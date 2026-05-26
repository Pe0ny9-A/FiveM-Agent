"""MCP Server 端：把玄玑的 26+ 个内置工具透过 stdio 暴露给任意 MCP 兼容客户端。

设计要点：
- stdio NDJSON（spec 一致）；CC / Codex / 任何 MCP-compliant client 都能挂
- 复用 ServerRuntime.build_registry() —— 工具列表跟 chat / serve / ipc 完全一致
- 不引入新调度：tools/call 内部走 InProcSandbox（含 Gate 拦截），与主 Conductor 一致
- 不做 sampling、不做 resources/prompts —— 这版只暴露 tools

入口：`xuanji mcp-serve`（在 cli.py 里挂上）
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from xuanji.body.sandbox import InProcSandbox, Sandbox
from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import ToolCtx, tool_to_anthropic_schema
from xuanji.gate.bridge import NoOpHITLBridge
from xuanji.gate.interceptor import GateInterceptor, GateRefusal
from xuanji.mcp.protocol import (
    PROTOCOL_VERSION,
    InitializeResult,
    JsonRpcError,
    JsonRpcResponse,
    McpContent,
    McpToolCallResult,
    McpToolDef,
    McpToolListResult,
    ServerCapabilities,
    ServerInfo,
)


class McpServer:
    """单实例 MCP server。

    生命周期：
        srv = McpServer(registry)
        await srv.run_stdio()  # 阻塞跑到 stdin EOF

    线程模型：单事件循环，按行读 stdin、按行写 stdout，不并发派发请求
    （MCP spec 没规定 server 必须并发；按顺序处理简单可控）。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        server_name: str = "xuanji",
        server_version: str = "0.7.0",
        gate: GateInterceptor | None = None,
        sandbox: Sandbox | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.registry = registry
        self.server_info = ServerInfo(name=server_name, version=server_version)
        self.gate = gate or GateInterceptor(bridge=NoOpHITLBridge())
        self.sandbox = sandbox or InProcSandbox()
        self.project_root = (project_root or Path.cwd()).resolve()
        self._initialized = False
        self._session_id = "mcp-stdio"

    async def run_stdio(self) -> None:
        """阻塞主循环：从 sys.stdin 读 NDJSON，写 sys.stdout。

        Windows 下 stdin/stdout 二进制处理由 xuanji ipc 入口或本模块的
        bootstrap 负责（设置 PYTHONUTF8=1 / 用 binary mode）。
        """
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        # stdout 走同步 print + flush，足够（每条消息很小）
        while True:
            line = await reader.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                self._write({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                })
                continue
            await self._handle(msg)

    async def process_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """单消息派发，便于测试。返回响应；通知返回 None。"""
        method = msg.get("method")
        rid = msg.get("id")
        params = msg.get("params") or {}

        if rid is None and method:
            await self._handle_notification(method, params)
            return None

        try:
            result = await self._dispatch(method or "", params)
            return JsonRpcResponse(id=rid, result=result).model_dump(exclude_none=True)
        except _RpcError as e:
            return JsonRpcResponse(
                id=rid,
                error=JsonRpcError(code=e.code, message=e.message, data=e.data),
            ).model_dump(exclude_none=True)
        except Exception as e:
            return JsonRpcResponse(
                id=rid,
                error=JsonRpcError(
                    code=-32603,
                    message=f"Internal error: {type(e).__name__}: {e}",
                ),
            ).model_dump(exclude_none=True)

    async def _handle(self, msg: dict[str, Any]) -> None:
        resp = await self.process_message(msg)
        if resp is not None:
            self._write(resp)

    async def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        # 目前只关心 initialized；其他通知忽略
        if method == "notifications/initialized":
            self._initialized = True

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return self._handle_initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return self._handle_tools_list(params)
        if method == "tools/call":
            return await self._handle_tools_call(params)
        raise _RpcError(-32601, f"Method not found: {method}")

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        _ = params.get("protocolVersion")
        result = InitializeResult(
            protocolVersion=PROTOCOL_VERSION,
            capabilities=ServerCapabilities(tools={"listChanged": False}),
            serverInfo=self.server_info,
            instructions=(
                "玄玑（Xuanji）MCP server。暴露 FiveM 智能体的内置工具；"
                "高风险（EXEC / NET / DESTRUCTIVE）调用会被司辰阁 Gate 拒绝，"
                "请在客户端层面做人工确认后再决定是否重试。"
            ),
        )
        return result.model_dump(exclude_none=True)

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        # 不支持分页（玄玑目前 ~30 个工具，单页够）
        _ = params.get("cursor")
        defs: list[McpToolDef] = []
        for tool in self.registry.all():
            schema = tool_to_anthropic_schema(tool)
            defs.append(
                McpToolDef(
                    name=tool.name,
                    description=tool.description,
                    inputSchema=schema.get("input_schema") or {},
                ),
            )
        return McpToolListResult(tools=defs).model_dump(exclude_none=True)

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise _RpcError(-32602, "Invalid params: name must be a string")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise _RpcError(-32602, "Invalid params: arguments must be an object")

        tool = self.registry.get(name)
        if tool is None:
            return McpToolCallResult(
                content=[McpContent(type="text", text=f"未注册的工具：{name}")],
                isError=True,
            ).model_dump(exclude_none=True)

        ctx = ToolCtx(
            project_root=self.project_root,
            session_id=self._session_id,
            trace_id=f"mcp-{name}",
        )

        try:
            await self.gate.check(tool, args, ctx)
        except GateRefusal as e:
            return McpToolCallResult(
                content=[McpContent(type="text", text=f"司辰阁拦截：{e.verdict.reason}")],
                isError=True,
            ).model_dump(exclude_none=True)

        result = await self.sandbox.run(tool, args, ctx)
        text = self._stringify(result.output if result.ok else result.error)
        return McpToolCallResult(
            content=[McpContent(type="text", text=text)],
            isError=not result.ok,
        ).model_dump(exclude_none=True)

    @staticmethod
    def _stringify(output: object) -> str:
        if isinstance(output, str):
            return output
        if output is None:
            return ""
        try:
            return json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(output)

    def _write(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()


class _RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


__all__ = ["McpServer"]
