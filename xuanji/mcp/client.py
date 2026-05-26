"""MCP Client：和单个 MCP server 维持一条会话。

职责：
- 启动 transport（默认 stdio 子进程）
- 跑 initialize 握手 + 发 initialized 通知
- 维护 outgoing request 的 id 与 future 表，分发响应
- 提供 list_tools / call_tool 这两个高层 API
- 关闭时清理子进程

不负责：连接池、健康检查、自动重连——那是 registry 的事。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from xuanji.mcp.protocol import (
    PROTOCOL_VERSION,
    ClientCapabilities,
    ClientInfo,
    InitializeResult,
    JsonRpcRequest,
    McpContent,
    McpToolCallResult,
    McpToolDef,
    McpToolListResult,
)
from xuanji.mcp.transport import McpTransport, StdioTransport


class McpClientError(Exception):
    """MCP 调用失败：协议错误、server 报 error、超时等都走这条。"""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class McpClient:
    """单 server 的 MCP 客户端。

    生命周期：
        client = McpClient(transport)
        await client.connect()   # transport.start + initialize 握手
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "..."})
        await client.close()
    """

    def __init__(
        self,
        transport: McpTransport,
        *,
        name: str = "xuanji",
        version: str = "0.6.0",
        request_timeout: float = 30.0,
    ) -> None:
        self.transport = transport
        self.client_info = ClientInfo(name=name, version=version)
        self.request_timeout = request_timeout
        self.server_info: InitializeResult | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._closing = False

    @classmethod
    def stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> McpClient:
        """便利构造器：直接给 command + args，内部自动建 stdio transport。"""
        transport = StdioTransport(command, args or [], cwd=cwd, env=env)
        return cls(transport, **kwargs)

    async def connect(self) -> InitializeResult:
        """启动 transport、握手、返回 server 信息。"""
        await self.transport.start()
        self._reader_task = asyncio.create_task(self._read_loop())
        result = await self._initialize()
        await self._send_notification("notifications/initialized", {})
        self.server_info = result
        return result

    async def _initialize(self) -> InitializeResult:
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": ClientCapabilities().model_dump(exclude_none=True),
            "clientInfo": self.client_info.model_dump(),
        }
        raw = await self._call("initialize", params)
        return InitializeResult.model_validate(raw)

    async def list_tools(self, *, cursor: str | None = None) -> list[McpToolDef]:
        """返回 server 暴露的全部工具（自动跟着 nextCursor 翻页）。"""
        all_tools: list[McpToolDef] = []
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        while True:
            raw = await self._call("tools/list", params if params else None)
            page = McpToolListResult.model_validate(raw)
            all_tools.extend(page.tools)
            if not page.nextCursor:
                break
            params = {"cursor": page.nextCursor}
        return all_tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResult:
        """调一个 server 工具，把它的 result 原样返回。"""
        params: dict[str, Any] = {"name": name}
        if arguments is not None:
            params["arguments"] = arguments
        raw = await self._call("tools/call", params)
        return McpToolCallResult.model_validate(raw)

    async def ping(self) -> None:
        """ping/pong 健康检查。失败抛 McpClientError。"""
        await self._call("ping", None)

    async def close(self) -> None:
        self._closing = True
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(McpClientError("MCP 客户端关闭"))
        self._pending.clear()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None
        await self.transport.close()

    # ------------------------------ 内部 ------------------------------

    def _alloc_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def _call(self, method: str, params: dict[str, Any] | None) -> Any:
        rid = self._alloc_id()
        req = JsonRpcRequest(id=rid, method=method, params=params)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[rid] = fut
        try:
            await self.transport.send(req.model_dump(exclude_none=True))
            return await asyncio.wait_for(fut, timeout=self.request_timeout)
        except TimeoutError as e:
            self._pending.pop(rid, None)
            raise McpClientError(f"MCP 调用 {method} 超时") from e

    async def _send_notification(
        self, method: str, params: dict[str, Any] | None,
    ) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self.transport.send(msg)

    async def _read_loop(self) -> None:
        """后台跑 transport.receive()，按消息类型分发到 _pending future。"""
        while not self._closing:
            try:
                msg = await self.transport.receive()
            except Exception as e:
                # transport 自己挂了，把所有 pending 全 reject
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(McpClientError(f"transport 异常：{e}"))
                self._pending.clear()
                return
            if msg is None:
                # server 关闭
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(McpClientError("MCP server 已关闭"))
                self._pending.clear()
                return
            self._dispatch(msg)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        # 响应：有 id，有 result 或 error
        if "id" in msg and ("result" in msg or "error" in msg):
            rid = msg["id"]
            fut = self._pending.pop(rid, None) if isinstance(rid, int) else None
            if fut is None or fut.done():
                return
            if msg.get("error"):
                err = msg["error"]
                fut.set_exception(
                    McpClientError(
                        err.get("message", "MCP server 报错"),
                        code=err.get("code"),
                        data=err.get("data"),
                    ),
                )
            else:
                fut.set_result(msg.get("result"))
            return
        # 通知：method 但无 id——目前不处理（log/进度通知留 0.7+ 实装）

    @staticmethod
    def flatten_content(blocks: list[McpContent]) -> str:
        """把 server 返回的多 content 块拼成单段文本，给百工坊 ToolResult 用。"""
        parts: list[str] = []
        for b in blocks:
            if b.type == "text" and b.text:
                parts.append(b.text)
            elif b.type == "image" and b.data:
                parts.append(f"[image: {b.mimeType or 'unknown'} {len(b.data)}B]")
            elif b.type == "resource" and b.resource:
                parts.append(f"[resource: {b.resource.get('uri', '?')}]")
            else:
                parts.append(f"[{b.type}]")
        return "\n".join(parts)


__all__ = ["McpClient", "McpClientError"]
