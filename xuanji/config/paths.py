"""跨平台配置路径。

借 platformdirs 决定用户目录：
- Windows: %APPDATA%\\xuanji\\
- macOS:  ~/Library/Application Support/xuanji/
- Linux:  ~/.config/xuanji/

允许通过 XUANJI_CONFIG_HOME 环境变量覆盖（便于开发与测试）。
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

_APP_NAME = "xuanji"
_CONFIG_FILE = "config.json"
_KNOWLEDGE_DB = "knowledge.db"
_MEMORY_DB = "memory.db"


def config_dir() -> Path:
    """返回配置目录，必要时创建。"""
    override = os.environ.get("XUANJI_CONFIG_HOME")
    base = Path(override) if override else Path(user_config_dir(_APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file_path() -> Path:
    """返回配置 JSON 文件的完整路径。"""
    return config_dir() / _CONFIG_FILE


def data_dir() -> Path:
    """返回数据目录（数据库、向量索引等）。"""
    override = os.environ.get("XUANJI_DATA_HOME")
    base = Path(override) if override else Path(user_data_dir(_APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base


def knowledge_db_path() -> Path:
    """返回知识库 SQLite 文件路径。"""
    return data_dir() / _KNOWLEDGE_DB


def memory_db_path() -> Path:
    """返回记忆库 SQLite 文件路径。"""
    return data_dir() / _MEMORY_DB


def tool_drafts_dir() -> Path:
    """返回 propose_tool 草案的存放目录。"""
    p = data_dir() / "tool_drafts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def crawl_cache_path() -> Path:
    """爬虫的 URL→content_hash 缓存（增量去重用）。"""
    return data_dir() / "crawl_cache.json"


def tool_staged_dir() -> Path:
    """工具工厂 staged 目录：codegen 完成、待 test/publish 的代码。"""
    p = data_dir() / "tool_staged"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tool_published_dir() -> Path:
    """工具工厂 published 目录：通过 review 的可加载工具。"""
    p = data_dir() / "tool_published"
    p.mkdir(parents=True, exist_ok=True)
    return p


def factory_db_path() -> Path:
    """ToolFactory 状态数据库。"""
    return data_dir() / "tool_factory.db"


def scaffold_presets_dir() -> Path:
    """用户已激活的 scaffold 预设目录。"""
    p = data_dir() / "scaffold_presets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def scaffold_drafts_dir() -> Path:
    """propose_preset 提交的预设草案目录（待 review）。"""
    p = data_dir() / "scaffold_drafts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def skills_dir() -> Path:
    """Skills 目录：markdown + YAML frontmatter。

    与 Claude Code / Codex 的 skills 目录格式互通——文件可双向迁移。
    玄玑特定字段放在 frontmatter 的 `metadata.xuanji.*` 子树。
    """
    p = data_dir() / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def hooks_dir() -> Path:
    """Hooks 目录：YAML 配置。

    事件名复用 Claude Code 体系：PreToolUse / PostToolUse /
    UserPromptSubmit / Notification。文件名约定 `<event>.yaml`。
    """
    p = data_dir() / "hooks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def vector_db_path() -> Path:
    """LanceDB 嵌入式数据目录。

    LanceDBVectorStore 落盘到这里。InMemoryVectorStore 不会创建。
    """
    p = data_dir() / "vectors"
    p.mkdir(parents=True, exist_ok=True)
    return p


def chat_session_dir() -> Path:
    """CLI chat 会话快照目录。

    `last.json` 存放最近一次对话的 history，重启 CLI 时可询问是否恢复。
    """
    p = data_dir() / "chat_sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def chat_session_last_path() -> Path:
    """最近一次 CLI chat 会话快照路径。"""
    return chat_session_dir() / "last.json"
