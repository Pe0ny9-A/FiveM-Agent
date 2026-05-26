"""服务层运行时容器。

把 chat loop 里那一堆"开 store、注册工具、建 conductor"提取出来，
让 CLI 的 chat 命令、FastAPI 的 WebSocket 都从同一处拿到一致的注入。
"""

from __future__ import annotations

import os
from pathlib import Path

from xuanji.capability.registry import ToolRegistry
from xuanji.config import (
    ConfigStore,
    hooks_dir,
    knowledge_db_path,
    memory_db_path,
    scaffold_drafts_dir,
    scaffold_presets_dir,
    skills_dir,
    tool_drafts_dir,
    vector_db_path,
)
from xuanji.config.profiles import Profile
from xuanji.fivem import detect_fivem_context, summarize_for_prompt
from xuanji.fivem.scaffold import ScaffoldEngine
from xuanji.gate.bridge import HITLBridge, NoOpHITLBridge
from xuanji.hooks import HooksRegistry
from xuanji.knowledge import (
    HashingEmbedder,
    InMemoryVectorStore,
    LanceDBVectorStore,
    SqliteKnowledgeStore,
    VectorStore,
)
from xuanji.mcp.registry import McpClientRegistry
from xuanji.memory import SqliteMemoryStore
from xuanji.neural import Conductor
from xuanji.persona import PersonaMode
from xuanji.tools import (
    builtin_tools,
    ingest_tools_offline,
    knowledge_tools,
    memory_tools,
    meta_tools,
    skill_file_tools,
    skill_tools,
    tool_factory_tools,
)
from xuanji.tools.fivem import fivem_tools
from xuanji.tools.ingest_url import IngestUrlTool


class ServerRuntime:
    """单实例的玄玑运行时（每个进程一个）。

    线程安全说明：SQLite 连接每次操作都新开，所以 store 对象本身可共享；
    但 Conductor 持有会话 history，每次对话应新建一个 Conductor 实例。
    """

    def __init__(
        self,
        *,
        cfg_store: ConfigStore | None = None,
        project_namespace: str | None = None,
        attach_vector_index: bool = True,
        project_root: Path | None = None,
        vector_backend: str | None = None,
    ) -> None:
        self.cfg_store = cfg_store or ConfigStore()
        self.knowledge = SqliteKnowledgeStore(knowledge_db_path())
        self.memory = SqliteMemoryStore(memory_db_path())
        if attach_vector_index:
            embedder = HashingEmbedder()
            backend = vector_backend or os.environ.get("XUANJI_VECTOR_BACKEND", "inmemory")
            vstore: VectorStore = self._make_vector_store(backend, dim=embedder.dim)
            self.knowledge.attach_vector_index(embedder, vstore)
            self.vector_backend = backend
        else:
            self.vector_backend = "none"
        self.project_root = (project_root or Path.cwd()).resolve()
        self.project_namespace = project_namespace or self.project_root.name or "default"
        # FiveM 专精层：scaffold engine 用项目级用户预设目录
        self.scaffold_engine = ScaffoldEngine(
            user_presets_dir=scaffold_presets_dir(),
            drafts_dir=scaffold_drafts_dir(),
        )
        self.mcp_registry: McpClientRegistry | None = None

    @staticmethod
    def _make_vector_store(backend: str, *, dim: int) -> VectorStore:
        """选 VectorStore 实现。

        - "lancedb"：嵌入式 LanceDB，落盘到 vector_db_path()
        - "inmemory" / 其他：内存版，重启即丢
        - "lancedb" 但 import 失败：自动退回 inmemory（不强制阻塞启动）
        """
        if backend.lower() == "lancedb":
            try:
                return LanceDBVectorStore(str(vector_db_path()), dim=dim)
            except ImportError:
                return InMemoryVectorStore(dim=dim)
        return InMemoryVectorStore(dim=dim)

    def build_registry(self) -> ToolRegistry:
        """构造跟 CLI chat loop 一致的工具注册表。"""
        registry = ToolRegistry()
        registry.register_all(builtin_tools())
        registry.register_all(knowledge_tools(self.knowledge))
        registry.register_all(ingest_tools_offline(self.knowledge))
        registry.register(IngestUrlTool(self.knowledge))
        registry.register_all(memory_tools(self.memory, self.project_namespace))
        registry.register_all(skill_tools(self.memory))
        registry.register_all(skill_file_tools(skills_dir()))
        registry.register_all(tool_factory_tools(tool_drafts_dir()))
        # FiveM 三件套：detect_project / analyze_resource / propose_preset
        registry.register_all(fivem_tools(self.scaffold_engine))
        # MCP：若 attach_mcp 已跑过，把收编的远程工具一并塞进来
        if self.mcp_registry is not None:
            for adapter in self.mcp_registry.all_adapters():
                registry.register(adapter)
        registry.register_all(meta_tools(registry, self.memory))
        return registry

    async def attach_mcp(self, *, connect_timeout: float = 10.0) -> dict[str, str]:
        """从 ConfigStore 读 enabled mcp_servers 并并发连接。

        返回 {server_name: status_text} 摘要。**不抛**——失败的 server 在
        摘要里报 error，让调用方决定是 fail-fast 还是只警告。
        """
        from xuanji.mcp.registry import McpClientRegistry

        cfg = self.cfg_store.load()
        if not cfg.mcp_servers:
            return {}
        self.mcp_registry = McpClientRegistry(cfg.mcp_servers)
        await self.mcp_registry.connect_all(connect_timeout=connect_timeout)
        return self.mcp_registry.health_summary()

    async def detach_mcp(self) -> None:
        if self.mcp_registry is not None:
            await self.mcp_registry.close_all()
            self.mcp_registry = None

    def get_active_profile(self) -> Profile | None:
        return self.cfg_store.load().get_active()

    def fivem_static_extra(self) -> str | None:
        """启动期跑一次 detector，把 FiveM 项目身份卡作为 system prompt 注入。"""
        try:
            ctx = detect_fivem_context(self.project_root)
        except OSError:
            return None
        return summarize_for_prompt(ctx)

    def make_conductor(
        self,
        *,
        profile: Profile,
        hitl_bridge: HITLBridge | None = None,
        registry: ToolRegistry | None = None,
    ) -> Conductor:
        """创建一个新会话的 Conductor。"""
        cfg = self.cfg_store.load()
        return Conductor(
            profile=profile,
            mode=PersonaMode.CHAT,
            temperature=cfg.persona_temperature,
            assistant_alias=cfg.assistant_alias,
            user_alias=cfg.user_alias,
            registry=registry or self.build_registry(),
            hitl_bridge=hitl_bridge or NoOpHITLBridge(),
            memory=self.memory,
            memory_namespace=self.project_namespace,
            project_root=self.project_root,
            static_extra=self.fivem_static_extra(),
            hooks=HooksRegistry(hooks_dir()),
        )


__all__ = ["ServerRuntime"]
