"""配置仓库。

ConfigStore 是 JSON 配置文件的唯一持久化入口。
- load() 从磁盘读取，文件不存在时返回空配置
- save() 原子写回（先写 tmp，再 replace）
- 增删改 profile 与 active_profile 切换都通过本类
- 同一份 schema 未来直接给 Web/Tauri 用，前端零改造
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from xuanji.config.paths import config_file_path
from xuanji.config.profiles import Profile
from xuanji.mcp.registry import McpServerConfig
from xuanji.neural.compaction import CompactionConfig
from xuanji.persona.modes import PersonaTemperature


class ChatUIConfig(BaseModel):
    """CLI 聊天框 UI 偏好。

    show_thinking: 是否在终端打印 thinking_delta 思维链文本。
    思维链对调试模型推理过程有用，但对日常对话是噪音；
    默认关闭，用户可在 CLI 里 `/think on|off` 实时切换。
    """

    show_thinking: bool = False


class XuanjiConfig(BaseModel):
    """配置文件的根 schema。"""

    version: int = 1
    active_profile: str | None = None
    persona_temperature: PersonaTemperature = PersonaTemperature.BALANCED
    # 玄玑的"真名"是固定的玄玑（Xuanji），但对话中的称呼小宝可调：
    #   user_alias 是玄玑对用户的称呼（默认"小宝"）
    #   assistant_alias 是玄玑自称（默认"姐姐"）
    # CLI 框架文字（panel 标题 / 输入提示）不受影响，永远显示"玄玑/用户"。
    user_alias: str = Field(default="小宝", min_length=1, max_length=16)
    assistant_alias: str = Field(default="姐姐", min_length=1, max_length=16)
    profiles: dict[str, Profile] = Field(default_factory=dict)
    mcp_servers: list[McpServerConfig] = Field(
        default_factory=list,
        description="收编的 MCP server 列表。启动时 ServerRuntime 会拉起 enabled 的",
    )
    compaction: CompactionConfig = Field(
        default_factory=CompactionConfig,
        description="上下文自动压缩。超 max_context_tokens 时折叠 history 头部",
    )
    chat_ui: ChatUIConfig = Field(
        default_factory=ChatUIConfig,
        description="CLI 聊天框 UI 偏好（如是否显示 thinking 思维链）",
    )

    def get_active(self) -> Profile | None:
        """返回当前激活的 profile，未设置或不存在时返回 None。"""
        if not self.active_profile:
            return None
        return self.profiles.get(self.active_profile)


class ConfigStore:
    """JSON 配置文件读写器。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_file_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> XuanjiConfig:
        """读取配置。文件不存在返回空配置，损坏时抛 ValueError。"""
        if not self._path.exists():
            return XuanjiConfig()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件 {self._path} 损坏：{e}") from e
        return XuanjiConfig.model_validate(raw)

    def save(self, config: XuanjiConfig) -> None:
        """原子写回。先写 .tmp 文件再 os.replace，避免半截写坏。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        payload = config.model_dump(mode="json", exclude_none=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def upsert_profile(self, name: str, profile: Profile, *, activate: bool = False) -> None:
        """新增或覆盖 profile。activate=True 时同时设为当前 active。"""
        cfg = self.load()
        cfg.profiles[name] = profile
        if activate or cfg.active_profile is None:
            cfg.active_profile = name
        self.save(cfg)

    def remove_profile(self, name: str) -> bool:
        """删除 profile。返回是否成功删除。"""
        cfg = self.load()
        if name not in cfg.profiles:
            return False
        del cfg.profiles[name]
        if cfg.active_profile == name:
            cfg.active_profile = next(iter(cfg.profiles), None)
        self.save(cfg)
        return True

    def use_profile(self, name: str) -> None:
        """切换激活 profile。不存在时抛 KeyError。"""
        cfg = self.load()
        if name not in cfg.profiles:
            raise KeyError(name)
        cfg.active_profile = name
        self.save(cfg)

    def set_persona_temperature(self, temperature: PersonaTemperature) -> None:
        cfg = self.load()
        cfg.persona_temperature = temperature
        self.save(cfg)

    def set_aliases(
        self,
        *,
        user_alias: str | None = None,
        assistant_alias: str | None = None,
    ) -> None:
        """更新对话称呼。任一参数为 None 表示不改该项。"""
        cfg = self.load()
        if user_alias is not None:
            cfg.user_alias = user_alias
        if assistant_alias is not None:
            cfg.assistant_alias = assistant_alias
        self.save(cfg)

    # ------------------------------ MCP server ------------------------------

    def upsert_mcp_server(self, server: McpServerConfig) -> None:
        """新增或按 name 覆盖 MCP server 配置。"""
        cfg = self.load()
        cfg.mcp_servers = [s for s in cfg.mcp_servers if s.name != server.name]
        cfg.mcp_servers.append(server)
        self.save(cfg)

    def remove_mcp_server(self, name: str) -> bool:
        cfg = self.load()
        before = len(cfg.mcp_servers)
        cfg.mcp_servers = [s for s in cfg.mcp_servers if s.name != name]
        if len(cfg.mcp_servers) == before:
            return False
        self.save(cfg)
        return True

    def set_mcp_enabled(self, name: str, enabled: bool) -> bool:
        cfg = self.load()
        for s in cfg.mcp_servers:
            if s.name == name:
                s.enabled = enabled
                self.save(cfg)
                return True
        return False
