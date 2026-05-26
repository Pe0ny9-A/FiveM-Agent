"""三家 Provider 拆分后的形状单测。

不依赖真实 API key——只测纯结构与转换逻辑：
- DeepSeek `reasoning_content` 往返
- Anthropic thinking_budget 自动展开 + cache_system 包系统提示
- OpenAI reasoning 模型 max_tokens → max_completion_tokens 迁移
"""

from __future__ import annotations

import pytest

from xuanji.llm.providers.anthropic import AnthropicProvider, _build_kwargs
from xuanji.llm.providers.base import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
)
from xuanji.llm.providers.deepseek import DeepSeekProvider, _to_deepseek_messages
from xuanji.llm.providers.openai import (
    OpenAIProvider,
    _adapt_kwargs,
    _is_reasoning_model,
)

# ----------------------------- DeepSeek -----------------------------

def test_deepseek_provider_name_fixed() -> None:
    p = DeepSeekProvider(api_key="sk-test-placeholder")
    assert p.name == "deepseek"


def test_deepseek_caps_v4_pro_thinking() -> None:
    p = DeepSeekProvider(api_key="sk-test-placeholder")
    caps = p.capabilities("deepseek-v4-pro")
    assert caps.supports_thinking is True
    assert caps.supports_prompt_cache is True
    assert caps.provider == "deepseek"


def test_deepseek_to_messages_carries_reasoning_content() -> None:
    """ThinkingBlock 必须翻成 assistant 消息的 reasoning_content 字段，
    否则 DeepSeek 在第二轮会回 400。"""
    msgs = [
        Message(role="user", content="QBCore 怎么加物品"),
        Message(
            role="assistant",
            content=[
                ThinkingBlock(text="先查一下 QBCore.Functions"),
                TextBlock(text="QBCore.Functions.CreateUseableItem"),
            ],
        ),
        Message(role="user", content="详细点"),
    ]
    out = _to_deepseek_messages(msgs, system="你是玄玑")
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"
    asst = out[2]
    assert asst["role"] == "assistant"
    assert asst["content"] == "QBCore.Functions.CreateUseableItem"
    assert asst["reasoning_content"] == "先查一下 QBCore.Functions"


def test_deepseek_to_messages_user_thinking_dropped() -> None:
    """user 消息不应携带 reasoning_content（DeepSeek 不接受）。"""
    msgs = [
        Message(
            role="user",
            content=[
                ThinkingBlock(text="不该出现"),
                TextBlock(text="hello"),
            ],
        ),
    ]
    out = _to_deepseek_messages(msgs, system=None)
    assert "reasoning_content" not in out[0]


def test_deepseek_to_messages_tool_calls_kept() -> None:
    msgs = [
        Message(
            role="assistant",
            content=[
                TextBlock(text="读个文件"),
                ToolCallBlock(id="t1", name="read_file", args={"path": "a.lua"}),
            ],
        ),
    ]
    out = _to_deepseek_messages(msgs, system=None)
    assert "tool_calls" in out[0]
    assert out[0]["tool_calls"][0]["function"]["name"] == "read_file"


# ----------------------------- OpenAI -----------------------------

def test_openai_provider_name() -> None:
    p = OpenAIProvider(api_key="sk-test-placeholder")
    assert p.name == "openai"


def test_openai_reasoning_model_detection() -> None:
    assert _is_reasoning_model("o1") is True
    assert _is_reasoning_model("o3-mini") is True
    assert _is_reasoning_model("gpt-5.5") is True
    assert _is_reasoning_model("gpt-4o") is False
    assert _is_reasoning_model("gpt-4o-mini") is False


def test_openai_adapt_kwargs_migrates_max_tokens() -> None:
    """reasoning 模型的 max_tokens 必须迁到 max_completion_tokens。"""
    out = _adapt_kwargs("o3-mini", {"max_tokens": 1024, "model": "o3-mini"})
    assert "max_tokens" not in out
    assert out["max_completion_tokens"] == 1024


def test_openai_adapt_kwargs_passthrough_for_4o() -> None:
    out = _adapt_kwargs("gpt-4o", {"max_tokens": 1024, "model": "gpt-4o"})
    assert out["max_tokens"] == 1024
    assert "max_completion_tokens" not in out


def test_openai_caps_gpt5_supports_thinking() -> None:
    p = OpenAIProvider(api_key="sk-test-placeholder")
    caps = p.capabilities("gpt-5.5")
    assert caps.supports_thinking is True
    assert caps.supports_prompt_cache is True


# ----------------------------- Anthropic -----------------------------

def test_anthropic_thinking_budget_expands() -> None:
    """thinking_budget=N 应被翻译成完整的 thinking dict + 强制 temperature=1。"""
    kwargs = _build_kwargs(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hi")],
        system="你是玄玑",
        max_tokens=1024,
        temperature=0.7,
        tools=None,
        extra={"thinking_budget": 2048},
    )
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert kwargs["temperature"] == 1.0


def test_anthropic_cache_system_wraps_system() -> None:
    """cache_system=True 时 system 应被包成 cache_control 块。"""
    kwargs = _build_kwargs(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hi")],
        system="你是玄玑",
        max_tokens=1024,
        temperature=1.0,
        tools=None,
        extra={"cache_system": True},
    )
    assert kwargs["system"] == [
        {
            "type": "text",
            "text": "你是玄玑",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def test_anthropic_no_cache_when_off() -> None:
    """默认 cache_system=False 时 system 是裸字符串。"""
    kwargs = _build_kwargs(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hi")],
        system="你是玄玑",
        max_tokens=1024,
        temperature=1.0,
        tools=None,
        extra={},
    )
    assert kwargs["system"] == "你是玄玑"


def test_anthropic_provider_unknown_model_falls_back_to_sonnet() -> None:
    p = AnthropicProvider(api_key="sk-test-placeholder")
    caps = p.capabilities("claude-some-future-model")
    assert caps.supports_thinking is True
    assert caps.supports_prompt_cache is True


# ----------------------------- factory routing -----------------------------

def test_factory_routes_deepseek_to_deepseek_provider() -> None:
    from xuanji.config.profiles import DeepSeekProfile
    from xuanji.llm.providers.factory import build_provider

    profile = DeepSeekProfile(
        label="ds",
        api_key="sk-test-placeholder",
        default_model="deepseek-v4-pro",
    )
    p = build_provider(profile)
    assert isinstance(p, DeepSeekProvider)


def test_factory_routes_openai_to_openai_provider() -> None:
    from xuanji.config.profiles import OpenAIProfile
    from xuanji.llm.providers.factory import build_provider

    profile = OpenAIProfile(
        label="oai",
        api_key="sk-test-placeholder",
        default_model="gpt-5.5",
    )
    p = build_provider(profile)
    assert isinstance(p, OpenAIProvider)


def test_factory_rejects_unknown_profile_type() -> None:
    from xuanji.llm.providers.factory import build_provider

    class FakeProfile:
        pass

    with pytest.raises(ValueError, match="未知 profile 类型"):
        build_provider(FakeProfile())  # type: ignore[arg-type]
