"""配置存储。

设计要点：
- API Key 不写 .env，存到平台用户目录的 JSON 文件里。
- profile 用 discriminated union 区分 anthropic / openai / deepseek / openai-compatible
  四种来源。三家官方只填 api_key，openai-compatible 额外填 base_url。
- ConfigStore 是同一套 schema 的唯一持久化入口，未来 Web/Tauri 直接复用。
"""

from core.config.paths import (
    config_dir,
    config_file_path,
    data_dir,
    knowledge_db_path,
    memory_db_path,
)
from core.config.profiles import (
    AnthropicProfile,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
)
from core.config.store import ConfigStore, XuanjiConfig

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
    "data_dir",
    "knowledge_db_path",
    "memory_db_path",
]
