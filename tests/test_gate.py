"""司辰阁单测：策略 + 拦截器 + HITL 桥接。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from xuanji.gate import (
    DefaultPolicy,
    GateInterceptor,
    GateRefusal,
    HITLBridge,
    NoOpHITLBridge,
    VerdictKind,
)


class _StubTool(Tool):
    """测试桩：可设定任意 risk。"""

    name = "stub"
    schema: ClassVar[dict[str, Any]] = {"type": "object"}

    def __init__(self, risk: RiskTag) -> None:
        self.risk = risk  # type: ignore[misc]

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output="stubbed")


class _AlwaysAllow(HITLBridge):
    async def confirm(self, *, tool: Tool, args: dict[str, Any], reason: str) -> bool:
        return True


class _AlwaysReject(HITLBridge):
    async def confirm(self, *, tool: Tool, args: dict[str, Any], reason: str) -> bool:
        return False


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


# ----------- DefaultPolicy -----------


def test_safe_passes(ctx: ToolCtx) -> None:
    v = DefaultPolicy().evaluate(_StubTool(RiskTag.SAFE), {}, ctx)
    assert v.kind == VerdictKind.PASS


def test_destructive_denied(ctx: ToolCtx) -> None:
    v = DefaultPolicy().evaluate(_StubTool(RiskTag.DESTRUCTIVE), {}, ctx)
    assert v.kind == VerdictKind.DENY


def test_exec_requires_hitl(ctx: ToolCtx) -> None:
    v = DefaultPolicy().evaluate(_StubTool(RiskTag.EXEC), {"command": "ls"}, ctx)
    assert v.kind == VerdictKind.HITL
    assert "ls" in v.reason


def test_io_inside_project_passes(tmp_path: Path, ctx: ToolCtx) -> None:
    v = DefaultPolicy().evaluate(_StubTool(RiskTag.IO), {"path": "out.txt"}, ctx)
    assert v.kind == VerdictKind.PASS


def test_io_outside_project_requires_hitl(tmp_path: Path, ctx: ToolCtx) -> None:
    outside = tmp_path.parent / "outside.txt"
    v = DefaultPolicy().evaluate(_StubTool(RiskTag.IO), {"path": str(outside)}, ctx)
    assert v.kind == VerdictKind.HITL


# ----------- GateInterceptor -----------


@pytest.mark.asyncio
async def test_gate_passes_safe_tool(ctx: ToolCtx) -> None:
    gate = GateInterceptor(bridge=NoOpHITLBridge())
    v = await gate.check(_StubTool(RiskTag.SAFE), {}, ctx)
    assert v.kind == VerdictKind.PASS


@pytest.mark.asyncio
async def test_gate_blocks_destructive(ctx: ToolCtx) -> None:
    gate = GateInterceptor(bridge=NoOpHITLBridge())
    with pytest.raises(GateRefusal) as ei:
        await gate.check(_StubTool(RiskTag.DESTRUCTIVE), {}, ctx)
    assert ei.value.verdict.kind == VerdictKind.DENY


@pytest.mark.asyncio
async def test_gate_hitl_user_allows(ctx: ToolCtx) -> None:
    gate = GateInterceptor(bridge=_AlwaysAllow())
    v = await gate.check(_StubTool(RiskTag.EXEC), {"command": "ls"}, ctx)
    assert v.kind == VerdictKind.HITL


@pytest.mark.asyncio
async def test_gate_hitl_user_rejects(ctx: ToolCtx) -> None:
    gate = GateInterceptor(bridge=_AlwaysReject())
    with pytest.raises(GateRefusal) as ei:
        await gate.check(_StubTool(RiskTag.EXEC), {"command": "ls"}, ctx)
    assert ei.value.verdict.kind == VerdictKind.DENY
    assert "用户拒绝" in ei.value.verdict.reason


@pytest.mark.asyncio
async def test_noop_bridge_rejects_everything(ctx: ToolCtx) -> None:
    """无人值守的 NoOp 桥接对任何 HITL 都说 No。"""
    bridge = NoOpHITLBridge()
    ok = await bridge.confirm(
        tool=_StubTool(RiskTag.EXEC), args={"command": "rm -rf"}, reason="test"
    )
    assert ok is False
