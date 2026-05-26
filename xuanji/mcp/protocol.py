"""MCP 协议消息模型。

MCP（Model Context Protocol）是 Anthropic 主导的开放协议，传输层走
JSON-RPC 2.0，Client/Server 之间约定了一套 method 与 capability。

我们这里只覆盖 Client 侧用得到的子集：
- initialize / initialized
- tools/list / tools/call
- ping
- 通用 JSON-RPC 错误

完整 spec：https://spec.modelcontextprotocol.io
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "2025-03-26"
"""我们声明支持的 MCP 协议版本。Server 在 initialize 阶段会回它自己的版本，
不一致时由 McpClient.handshake 把双方拉到最大共同版本——目前 spec 还没出
incompat 的情况，按最严就声明这一个就够。"""


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 错误对象。"""

    code: int
    message: str
    data: Any = None


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 请求。"""

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str
    method: str
    params: dict[str, Any] | None = None


class JsonRpcNotification(BaseModel):
    """JSON-RPC 2.0 通知（无 id，无返回）。"""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 响应（成功或失败二选一）。"""

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    result: Any = None
    error: JsonRpcError | None = None


# ------------------------------ MCP 业务消息 ------------------------------


class ClientCapabilities(BaseModel):
    """Client 在 initialize 时声明自己支持哪些可选能力。"""

    sampling: dict[str, Any] | None = None
    """如果 server 想反向调 client 的 LLM，client 要声明 sampling。
    玄玑暂不支持反向调用——server 工具内部跑 LLM 自负其责。"""

    roots: dict[str, Any] | None = None


class ServerCapabilities(BaseModel):
    """Server 在 initialize 响应里告知支持哪些能力。"""

    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None


class ClientInfo(BaseModel):
    """Client 自我介绍，给 server 看的。"""

    name: str = "xuanji"
    version: str = "0.6.0"


class ServerInfo(BaseModel):
    """Server 在 initialize 里返回的身份信息。"""

    name: str
    version: str


class InitializeResult(BaseModel):
    """initialize 成功时 server 返回的 result。"""

    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: ServerInfo
    instructions: str | None = None


class McpToolDef(BaseModel):
    """tools/list 返回的单个工具描述。"""

    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class McpToolListResult(BaseModel):
    """tools/list 的响应 result。"""

    tools: list[McpToolDef] = Field(default_factory=list)
    nextCursor: str | None = None


class McpContent(BaseModel):
    """tools/call 返回的 content 单元（文本 / 图像 / 资源链接）。"""

    type: str
    text: str | None = None
    data: str | None = None
    mimeType: str | None = None
    resource: dict[str, Any] | None = None


class McpToolCallResult(BaseModel):
    """tools/call 的响应 result。"""

    content: list[McpContent] = Field(default_factory=list)
    isError: bool = False


__all__ = [
    "PROTOCOL_VERSION",
    "ClientCapabilities",
    "ClientInfo",
    "InitializeResult",
    "JsonRpcError",
    "JsonRpcNotification",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "McpContent",
    "McpToolCallResult",
    "McpToolDef",
    "McpToolListResult",
    "ServerCapabilities",
    "ServerInfo",
]
