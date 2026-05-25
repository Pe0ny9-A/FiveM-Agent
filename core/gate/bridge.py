"""HITL 桥接：抽象的"询问用户"接口。

CLI 用 typer.confirm 实现；Web/Tauri 后续走 WebSocket。
Conductor 不依赖具体实现，只持有 HITLBridge 协议引用。
"""

from __future__ import annotations

from typing import Any, Protocol

from core.capability.tool import Tool


class HITLBridge(Protocol):
    """人工确认桥接协议。"""

    async def confirm(
        self,
        *,
        tool: Tool,
        args: dict[str, Any],
        reason: str,
    ) -> bool:
        """询问用户是否放行。返回 True=放行，False=拒绝。"""


class NoOpHITLBridge:
    """空实现：所有 HITL 一律拒绝。

    用于无人值守环境（如 CI、批处理），保证 Gate 至少不会偷偷执行高危操作。
    """

    async def confirm(
        self,
        *,
        tool: Tool,
        args: dict[str, Any],
        reason: str,
    ) -> bool:
        return False
