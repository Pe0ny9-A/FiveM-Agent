"""配置存储。

设计要点：
- API Key 不写 .env，存到平台用户目录的 JSON 文件里。
- profile 用 discriminated union 区分 anthropic / openai / deepseek / openai-compatible
  四种来源。三家官方只填 api_key，openai-compatible 额外填 base_url。
- ConfigStore 是同一套 schema 的唯一持久化入口，未来 Web/Tauri 直接复用。
"""

from xuanji.config.paths import (
    config_dir,
    config_file_path,
    crawl_cache_path,
    data_dir,
    factory_db_path,
    hooks_dir,
    knowledge_db_path,
    memory_db_path,
    scaffold_drafts_dir,
    scaffold_presets_dir,
    skills_dir,
    tool_drafts_dir,
    tool_published_dir,
    tool_staged_dir,
    vector_db_path,
)
from xuanji.config.profiles import (
    AnthropicProfile,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
)
from xuanji.config.store import ConfigStore, XuanjiConfig

__all__ = [
    "AnthropicProfile",
    "ConfigStore",
    "DeepSeekProfile",
    "OpenAICompatibleProfile",
    "OpenAIProfile",
    "Profile",
    "ProfileKind",
    "XuanjiConfig",
    "config_dir",
    "config_file_path",
    "crawl_cache_path",
    "data_dir",
    "factory_db_path",
    "hooks_dir",
    "knowledge_db_path",
    "memory_db_path",
    "scaffold_drafts_dir",
    "scaffold_presets_dir",
    "skills_dir",
    "tool_drafts_dir",
    "tool_published_dir",
    "tool_staged_dir",
    "vector_db_path",
]
