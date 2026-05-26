"""SubprocessSandbox 单测。

不引入额外测试 fixture——用 RunShellTool（已标 is_subprocess_safe=True）
作为正向用例，用一个小的失败工具验证错误归一化。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

from xuanji.body.sandbox import (
    InProcSandbox,
    RoutingSandbox,
    SubprocessSandbox,
)
from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.tools.builtin import ReadFileTool, RunShellTool


class _SafeEchoTool(Tool):
    """模块级测试工具——子进程能 import 它。"""

    name = "_safe_echo"
    risk = RiskTag.SAFE
    is_subprocess_safe = True
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output=args["text"])


class _RaisingTool(Tool):
    name = "_raising"
    risk = RiskTag.SAFE
    is_subprocess_safe = True
    schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        raise ToolError("故意失败")


def _ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.mark.asyncio
async def test_subprocess_runs_safe_tool(tmp_path: Path) -> None:
    sandbox = SubprocessSandbox()
    res = await sandbox.run(_SafeEchoTool(), {"text": "你好"}, _ctx(tmp_path))
    assert res.ok
    assert res.output == "你好"
    assert res.duration_ms > 0


@pytest.mark.asyncio
async def test_subprocess_propagates_tool_error(tmp_path: Path) -> None:
    sandbox = SubprocessSandbox()
    res = await sandbox.run(_RaisingTool(), {}, _ctx(tmp_path))
    assert not res.ok
    assert "故意失败" in (res.error or "")


@pytest.mark.asyncio
async def test_subprocess_refuses_unsafe_tool(tmp_path: Path) -> None:
    """is_subprocess_safe=False 的工具应被拒绝，避免悄悄降级。"""
    sandbox = SubprocessSandbox()
    res = await sandbox.run(ReadFileTool(), {"path": "x"}, _ctx(tmp_path))
    assert not res.ok
    assert "is_subprocess_safe" in (res.error or "")


@pytest.mark.asyncio
async def test_subprocess_timeout_kills(tmp_path: Path) -> None:
    """超时应触发子进程 kill 并归一化为 ToolResult(ok=False)。"""
    sandbox = SubprocessSandbox()
    sleep_cmd = (
        f'{sys.executable} -c "import time; time.sleep(5)"'
    )
    res = await sandbox.run(
        RunShellTool(),
        {"command": sleep_cmd, "timeout_sec": 30},
        _ctx(tmp_path),
        timeout_sec=0.5,
    )
    assert not res.ok
    assert "超时" in (res.error or "")


@pytest.mark.asyncio
async def test_routing_sandbox_picks_subprocess_for_safe_tools(tmp_path: Path) -> None:
    routing = RoutingSandbox(inproc=InProcSandbox())
    res = await routing.run(_SafeEchoTool(), {"text": "ok"}, _ctx(tmp_path))
    assert res.ok
    assert res.output == "ok"


@pytest.mark.asyncio
async def test_routing_sandbox_falls_back_to_inproc(tmp_path: Path) -> None:
    """ReadFileTool 没标 subprocess_safe，路由器应走 InProc。"""
    f = tmp_path / "hello.txt"
    f.write_text("姐姐", encoding="utf-8")
    routing = RoutingSandbox(inproc=InProcSandbox())
    res = await routing.run(
        ReadFileTool(), {"path": str(f)}, _ctx(tmp_path),
    )
    assert res.ok
    assert res.output == "姐姐"
