"""服务端 push notification 网关。

VS Code 插件 1.0 起，玄玑后端要主动把流式事件（chat.text_delta /
chat.tool_run_started / chat.hitl_request / council.progress 等）推给客户端。

JSON-RPC 2.0 通知 = 没有 id 的请求：
    {"jsonrpc": "2.0", "method": "...", "params": {...}}

并发安全：多个 chat 会话或 council 角色可能同时往 stdout 写，
用一个 asyncio.Lock 串行化 write_message，避免帧交错破坏 LSP 分帧。

stdout 关流 / OSError 静默吞掉——客户端断了就让它断，避免 server 崩。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, BinaryIO, Protocol

from xuanji.ipc.framing import write_message


class Notifier(Protocol):
    """服务端推流协议。"""

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        """发一条 JSON-RPC 通知给客户端。"""


class StdoutNotifier:
    """通过 stdout 推 JSON-RPC 通知，写操作串行化。"""

    def __init__(self, stream: BinaryIO | None = None) -> None:
        self._stream = stream or sys.stdout.buffer
        self._lock = asyncio.Lock()
        self._closed = False

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._closed:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        async with self._lock:
            try:
                await write_message(msg, self._stream)
            except (OSError, BrokenPipeError):
                self._closed = True

    def close(self) -> None:
        self._closed = True


class NoOpNotifier:
    """不推任何通知，单测里方便用。"""

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        return None


class CapturingNotifier:
    """记录所有通知，单测断言用。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        self.events.append((method, params))


__all__ = [
    "CapturingNotifier",
    "NoOpNotifier",
    "Notifier",
    "StdoutNotifier",
]
