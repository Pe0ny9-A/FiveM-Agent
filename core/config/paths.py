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
