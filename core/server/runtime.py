"""服务层运行时容器。

把 chat loop 里那一堆"开 store、注册工具、建 conductor"提取出来，
让 CLI 的 chat 命令、FastAPI 的 WebSocket 都从同一处拿到一致的注入。
"""

from __future__ import annotations

from pathlib import Path

from core.capability.registry import ToolRegistry
from core.config import (
    ConfigStore,
    knowledge_db_path,
    memory_db_path,
    scaffold_drafts_dir,
    scaffold_presets_dir,
    tool_drafts_dir,
)
from core.config.profiles import Profile
from core.fivem import detect_fivem_context, summarize_for_prompt
from core.fivem.scaffold import ScaffoldEngine
from core.gate.bridge import HITLBridge, NoOpHITLBridge
from core.knowledge import HashingEmbedder, InMemoryVectorStore, SqliteKnowledgeStore
from core.memory import SqliteMemoryStore
from core.neural import Conductor
from core.persona import PersonaMode
from core.tools import (
    builtin_tools,
    ingest_tools_offline,
    knowledge_tools,
    memory_tools,
    meta_tools,
    skill_tools,
    tool_factory_tools,
)
from core.tools.fivem import fivem_tools
from core.tools.ingest_url import IngestUrlTool


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
    ) -> None:
        self.cfg_store = cfg_store or ConfigStore()
        self.knowledge = SqliteKnowledgeStore(knowledge_db_path())
        self.memory = SqliteMemoryStore(memory_db_path())
        if attach_vector_index:
            embedder = HashingEmbedder()
            vstore = InMemoryVectorStore(dim=embedder.dim)
            self.knowledge.attach_vector_index(embedder, vstore)
        self.project_root = (project_root or Path.cwd()).resolve()
        self.project_namespace = project_namespace or self.project_root.name or "default"
        # FiveM 专精层：scaffold engine 用项目级用户预设目录
        self.scaffold_engine = ScaffoldEngine(
            user_presets_dir=scaffold_presets_dir(),
            drafts_dir=scaffold_drafts_dir(),
        )

    def build_registry(self) -> ToolRegistry:
        """构造跟 CLI chat loop 一致的工具注册表。"""
        registry = ToolRegistry()
        registry.register_all(builtin_tools())
        registry.register_all(knowledge_tools(self.knowledge))
        registry.register_all(ingest_tools_offline(self.knowledge))
        registry.register(IngestUrlTool(self.knowledge))
        registry.register_all(memory_tools(self.memory, self.project_namespace))
        registry.register_all(skill_tools(self.memory))
        registry.register_all(tool_factory_tools(tool_drafts_dir()))
        # FiveM 三件套：detect_project / analyze_resource / propose_preset
        registry.register_all(fivem_tools(self.scaffold_engine))
        registry.register_all(meta_tools(registry, self.memory))
        return registry

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
        )


__all__ = ["ServerRuntime"]
