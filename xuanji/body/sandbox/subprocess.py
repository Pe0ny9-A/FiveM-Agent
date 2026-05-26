"""子进程沙箱：把工具丢到独立 Python 进程跑，父进程靠 timeout 杀掉。

只对显式标了 `is_subprocess_safe = True` 的工具放行。
其他工具会回退一个 ok=False 的 ToolResult，避免悄悄降级到 InProc。

实现要点：
- `python -m xuanji.body.sandbox.subproc_runner` 起子进程
- stdin 喂 JSON（module / qualname / args / ctx），stdout 收一行 ToolResult JSON
- timeout 由父进程 `wait_for + proc.kill()` 兜底
- Windows 上 stdout 默认不是 UTF-8，靠 PYTHONUTF8=1 + PYTHONIOENCODING 强制改
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Protocol

from xuanji.capability.tool import Tool, ToolCtx, ToolResult


class _SandboxLike(Protocol):
    async def run(
        self,
        tool: Tool,
        args: dict[str, Any],
        ctx: ToolCtx,
        *,
        timeout_sec: float = ...,
    ) -> ToolResult: ...


def _utf8_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class SubprocessSandbox:
    """跨进程沙箱。

    要求工具：
    - `is_subprocess_safe = True`
    - `__init__` 无必填参数
    - 不持有跨进程不能复活的状态（DB 连接、句柄、大对象）
    """

    def __init__(self, *, python_executable: str | None = None) -> None:
        self._python = python_executable or sys.executable

    async def run(
        self,
        tool: Tool,
        args: dict[str, Any],
        ctx: ToolCtx,
        *,
        timeout_sec: float = 30.0,
    ) -> ToolResult:
        started = time.perf_counter()
        if not getattr(tool, "is_subprocess_safe", False):
            return ToolResult(
                ok=False,
                error=f"工具 {tool.name!r} 未声明 is_subprocess_safe，拒绝跨进程执行",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        cls = type(tool)
        payload = {
            "module": cls.__module__,
            "qualname": cls.__qualname__,
            "args": args,
            "ctx": {
                "project_root": str(ctx.project_root),
                "session_id": ctx.session_id,
                "trace_id": ctx.trace_id,
            },
        }

        proc = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            "xuanji.body.sandbox.subproc_runner",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_utf8_env(),
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(json.dumps(payload).encode("utf-8")),
                timeout=timeout_sec,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                ok=False,
                error=f"子进程执行超时（{timeout_sec}s）",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        duration_ms = int((time.perf_counter() - started) * 1000)

        if proc.returncode != 0:
            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            return ToolResult(
                ok=False,
                error=f"子进程崩溃（exit={proc.returncode}）：{stderr_text[:500]}",
                duration_ms=duration_ms,
            )

        stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
        if not stdout_text:
            return ToolResult(
                ok=False,
                error="子进程未返回任何输出",
                duration_ms=duration_ms,
            )

        try:
            data = json.loads(stdout_text)
            result = ToolResult.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            return ToolResult(
                ok=False,
                error=f"无法解析子进程输出：{e}",
                duration_ms=duration_ms,
            )

        if result.duration_ms == 0:
            result.duration_ms = duration_ms
        return result


class RoutingSandbox:
    """按工具属性路由到 InProc 或 Subprocess。

    决策：
    - `is_subprocess_safe == True` → SubprocessSandbox
    - 否则 → InProcSandbox

    Conductor 默认仍用 InProc。要启用路由就显式传 `sandbox=RoutingSandbox(...)`。
    """

    def __init__(
        self,
        *,
        inproc: _SandboxLike,
        subprocess: SubprocessSandbox | None = None,
    ) -> None:
        self._inproc = inproc
        self._subprocess = subprocess or SubprocessSandbox()

    async def run(
        self,
        tool: Tool,
        args: dict[str, Any],
        ctx: ToolCtx,
        *,
        timeout_sec: float = 30.0,
    ) -> ToolResult:
        if getattr(tool, "is_subprocess_safe", False):
            return await self._subprocess.run(tool, args, ctx, timeout_sec=timeout_sec)
        return await self._inproc.run(tool, args, ctx, timeout_sec=timeout_sec)
