"""MCP Server（xuanji mcp-serve）单测。

不起真子进程——直接调 process_message 跑 RPC 流：
- initialize 握手返回正确 protocolVersion / capabilities
- tools/list 列出注册工具
- tools/call 跑 SAFE 工具成功
- tools/call 跑 EXEC 工具被 Gate 拦
- tools/call 未知工具返回 isError=True
- ping 健康检查
- 未知 method 返回 -32601
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from xuanji.mcp.protocol import PROTOCOL_VERSION
from xuanji.mcp.server import McpServer
from xuanji.tools.builtin import ListDirTool, RunShellTool


class _EchoTool(Tool):
    name = "echo"
    description = "测试用：原样返回 text"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output=args["text"])


def _server(tmp_path: Path) -> McpServer:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(ListDirTool())
    reg.register(RunShellTool())
    return McpServer(reg, project_root=tmp_path)


@pytest.mark.asyncio
async def test_initialize_returns_protocol_and_capabilities(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    })
    assert resp is not None
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "xuanji"


@pytest.mark.asyncio
async def test_initialized_notification_does_not_reply(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    assert resp is None


@pytest.mark.asyncio
async def test_ping(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert resp is not None
    assert resp["result"] == {}


@pytest.mark.asyncio
async def test_tools_list(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert resp is not None
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"echo", "list_dir", "run_shell"} <= names
    # 每条都带 inputSchema
    for t in tools:
        assert "inputSchema" in t


@pytest.mark.asyncio
async def test_tools_call_safe_tool(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "你好姐姐"}},
    })
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is False
    assert result["content"][0]["text"] == "你好姐姐"


@pytest.mark.asyncio
async def test_tools_call_exec_tool_blocked_by_gate(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "run_shell", "arguments": {"command": "echo hi"}},
    })
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is True
    assert "司辰阁" in result["content"][0]["text"] or "拦截" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_unknown_tool(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "nope", "arguments": {}},
    })
    assert resp is not None
    result = resp["result"]
    assert result["isError"] is True


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    resp = await srv.process_message({"jsonrpc": "2.0", "id": 7, "method": "unknown/method"})
    assert resp is not None
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tools_call_invalid_params(tmp_path: Path) -> None:
    srv = _server(tmp_path)
    # name 不是 string
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": 123, "arguments": {}},
    })
    assert resp is not None
    assert resp["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_response_round_trips_json(tmp_path: Path) -> None:
    """响应必须是合法 JSON——确保中文 / 嵌套 dict 都能序列化。"""
    srv = _server(tmp_path)
    resp = await srv.process_message({
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "中文「带标点」"}},
    })
    assert resp is not None
    encoded = json.dumps(resp, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["result"]["content"][0]["text"] == "中文「带标点」"
