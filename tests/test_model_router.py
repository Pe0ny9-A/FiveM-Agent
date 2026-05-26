"""ModelRouter + 路由策略单测。

不调真 LLM——只验证路由决策矩阵：
- 单 profile 用户的退化行为
- 多 profile 时按 RoutingPolicy 偏好挑 profile kind
- prefer_model 显式指定
- fallback_chain 构造正确
"""

from __future__ import annotations

import pytest

from xuanji.config.profiles import (
    AnthropicProfile,
    DeepSeekProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
)
from xuanji.llm.router import (
    ModelRouter,
    RoutingPolicy,
    TaskSpec,
    default_policies,
)


def _anthropic(label: str = "anthr", model: str = "claude-x") -> Profile:
    return AnthropicProfile(label=label, api_key="sk-test-placeholder", default_model=model)


def _openai(label: str = "openai", model: str = "gpt-x") -> Profile:
    return OpenAIProfile(label=label, api_key="sk-test-placeholder", default_model=model)


def _deepseek(label: str = "ds", model: str = "deepseek-chat") -> Profile:
    return DeepSeekProfile(label=label, api_key="sk-test-placeholder", default_model=model)


def test_single_profile_returns_only_available() -> None:
    """只有一个 profile 时所有路由都回到它。"""
    profiles = {"only": _anthropic()}
    router = ModelRouter(profiles, active_profile_name="only")
    choice = router.route(TaskSpec(role="reviewer", complexity="high"))
    assert choice.profile_name == "only"
    assert choice.model == "claude-x"
    assert "单 profile" in choice.reason or "single" in choice.reason.lower()


def test_empty_profiles_raises() -> None:
    """空 profile 字典应抛 ValueError。"""
    router = ModelRouter({})
    with pytest.raises(ValueError, match="没有可用 profile"):
        router.route(TaskSpec())


def test_routing_picks_anthropic_for_reviewer() -> None:
    """reviewer-strict 策略：偏好 Anthropic。"""
    profiles = {
        "a": _anthropic(model="claude-opus"),
        "o": _openai(model="gpt-5"),
    }
    router = ModelRouter(profiles, active_profile_name="o")
    choice = router.route(TaskSpec(role="reviewer"))
    assert choice.profile_name == "a"
    assert choice.model == "claude-opus"
    assert "reviewer" in choice.reason


def test_cn_heavy_prefers_deepseek() -> None:
    """cn_heavy=True 应命中 cn-heavy-content 策略，偏好 DeepSeek。"""
    profiles = {
        "ds": _deepseek(model="deepseek-chat"),
        "a": _anthropic(model="claude-x"),
    }
    router = ModelRouter(profiles, active_profile_name="a")
    choice = router.route(TaskSpec(cn_heavy=True))
    assert choice.profile_name == "ds"
    assert choice.model == "deepseek-chat"


def test_long_context_prefers_anthropic() -> None:
    """ctx > 200k + complexity high → Anthropic。"""
    profiles = {
        "a": _anthropic(model="claude-opus-1m"),
        "o": _openai(model="gpt-5"),
    }
    router = ModelRouter(profiles, active_profile_name="o")
    choice = router.route(
        TaskSpec(complexity="high", ctx_size_tokens=300_000),
    )
    assert choice.profile_name == "a"
    assert choice.model == "claude-opus-1m"


def test_no_matching_kind_falls_back_to_active() -> None:
    """没有 anthropic/openai 时，reviewer-strict 降级到下一个策略或 active。"""
    profiles = {
        "ds": _deepseek(model="deepseek-chat"),
    }
    # 只有一个 profile 走的是 single_profile_route
    router = ModelRouter(profiles, active_profile_name="ds")
    choice = router.route(TaskSpec(role="reviewer"))
    assert choice.profile_name == "ds"
    assert choice.model == "deepseek-chat"


def test_no_matching_policy_uses_active_default() -> None:
    """无规则匹配的 spec → 用 active profile 的 default_model。"""
    profiles = {
        "a": _anthropic(model="m1"),
        "o": _openai(model="m2"),
    }
    router = ModelRouter(profiles, active_profile_name="o", policies=[])
    choice = router.route(TaskSpec())
    assert choice.profile_name == "o"
    assert choice.model == "m2"
    assert "无规则匹配" in choice.reason or "回退" in choice.reason


def test_fallback_chain_excludes_primary() -> None:
    profiles = {
        "a": _anthropic(model="m1"),
        "o": _openai(model="m2"),
        "ds": _deepseek(model="m3"),
    }
    router = ModelRouter(profiles, active_profile_name="a")
    choice = router.route(TaskSpec(role="reviewer"))  # → a
    chain_names = [name for (name, _) in choice.fallback_chain]
    assert "a" not in chain_names
    assert set(chain_names) == {"o", "ds"}


def test_custom_policy_with_prefer_model() -> None:
    """用户自定义策略可以指定具体 model id。"""
    profiles = {
        "a": _anthropic(model="claude-default"),
    }
    custom = [
        RoutingPolicy(
            name="my-rule",
            when_role=["coder"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC],
            prefer_model="claude-special",
            reason="测试用",
        ),
    ]
    router = ModelRouter(profiles, active_profile_name="a", policies=custom)
    choice = router.route(TaskSpec(role="coder"))
    assert choice.model == "claude-special"
    assert "my-rule" in choice.reason


def test_default_policies_no_hardcoded_models() -> None:
    """0.6 关键约束：默认策略不能硬编码 model id——model 由 profile.default_model 决定。"""
    for policy in default_policies():
        assert policy.prefer_model is None, (
            f"策略 {policy.name} 不应硬编码 model id={policy.prefer_model!r}"
        )


def test_routing_policy_matches_predicates() -> None:
    """RoutingPolicy.matches 各维度联合判定。"""
    p = RoutingPolicy(
        name="t",
        when_role=["reviewer"],
        when_complexity=["high"],
        when_min_ctx_tokens=10_000,
        when_cn_heavy=False,
    )
    assert p.matches(
        TaskSpec(role="reviewer", complexity="high", ctx_size_tokens=20_000, cn_heavy=False),
    )
    # role 不匹配
    assert not p.matches(TaskSpec(role="coder", complexity="high", ctx_size_tokens=20_000))
    # ctx 不够
    assert not p.matches(
        TaskSpec(role="reviewer", complexity="high", ctx_size_tokens=5_000),
    )
    # cn_heavy 不一致
    assert not p.matches(
        TaskSpec(role="reviewer", complexity="high", ctx_size_tokens=20_000, cn_heavy=True),
    )
