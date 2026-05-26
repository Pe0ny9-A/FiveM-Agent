"""异构路由 + 0.6 dispatch_subagent 增量测试。

验证：
- 4 角色（含天枢令）都能调
- profile_override 命中 / 找不到时降级
- 无 override 时按 role.preferred_profile_kinds 挑 profile
- model_override 单次覆盖
- 单 profile 退化兼容
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import ToolCtx
from xuanji.config.profiles import (
    AnthropicProfile,
    DeepSeekProfile,
    OpenAIProfile,
    Profile,
)
from xuanji.ensemble import DispatchSubagentTool, builtin_roles
from xuanji.ensemble.supervisor import ListProfilesTool, supervisor_tools
from xuanji.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
)
from xuanji.tools import builtin_tools


class _DoneProvider(LLMProvider):
    """只回一段 text 然后 end_turn——记录被调用时用的 model。"""

    name = "fake"
    last_model: str = ""

    def __init__(self) -> None:
        type(self).last_model = ""

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model, provider="fake", context_window=128_000, max_output_tokens=4096,
        )

    async def chat(self, **kw: Any) -> AssistantMessage:
        raise NotImplementedError

    async def stream(
        self, *, model: str, messages: Sequence[Message],
        system: str | None = None, **kw: Any,
    ) -> AsyncIterator[Delta]:
        type(self).last_model = model
        yield Delta(type="text_delta", index=0, text="ok")
        yield Delta(type="message_done", stop_reason="end_turn")


def _anthropic(label: str = "a", model: str = "claude-x") -> Profile:
    return AnthropicProfile(label=label, api_key="sk-test-placeholder", default_model=model)


def _openai(label: str = "o", model: str = "gpt-x") -> Profile:
    return OpenAIProfile(label=label, api_key="sk-test-placeholder", default_model=model)


def _deepseek(label: str = "ds", model: str = "ds-chat") -> Profile:
    return DeepSeekProfile(label=label, api_key="sk-test-placeholder", default_model=model)


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        lambda _p: _DoneProvider(),
    )


@pytest.mark.asyncio
async def test_dispatch_resolves_chinese_role(tmp_path: Path) -> None:
    """中文正名 '稷下生' 应能直接用。"""
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "稷下生", "brief": "查一下"}, ctx,
    )
    assert res.ok
    assert res.output["role"] == "稷下生"


@pytest.mark.asyncio
async def test_dispatch_tianshu_planner(tmp_path: Path) -> None:
    """天枢令角色应可调，alias 'planner' 也可。"""
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "planner", "brief": "拆任务"}, ctx,
    )
    assert res.ok
    assert res.output["role"] == "天枢令"


@pytest.mark.asyncio
async def test_dispatch_uses_profile_override(tmp_path: Path) -> None:
    """profile_override 命中时，应路由到指定 profile。"""
    profiles = {
        "anth": _anthropic(model="claude-z"),
        "ds": _deepseek(model="deepseek-z"),
    }
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=profiles["anth"],
        master_registry=master,
        project_root=tmp_path,
        profiles=profiles,
        active_profile_name="anth",
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "researcher", "brief": "x", "profile_override": "ds"}, ctx,
    )
    assert res.ok
    assert res.output["routing"]["profile_kind"] == "deepseek"
    assert res.output["routing"]["model"] == "deepseek-z"
    assert "profile_override=ds" in res.output["routing"]["reason"]


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_override_unknown(tmp_path: Path) -> None:
    """profile_override 给的名找不到时降级到 router 决策。"""
    profiles = {
        "anth": _anthropic(model="claude-z"),
        "ds": _deepseek(model="deepseek-z"),
    }
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=profiles["anth"],
        master_registry=master,
        project_root=tmp_path,
        profiles=profiles,
        active_profile_name="anth",
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "researcher", "brief": "x", "profile_override": "ghost"}, ctx,
    )
    assert res.ok
    # 稷下生 preferred_profile_kinds = [ANTHROPIC, OPENAI]
    assert res.output["routing"]["profile_kind"] == "anthropic"
    assert "找不到" in res.output["routing"]["reason"]


@pytest.mark.asyncio
async def test_dispatch_uses_role_preferred_kind(tmp_path: Path) -> None:
    """无 override 时应按 role.preferred_profile_kinds 选 profile。

    司鉴 preferred = [ANTHROPIC]，即便 active 是 deepseek 也应选 anthropic。
    """
    profiles = {
        "ds": _deepseek(model="deepseek-z"),
        "anth": _anthropic(model="claude-z"),
    }
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=profiles["ds"],
        master_registry=master,
        project_root=tmp_path,
        profiles=profiles,
        active_profile_name="ds",
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "reviewer", "brief": "审一下"}, ctx,
    )
    assert res.ok
    assert res.output["routing"]["profile_kind"] == "anthropic"
    assert res.output["routing"]["model"] == "claude-z"
    assert "role.preferred" in res.output["routing"]["reason"]


@pytest.mark.asyncio
async def test_dispatch_model_override_takes_priority(tmp_path: Path) -> None:
    """model_override 可单次覆盖 profile.default_model。"""
    profiles = {
        "anth": _anthropic(model="claude-default"),
        "ds": _deepseek(model="deepseek-default"),
    }
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=profiles["anth"],
        master_registry=master,
        project_root=tmp_path,
        profiles=profiles,
        active_profile_name="anth",
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {
            "role": "coder",
            "brief": "写点东西",
            "profile_override": "anth",
            "model_override": "claude-haiku-special",
        },
        ctx,
    )
    assert res.ok
    assert res.output["routing"]["model"] == "claude-haiku-special"


@pytest.mark.asyncio
async def test_dispatch_single_profile_falls_back_gracefully(tmp_path: Path) -> None:
    """无 profiles 字典时退化为 0.5 行为：用 default_profile。"""
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=_anthropic(model="solo"),
        master_registry=master,
        project_root=tmp_path,
        # 不传 profiles
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "researcher", "brief": "x"}, ctx,
    )
    assert res.ok
    assert res.output["routing"]["profile_kind"] == "anthropic"
    assert res.output["routing"]["model"] == "solo"
    assert "single-profile-fallback" in res.output["routing"]["reason"]


@pytest.mark.asyncio
async def test_list_profiles_tool(tmp_path: Path) -> None:
    """ListProfilesTool 应列出全部 profile，不漏 api_key。"""
    profiles = {
        "anth": _anthropic(model="m1"),
        "ds": _deepseek(model="m2"),
    }
    tool = ListProfilesTool(profiles, active_name="anth")
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute({}, ctx)
    assert res.ok
    names = {p["name"] for p in res.output}
    assert names == {"anth", "ds"}
    # 不含 api_key
    for p in res.output:
        assert "api_key" not in p
        assert "default_model" in p
        assert "kind" in p
        assert "active" in p
    # active 标记正确
    active = [p for p in res.output if p["active"]]
    assert len(active) == 1
    assert active[0]["name"] == "anth"


def test_supervisor_tools_factory_returns_three_tools() -> None:
    """supervisor_tools 工厂应返回 dispatch_subagent / list_roles / list_profiles。"""
    profiles = {
        "anth": _anthropic(),
        "ds": _deepseek(),
    }
    master = ToolRegistry()
    tools = supervisor_tools(
        roles=builtin_roles(),
        profile=profiles["anth"],
        master_registry=master,
        project_root=Path.cwd(),
        profiles=profiles,
        active_profile_name="anth",
    )
    names = [t.name for t in tools]
    assert names == ["dispatch_subagent", "list_roles", "list_profiles"]


def test_supervisor_tools_factory_works_without_profiles_dict() -> None:
    """单 profile 用户：不传 profiles，list_profiles 仍能列出唯一项。"""
    master = ToolRegistry()
    tools = supervisor_tools(
        roles=builtin_roles(),
        profile=_anthropic(label="solo"),
        master_registry=master,
        project_root=Path.cwd(),
    )
    assert len(tools) == 3
