"""MCP server 配置 + 多 server 客户端池。

ConfigStore 持久化的是 McpServerConfig，启动期由 McpClientRegistry 实例化
对应的 McpClient，调 connect() 拉工具列表，再统一交给百工坊 Tool 注册。

健康检查 / 自动重连 / SSE 远程支持留 0.7+。当前先把 stdio 那条最常用的路跑通。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Literal

from pydantic import BaseModel, Field

from xuanji.mcp.adapter import McpToolAdapter
from xuanji.mcp.client import McpClient, McpClientError
from xuanji.mcp.protocol import McpToolDef
from xuanji.mcp.transport import StdioTransport

log = logging.getLogger(__name__)


class McpServerConfig(BaseModel):
    """单个 MCP server 的连接配置（持久化到 config.json）。"""

    name: str = Field(min_length=1, max_length=64, description="server 显式名，工具前缀用")
    transport: Literal["stdio", "http+sse"] = "stdio"
    command: str | None = Field(
        default=None, description="stdio 模式下的可执行文件路径或 PATH 名"
    )
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = Field(default=None, description="http+sse 模式的 server URL")
    enabled: bool = True
    description: str = ""


class McpServerHandle(BaseModel):
    """已建立连接的 server 句柄（运行时态，不持久化）。"""

    model_config = {"arbitrary_types_allowed": True}

    config: McpServerConfig
    client: McpClient
    tools: list[McpToolDef] = Field(default_factory=list)
    adapters: list[McpToolAdapter] = Field(default_factory=list)
    error: str | None = None


class McpClientRegistry:
    """多 server 协同。

    用法：
        reg = McpClientRegistry([cfg1, cfg2])
        await reg.connect_all()
        for adapter in reg.all_adapters():
            tool_registry.register(adapter)
        ...
        await reg.close_all()
    """

    def __init__(self, configs: list[McpServerConfig]) -> None:
        self._configs = configs
        self._handles: dict[str, McpServerHandle] = {}

    @property
    def handles(self) -> dict[str, McpServerHandle]:
        return self._handles

    async def connect_all(self, *, connect_timeout: float = 10.0) -> None:
        """并发拉起所有 enabled server。失败的不抛——记录到 handle.error。"""
        tasks: list[asyncio.Task[None]] = []
        for cfg in self._configs:
            if not cfg.enabled:
                continue
            tasks.append(asyncio.create_task(self._connect_one(cfg, connect_timeout)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect_one(
        self, cfg: McpServerConfig, timeout: float,
    ) -> None:
        if cfg.transport != "stdio":
            handle = McpServerHandle(
                config=cfg,
                client=_DummyClient(),
                error=f"transport={cfg.transport} 暂未实装（0.7+ 计划）",
            )
            self._handles[cfg.name] = handle
            return
        if not cfg.command:
            self._handles[cfg.name] = McpServerHandle(
                config=cfg,
                client=_DummyClient(),
                error="stdio 模式必须配 command",
            )
            return
        transport = StdioTransport(
            cfg.command, cfg.args, cwd=cfg.cwd, env=dict(cfg.env) if cfg.env else None,
        )
        client = McpClient(transport)
        handle = McpServerHandle(config=cfg, client=client)
        try:
            async with asyncio.timeout(timeout):
                await client.connect()
                tools = await client.list_tools()
        except (TimeoutError, McpClientError, Exception) as e:
            handle.error = f"{type(e).__name__}: {e}"
            log.warning("MCP server %s 连接失败：%s", cfg.name, handle.error)
            with contextlib.suppress(Exception):
                await client.close()
            self._handles[cfg.name] = handle
            return
        handle.tools = tools
        handle.adapters = [
            McpToolAdapter(client=client, server_name=cfg.name, tool_def=t)
            for t in tools
        ]
        self._handles[cfg.name] = handle
        log.info(
            "MCP server %s 已连接，收编 %d 工具", cfg.name, len(tools),
        )

    def all_adapters(self) -> list[McpToolAdapter]:
        out: list[McpToolAdapter] = []
        for h in self._handles.values():
            out.extend(h.adapters)
        return out

    def health_summary(self) -> dict[str, str]:
        """给 doctor / status 用：每个 server 一行状态。"""
        out: dict[str, str] = {}
        for name, h in self._handles.items():
            if h.error:
                out[name] = f"error: {h.error}"
            else:
                out[name] = f"ok ({len(h.tools)} tools)"
        return out

    async def close_all(self) -> None:
        for h in list(self._handles.values()):
            try:
                await h.client.close()
            except Exception as e:
                log.debug("关闭 MCP server %s 报错：%s", h.config.name, e)
        self._handles.clear()


class _DummyClient(McpClient):
    """占位 client：用于持有失败的 handle，避免 Optional 污染调用方。"""

    def __init__(self) -> None:
        # 不真的 init transport——任何方法被调都会抛
        self.transport = None  # type: ignore[assignment]
        self.client_info = None  # type: ignore[assignment]
        self.request_timeout = 0.0
        self.server_info = None
        self._next_id = 0
        self._pending = {}
        self._reader_task = None
        self._closing = True

    async def connect(self) -> None:  # type: ignore[override]
        raise McpClientError("dummy client 不支持 connect")

    async def close(self) -> None:
        return None


__all__ = ["McpClientRegistry", "McpServerConfig", "McpServerHandle"]
