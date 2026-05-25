"""沙箱协议。"""

from __future__ import annotations

from typing import Any, Protocol

from core.capability.tool import Tool, ToolCtx, ToolResult


class Sandbox(Protocol):
    """工具执行沙箱。

    M0 只有 InProc。M2+ 按 RiskTag 自动选档：
    - safe / io  → InProc
    - exec       → Subprocess（带 rlimit）
    - net        → 受限 HTTP client
    - destructive → 永远拒绝（在 Gate 已经拦掉，不会到这里）
    """

    async def run(
        self,
        tool: Tool,
        args: dict[str, Any],
        ctx: ToolCtx,
        *,
        timeout_sec: float = 30.0,
    ) -> ToolResult: ...
