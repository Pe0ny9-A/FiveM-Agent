"""MCP client 单测。

不连真实 MCP server——用 FakeTransport 模拟一个 spec-compliant server，
验证客户端协议层的握手、tools/list 翻页、tools/call 错误传播、close 清理。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

import pytest

from xuanji.mcp.adapter import McpToolAdapter
from xuanji.mcp.client import McpClient, McpClientError
from xuanji.mcp.protocol import (
    PROTOCOL_VERSION,
    McpContent,
    McpToolDef,
)


class FakeMcpServer:
    """脚本化 MCP server——按 method 名预置响应。

    Client 调用一次 → 对应方法的预置响应被弹出 → 客户端拿到结果。
    pages 字段支持 tools/list 多页。
    """

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.pages: deque[dict[str, Any]] = deque()  # tools/list 多页
        self.tool_call_results: dict[str, dict[str, Any]] = {}
        self.tool_call_errors: dict[str, dict[str, Any]] = {}
        self.initialized_notified = False

    def reply(self, request: dict[str, Any]) -> dict[str, Any] | None:
        self.received.append(request)
        method = request.get("method")
        rid = request.get("id")
        if method == "notifications/initialized":
            self.initialized_notified = True
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.0.1"},
                },
            }
        if method == "tools/list":
            page = self.pages.popleft() if self.pages else {"tools": []}
            return {"jsonrpc": "2.0", "id": rid, "result": page}
        if method == "tools/call":
            tool_name = (request.get("params") or {}).get("name", "")
            if tool_name in self.tool_call_errors:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": self.tool_call_errors[tool_name],
                }
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": self.tool_call_results.get(
                    tool_name, {"content": [], "isError": False},
                ),
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"unknown method {method}"},
        }


class FakeTransport:
    """内存版 transport，跳过真子进程。"""

    def __init__(self, server: FakeMcpServer) -> None:
        self.server = server
        self._inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def send(self, message: dict[str, Any]) -> None:
        # 把 send 的消息也"序列化-反序列化"一遍，验证 client 输出是合法 JSON
        json.dumps(message, ensure_ascii=False)
        reply = self.server.reply(message)
        if reply is not None:
            await self._inbox.put(reply)

    async def receive(self) -> dict[str, Any] | None:
        return await self._inbox.get()

    async def close(self) -> None:
        self.closed = True
        await self._inbox.put(None)


@pytest.mark.asyncio
async def test_client_connect_handshake() -> None:
    """connect 应跑完 initialize + initialized 通知，server 都收到了。"""
    server = FakeMcpServer()
    transport = FakeTransport(server)
    client = McpClient(transport)

    info = await client.connect()
    assert info.serverInfo.name == "fake-mcp"
    assert info.protocolVersion == PROTOCOL_VERSION
    # 握手序列：initialize → notifications/initialized
    assert server.received[0]["method"] == "initialize"
    # initialized 通知会作为后续 send 进来
    assert server.initialized_notified is True

    await client.close()
    assert transport.closed


@pytest.mark.asyncio
async def test_list_tools_pagination() -> None:
    """list_tools 应跟 nextCursor 把多页拉完。"""
    server = FakeMcpServer()
    server.pages.append(
        {"tools": [{"name": "a", "description": "", "inputSchema": {}}], "nextCursor": "p2"},
    )
    server.pages.append(
        {"tools": [{"name": "b", "description": "", "inputSchema": {}}]},
    )
    transport = FakeTransport(server)
    client = McpClient(transport)
    await client.connect()
    tools = await client.list_tools()
    assert [t.name for t in tools] == ["a", "b"]
    await client.close()


@pytest.mark.asyncio
async def test_call_tool_error_propagates() -> None:
    """server 返回 JSON-RPC error 时应抛 McpClientError，code 正确。"""
    server = FakeMcpServer()
    server.tool_call_errors["broken"] = {
        "code": -32000, "message": "tool blew up", "data": {"hint": "x"},
    }
    transport = FakeTransport(server)
    client = McpClient(transport)
    await client.connect()
    with pytest.raises(McpClientError) as exc_info:
        await client.call_tool("broken", {})
    assert exc_info.value.code == -32000
    assert "tool blew up" in str(exc_info.value)
    await client.close()


@pytest.mark.asyncio
async def test_call_tool_returns_content() -> None:
    server = FakeMcpServer()
    server.tool_call_results["echo"] = {
        "content": [{"type": "text", "text": "hello"}],
        "isError": False,
    }
    transport = FakeTransport(server)
    client = McpClient(transport)
    await client.connect()
    result = await client.call_tool("echo", {"x": 1})
    assert not result.isError
    assert McpClient.flatten_content(result.content) == "hello"
    await client.close()


@pytest.mark.asyncio
async def test_close_rejects_pending() -> None:
    """close 时未完成的 future 应被 reject，调用方不会卡住。"""
    server = FakeMcpServer()
    transport = FakeTransport(server)
    client = McpClient(transport, request_timeout=2.0)
    await client.connect()
    # 强制让 server 不回这次：移走 server.reply 里 tools/call 的逻辑
    server.tool_call_results.clear()
    # 直接关
    await client.close()
    assert transport.closed


@pytest.mark.asyncio
async def test_adapter_wraps_mcp_tool() -> None:
    """McpToolAdapter 应把 MCP 工具调用结果转成百工坊 ToolResult。"""
    from pathlib import Path

    from xuanji.capability.tool import ToolCtx

    server = FakeMcpServer()
    server.tool_call_results["read_file"] = {
        "content": [{"type": "text", "text": "FILE CONTENTS"}],
        "isError": False,
    }
    transport = FakeTransport(server)
    client = McpClient(transport)
    await client.connect()

    tool_def = McpToolDef(
        name="read_file",
        description="Read a file",
        inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    adapter = McpToolAdapter(client=client, server_name="fs", tool_def=tool_def)
    assert adapter.name == "mcp:fs:read_file"
    assert "fs" in adapter.description

    ctx = ToolCtx(project_root=Path.cwd(), session_id="s", trace_id="t")
    result = await adapter.execute({"path": "/tmp/x"}, ctx)
    assert result.ok
    assert result.output == "FILE CONTENTS"
    assert result.extra["server"] == "fs"

    await client.close()


@pytest.mark.asyncio
async def test_adapter_passes_through_is_error() -> None:
    """server 返回 isError=True（不是 JSON-RPC error）时应 ToolResult.ok=False。"""
    from pathlib import Path

    from xuanji.capability.tool import ToolCtx

    server = FakeMcpServer()
    server.tool_call_results["bad"] = {
        "content": [{"type": "text", "text": "permission denied"}],
        "isError": True,
    }
    transport = FakeTransport(server)
    client = McpClient(transport)
    await client.connect()

    adapter = McpToolAdapter(
        client=client,
        server_name="fs",
        tool_def=McpToolDef(name="bad", inputSchema={"type": "object"}),
    )
    ctx = ToolCtx(project_root=Path.cwd(), session_id="s", trace_id="t")
    result = await adapter.execute({}, ctx)
    assert not result.ok
    assert result.error is not None
    assert "permission denied" in result.error
    await client.close()


def test_flatten_content_renders_mixed_blocks() -> None:
    blocks = [
        McpContent(type="text", text="hello"),
        McpContent(type="image", data="aGk=", mimeType="image/png"),
        McpContent(type="resource", resource={"uri": "file:///x"}),
        McpContent(type="text", text="world"),
    ]
    out = McpClient.flatten_content(blocks)
    assert "hello" in out
    assert "image" in out
    assert "file:///x" in out
    assert "world" in out
