"""Provider 工厂：从 profile 创建对应 LLMProvider 实例。

base_url 统一从 core.config.profiles.OFFICIAL_BASE_URLS 读取，
确保配置展示与实际调用使用同一个值。
"""

from __future__ import annotations

from xuanji.config.profiles import (
    OFFICIAL_BASE_URLS,
    AnthropicProfile,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
)
from xuanji.llm.providers.anthropic import AnthropicProvider
from xuanji.llm.providers.base import LLMProvider
from xuanji.llm.providers.openai import OpenAIProvider


def build_provider(profile: Profile) -> LLMProvider:
    """根据 profile 类型实例化对应 Provider。"""
    if isinstance(profile, AnthropicProfile):
        return AnthropicProvider(
            api_key=profile.api_key,
            base_url=OFFICIAL_BASE_URLS[ProfileKind.ANTHROPIC],
        )

    if isinstance(profile, OpenAIProfile):
        return OpenAIProvider(
            api_key=profile.api_key,
            base_url=OFFICIAL_BASE_URLS[ProfileKind.OPENAI],
            provider_name=ProfileKind.OPENAI.value,
        )

    if isinstance(profile, DeepSeekProfile):
        return OpenAIProvider(
            api_key=profile.api_key,
            base_url=OFFICIAL_BASE_URLS[ProfileKind.DEEPSEEK],
            provider_name=ProfileKind.DEEPSEEK.value,
        )

    if isinstance(profile, OpenAICompatibleProfile):
        return OpenAIProvider(
            api_key=profile.api_key,
            base_url=str(profile.base_url),
            provider_name=ProfileKind.OPENAI_COMPATIBLE.value,
        )

    raise ValueError(f"未知 profile 类型：{type(profile).__name__}")
