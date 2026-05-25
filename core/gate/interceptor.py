"""GateInterceptor：横切到 Conductor.dispatch 的中间件。"""

from __future__ import annotations

from typing import Any

from core.capability.tool import Tool, ToolCtx
from core.gate.bridge import HITLBridge
from core.gate.policy import DefaultPolicy, Policy, Verdict, VerdictKind


class GateRefusal(Exception):
    """Gate 拦截下来的工具调用。携带裁决与原因。"""

    def __init__(self, verdict: Verdict, tool: Tool, tool_args: dict[str, Any]) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict
        self.tool = tool
        self.tool_args = tool_args


class GateInterceptor:
    """Conductor.dispatch 的前置守门员。

    流程：
    1. policy.evaluate 拿裁决
    2. PASS → 直接 OK
    3. DENY → 抛 GateRefusal
    4. HITL → 调 bridge.confirm；同意 OK，拒绝抛 GateRefusal
    """

    def __init__(
        self,
        *,
        policy: Policy | None = None,
        bridge: HITLBridge,
    ) -> None:
        self.policy = policy or DefaultPolicy()
        self.bridge = bridge

    async def check(self, tool: Tool, args: dict[str, Any], ctx: ToolCtx) -> Verdict:
        verdict = self.policy.evaluate(tool, args, ctx)
        if verdict.kind == VerdictKind.PASS:
            return verdict
        if verdict.kind == VerdictKind.DENY:
            raise GateRefusal(verdict, tool, args)
        # HITL
        ok = await self.bridge.confirm(tool=tool, args=args, reason=verdict.reason)
        if not ok:
            raise GateRefusal(
                Verdict.deny(f"用户拒绝：{verdict.reason}"), tool, args
            )
        return verdict
