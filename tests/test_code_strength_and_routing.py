"""代码强化段 + 0.9.3 默认 DeepSeek 优先路由的单测。"""

from __future__ import annotations

from xuanji.config.profiles import (
    AnthropicProfile,
    DeepSeekProfile,
    OpenAIProfile,
    Profile,
)
from xuanji.llm.router import ModelRouter, TaskSpec
from xuanji.persona.code_strength import code_strength_fragment


def _anthropic(label: str = "anthr", model: str = "claude-x") -> Profile:
    return AnthropicProfile(
        label=label, api_key="sk-test-placeholder", default_model=model,
    )


def _openai(label: str = "openai", model: str = "gpt-x") -> Profile:
    return OpenAIProfile(
        label=label, api_key="sk-test-placeholder", default_model=model,
    )


def _deepseek(label: str = "ds", model: str = "deepseek-v4-pro") -> Profile:
    return DeepSeekProfile(
        label=label, api_key="sk-test-placeholder", default_model=model,
    )


# ============== code_strength_fragment ==============


def test_code_strength_for_deepseek_v4_pro() -> None:
    frag = code_strength_fragment("deepseek", "deepseek-v4-pro")
    assert frag is not None
    assert "代码工程素养" in frag
    assert "最小改动" in frag


def test_code_strength_for_deepseek_reasoner() -> None:
    frag = code_strength_fragment("deepseek", "deepseek-reasoner")
    assert frag is not None


def test_code_strength_for_deepseek_v4_flash() -> None:
    frag = code_strength_fragment("deepseek", "deepseek-v4-flash")
    assert frag is not None


def test_code_strength_none_for_anthropic() -> None:
    """Opus / Sonnet 自带这层素养，不重复加。"""
    assert code_strength_fragment("anthropic", "claude-opus-4-7") is None
    assert code_strength_fragment("anthropic", "claude-sonnet-4-6") is None


def test_code_strength_none_for_openai() -> None:
    assert code_strength_fragment("openai", "gpt-5.5") is None
    assert code_strength_fragment("openai", "gpt-5.4") is None


def test_code_strength_none_for_legacy_deepseek_chat() -> None:
    """legacy deepseek-chat 不在白名单内——它没 thinking，不强加。"""
    assert code_strength_fragment("deepseek", "deepseek-chat") is None


def test_code_strength_handles_blank() -> None:
    assert code_strength_fragment("", "") is None
    assert code_strength_fragment("deepseek", "") is None


# ============== 默认路由：DeepSeek-first for dev/tool-loop ==============


def test_dev_tool_loop_prefers_deepseek_when_all_three_present() -> None:
    """0.9.3 默认：dev/tool-loop 现在 DeepSeek 优先。"""
    profiles = {
        "a": _anthropic(),
        "o": _openai(),
        "ds": _deepseek(),
    }
    router = ModelRouter(profiles, active_profile_name="a")
    choice = router.route(TaskSpec(task_kind="dev"))
    assert choice.profile_name == "ds"
    assert choice.model == "deepseek-v4-pro"


def test_tool_loop_prefers_deepseek_over_anthropic() -> None:
    profiles = {
        "a": _anthropic(),
        "ds": _deepseek(),
    }
    router = ModelRouter(profiles, active_profile_name="a")
    choice = router.route(TaskSpec(task_kind="tool-loop"))
    assert choice.profile_name == "ds"


def test_dev_falls_back_to_anthropic_when_no_deepseek() -> None:
    profiles = {
        "a": _anthropic(),
        "o": _openai(),
    }
    router = ModelRouter(profiles, active_profile_name="o")
    choice = router.route(TaskSpec(task_kind="dev"))
    assert choice.profile_name == "a"


def test_long_ctx_still_prefers_anthropic() -> None:
    """长上下文 + 高复杂度仍走 Anthropic。"""
    profiles = {
        "a": _anthropic(),
        "ds": _deepseek(),
    }
    router = ModelRouter(profiles, active_profile_name="ds")
    choice = router.route(
        TaskSpec(complexity="high", ctx_size_tokens=300_000),
    )
    assert choice.profile_name == "a"


def test_planning_still_prefers_anthropic() -> None:
    profiles = {
        "a": _anthropic(),
        "ds": _deepseek(),
    }
    router = ModelRouter(profiles, active_profile_name="ds")
    choice = router.route(
        TaskSpec(task_kind="planning", complexity="high"),
    )
    assert choice.profile_name == "a"


def test_researcher_tool_loop_prefers_deepseek() -> None:
    profiles = {
        "a": _anthropic(),
        "ds": _deepseek(),
    }
    router = ModelRouter(profiles, active_profile_name="a")
    choice = router.route(TaskSpec(role="researcher", task_kind="tool-loop"))
    assert choice.profile_name == "ds"
