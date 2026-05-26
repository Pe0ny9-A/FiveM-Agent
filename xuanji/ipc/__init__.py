"""IPC（Inter-Process Communication）：stdio JSON-RPC 服务器。

让 VS Code 插件、Tauri 桌面壳等外部进程通过 stdio 调玄玑后端能力。
通信协议照搬 LSP 风格：

    Content-Length: <bytes>\\r\\n
    \\r\\n
    {"jsonrpc": "2.0", "id": 1, "method": "...", "params": {...}}

为什么不用纯 line-based JSON：
- LLM 工具结果可能含换行；line-based 不安全
- LSP 风格是 VS Code 生态事实标准

为什么不用 HTTP：
- VS Code 进程退出时自动杀子进程
- 不占端口，多 workspace 不冲突
"""

from xuanji.ipc.dispatcher import RpcMethod, build_dispatcher
from xuanji.ipc.errors import RpcError
from xuanji.ipc.framing import read_message, write_message
from xuanji.ipc.server import run_stdio_server

__all__ = [
    "RpcError",
    "RpcMethod",
    "build_dispatcher",
    "read_message",
    "run_stdio_server",
    "write_message",
]
