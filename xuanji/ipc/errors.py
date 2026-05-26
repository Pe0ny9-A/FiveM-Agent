"""JSON-RPC 错误码（与 spec 一致）。"""

from __future__ import annotations


class RpcError(Exception):
    """JSON-RPC 错误。会被转成 {error: {code, message}} 响应。"""

    def __init__(self, code: int, message: str, data: object | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# JSON-RPC 2.0 spec 定义的标准码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# 应用自定义码（spec 留出 -32000 ~ -32099 给服务端实现）
TOOL_ERROR = -32000
GATE_REFUSAL = -32001
NOT_INITIALIZED = -32002


__all__ = [
    "GATE_REFUSAL",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "NOT_INITIALIZED",
    "PARSE_ERROR",
    "TOOL_ERROR",
    "RpcError",
]
