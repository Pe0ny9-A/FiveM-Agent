"""Provider profile schema。

每个 profile 描述"如何连一家模型供应商"。kind 是 discriminator：
- anthropic / openai / deepseek：官方端点，base_url 内置，用户只填 api_key
- openai-compatible：任意 OpenAI 兼容端点，用户填 base_url + api_key

所有 profile 共享 default_model，便于 chat 时直接拿到该 profile 的默认模型。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl


class ProfileKind(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    OPENAI_COMPATIBLE = "openai-compatible"


class _ProfileBase(BaseModel):
    """所有 profile 共享字段。"""

    label: str = Field(description="人类可读的档案名，前端展示用")
    api_key: str = Field(min_length=1, description="供应商 API Key")
    default_model: str = Field(description="该档案默认调用的模型 id")


class AnthropicProfile(_ProfileBase):
    kind: Literal[ProfileKind.ANTHROPIC] = ProfileKind.ANTHROPIC


class OpenAIProfile(_ProfileBase):
    kind: Literal[ProfileKind.OPENAI] = ProfileKind.OPENAI


class DeepSeekProfile(_ProfileBase):
    kind: Literal[ProfileKind.DEEPSEEK] = ProfileKind.DEEPSEEK


class OpenAICompatibleProfile(_ProfileBase):
    kind: Literal[ProfileKind.OPENAI_COMPATIBLE] = ProfileKind.OPENAI_COMPATIBLE
    base_url: HttpUrl = Field(description="兼容 OpenAI Chat Completions 的端点 URL")


Profile = Annotated[
    AnthropicProfile | OpenAIProfile | DeepSeekProfile | OpenAICompatibleProfile,
    Field(discriminator="kind"),
]
"""判别联合：根据 kind 字段反序列化到正确的子类型。"""

# 三家官方 API 端点（OpenAI 兼容地址）。openai-compatible 由用户填写。
# DeepSeek 同时提供 Anthropic 兼容端点 https://api.deepseek.com/anthropic，
# M1+ 可让 DeepSeek profile 选 SDK 方言。
OFFICIAL_BASE_URLS: dict[ProfileKind, str] = {
    ProfileKind.ANTHROPIC: "https://api.anthropic.com",
    ProfileKind.OPENAI: "https://api.openai.com/v1",
    ProfileKind.DEEPSEEK: "https://api.deepseek.com",
}

# 各 profile 的推荐默认模型（给 add 命令省事用）
DEFAULT_MODELS: dict[ProfileKind, str] = {
    ProfileKind.ANTHROPIC: "claude-opus-4-7",
    ProfileKind.OPENAI: "gpt-5.5",
    ProfileKind.DEEPSEEK: "deepseek-v4-pro",
    ProfileKind.OPENAI_COMPATIBLE: "gpt-4o-mini",
}
