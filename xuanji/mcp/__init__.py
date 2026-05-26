"""MCP（Model Context Protocol）适配子系统。

玄玑既做 Client（连别家的 MCP server，把工具收编进百工坊），
也做 Server（把自己 26+ 工具暴露给 Claude Code / Codex / 任意 spec-compliant client）。

- Client：xuanji.mcp.client / registry / adapter
- Server：xuanji.mcp.server （`xuanji mcp-serve` 入口）
- 通过 stdio newline-delimited JSON-RPC 2.0 通信
- HTTP+SSE 远程 server 留 transport 抽象，0.7+ 后再实装

入口对象：
- McpClient / McpClientRegistry：连别人
- McpServer：暴露自己
"""

from __future__ import annotations

from xuanji.mcp.adapter import McpToolAdapter
from xuanji.mcp.client import McpClient, McpClientError
from xuanji.mcp.protocol import McpToolDef
from xuanji.mcp.registry import McpClientRegistry, McpServerConfig
from xuanji.mcp.server import McpServer

__all__ = [
    "McpClient",
    "McpClientError",
    "McpClientRegistry",
    "McpServer",
    "McpServerConfig",
    "McpToolAdapter",
    "McpToolDef",
]
