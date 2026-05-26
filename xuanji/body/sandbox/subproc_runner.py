"""子进程沙箱入口脚本。

由 SubprocessSandbox 通过 `python -m xuanji.body.sandbox.subproc_runner` 拉起。

协议（stdin/stdout 各一行 JSON）：

stdin:
    {
        "module": "xuanji.tools.builtin",
        "qualname": "RunShellTool",
        "args": {...},
        "ctx": {"project_root": "...", "session_id": "...", "trace_id": "..."}
    }

stdout：单行 JSON 表示 ToolResult，失败也用同样格式（ok=False + error）。
所有 stderr 抛出的异常会被父进程捕获 + 归一化。

Windows 默认不是 UTF-8，进程启动时强制 reconfigure stdin/stdout 编码。
"""

from __future__ import annotations

import asyncio
import importlib
import io
import json
import sys
import traceback
from pathlib import Path

from xuanji.capability.tool import Tool, ToolCtx, ToolError, ToolResult


def _force_utf8() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
    if isinstance(sys.stdin, io.TextIOWrapper):
        sys.stdin.reconfigure(encoding="utf-8")


def _build_tool(module_name: str, qualname: str) -> Tool:
    mod = importlib.import_module(module_name)
    obj: object = mod
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, type):
        raise TypeError(f"{module_name}.{qualname} 不是类")
    instance = obj()
    if not isinstance(instance, Tool):
        raise TypeError(f"{module_name}.{qualname} 不是 Tool 子类")
    return instance


async def _run() -> ToolResult:
    payload = json.loads(sys.stdin.read())
    tool = _build_tool(payload["module"], payload["qualname"])
    args = payload.get("args") or {}
    ctx_data = payload.get("ctx") or {}
    ctx = ToolCtx(
        project_root=Path(ctx_data["project_root"]),
        session_id=ctx_data["session_id"],
        trace_id=ctx_data["trace_id"],
    )
    try:
        return await tool.execute(args, ctx)
    except ToolError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")


def main() -> None:
    _force_utf8()
    try:
        result = asyncio.run(_run())
        sys.stdout.write(result.model_dump_json())
        sys.stdout.flush()
    except Exception:
        sys.stderr.write(traceback.format_exc())
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
