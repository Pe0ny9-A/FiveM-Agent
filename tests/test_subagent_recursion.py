"""1.2.0 sub-agent 递归 dispatch 测试。

验证：
- 默认 max_depth=2，可嵌套两层
- 超深度时 dispatch 工具自身报 ToolError，不继续深入
- output 含 depth + parent_role 元信息
- nested DispatchSubagentTool 被注入到 sub-agent 的工具集
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import ToolCtx, ToolError
from xuanji.config.profiles import AnthropicProfile, Profile
from xuanji.ensemble import builtin_roles
from xuanji.ensemble.supervisor import DispatchSubagentTool
from xuanji.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
)
from xuanji.tools import builtin_tools


class _DoneProvider(LLMProvider):
    """只回 text + end_turn，不调任何工具。"""

    name = "fake"

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model,
            provider="fake",
            context_window=128_000,
            max_output_tokens=4096,
        )

    async def chat(self, **kw: Any) -> AssistantMessage:
        raise NotImplementedError

    async def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        system: str | None = None,
        **kw: Any,
    ) -> AsyncIterator[Delta]:
        yield Delta(type="text_delta", index=0, text="ok")
        yield Delta(type="message_done", stop_reason="end_turn")


def _anthropic(label: str = "a", model: str = "claude-x") -> Profile:
    return AnthropicProfile(
        label=label, api_key="sk-test-placeholder", default_model=model,
    )


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        lambda _p: _DoneProvider(),
    )


@pytest.mark.asyncio
async def test_dispatch_output_includes_depth_and_parent(tmp_path: Path) -> None:
    """顶层 dispatch 出来的结果应该 depth=1, parent_role=None。"""
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute({"role": "researcher", "brief": "查一下"}, ctx)
    assert res.ok
    assert res.output["depth"] == 1
    assert res.output["parent_role"] is None


@pytest.mark.asyncio
async def test_dispatch_blocks_when_depth_exceeds_max(tmp_path: Path) -> None:
    """depth >= max_depth 时直接拒绝，不再召唤 sub-agent。"""
    master = ToolRegistry()
    master.register_all(builtin_tools())
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        default_profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
        depth=2,
        max_depth=2,
        parent_role="稷下生",
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    with pytest.raises(ToolError) as exc_info:
        await tool.execute({"role": "researcher", "brief": "再嵌套"}, ctx)
    assert "max_depth" in str(exc_info.value)
    assert "稷下生" in str(exc_info.value)


@pytest.mark.asyncio
async def test_nested_dispatch_injected_into_subagent(tmp_path: Path) -> None:
    """sub-agent 拿到的 master_registry 里应有一个 depth+1 的 dispatch_subagent。

    用观察 ToolRegistry 注入的方式校验：sub-agent 启动时 SubAgent.__init__ 会
    根据 role.allowed_tools 过滤；稷下生 allowed_tools 含 dispatch_subagent，
    所以 sub.registry 应有这个工具，且它的 _depth=1。
    """
    captured: dict[str, Any] = {}

    real_subagent_init = None

    from xuanji.ensemble import subagent as _subagent_mod

    real_subagent_init = _subagent_mod.SubAgent.__init__

    def spy_init(
        self: _subagent_mod.SubAgent, *args: Any, **kwargs: Any,
    ) -> None:
        assert real_subagent_init is not None
        real_subagent_init(self, *args, **kwargs)
        captured["registry"] = self.registry

    monkeypatch_target = _subagent_mod.SubAgent
    monkeypatch_target.__init__ = spy_init  # type: ignore[method-assign]
    try:
        master = ToolRegistry()
        master.register_all(builtin_tools())
        tool = DispatchSubagentTool(
            roles=builtin_roles(),
            default_profile=_anthropic(),
            master_registry=master,
            project_root=tmp_path,
            depth=0,
            max_depth=3,
        )
        ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
        await tool.execute({"role": "researcher", "brief": "x"}, ctx)
    finally:
        monkeypatch_target.__init__ = real_subagent_init  # type: ignore[method-assign]

    sub_registry = captured["registry"]
    nested = sub_registry.get("dispatch_subagent")
    assert nested is not None
    assert nested._depth == 1
    assert nested._parent_role == "稷下生"
    assert nested._max_depth == 3


@pytest.mark.asyncio
async def test_supervisor_tools_factory_default_max_depth(tmp_path: Path) -> None:
    """工厂默认 max_depth=2。"""
    from xuanji.ensemble.supervisor import supervisor_tools

    master = ToolRegistry()
    master.register_all(builtin_tools())
    tools = supervisor_tools(
        roles=builtin_roles(),
        profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
    )
    dispatch = next(t for t in tools if t.name == "dispatch_subagent")
    assert isinstance(dispatch, DispatchSubagentTool)
    assert dispatch._max_depth == 2  # type: ignore[attr-defined]
    assert dispatch._depth == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_supervisor_tools_factory_custom_max_depth(tmp_path: Path) -> None:
    """工厂可自定义 max_depth。"""
    from xuanji.ensemble.supervisor import supervisor_tools

    master = ToolRegistry()
    master.register_all(builtin_tools())
    tools = supervisor_tools(
        roles=builtin_roles(),
        profile=_anthropic(),
        master_registry=master,
        project_root=tmp_path,
        max_depth=4,
    )
    dispatch = next(t for t in tools if t.name == "dispatch_subagent")
    assert dispatch._max_depth == 4  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dispatch_excludes_old_dispatch_from_nested_master(
    tmp_path: Path,
) -> None:
    """嵌套 master_registry 不应包含父层的 dispatch_subagent——
    只能用我们替换进去的 nested 实例（depth+1）。"""
    captured: dict[str, Any] = {}
    from xuanji.ensemble import subagent as _subagent_mod

    real_subagent_init = _subagent_mod.SubAgent.__init__

    def spy_init(
        self: _subagent_mod.SubAgent, *args: Any, **kwargs: Any,
    ) -> None:
        real_subagent_init(self, *args, **kwargs)
        captured["registry"] = self.registry
        captured["master"] = kwargs.get("master_registry") or args[2]

    monkeypatch_target = _subagent_mod.SubAgent
    monkeypatch_target.__init__ = spy_init  # type: ignore[method-assign]
    try:
        master = ToolRegistry()
        master.register_all(builtin_tools())
        # master 也含一个 dispatch_subagent（模拟主 Conductor 注入）
        outer_dispatch = DispatchSubagentTool(
            roles=builtin_roles(),
            default_profile=_anthropic(),
            master_registry=master,
            project_root=tmp_path,
            depth=0,
            max_depth=2,
        )
        master.register(outer_dispatch)
        ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
        await outer_dispatch.execute(
            {"role": "researcher", "brief": "x"}, ctx,
        )
    finally:
        monkeypatch_target.__init__ = real_subagent_init  # type: ignore[method-assign]

    inner_master = captured["master"]
    inner_dispatch = inner_master.get("dispatch_subagent")
    assert inner_dispatch is not None
    # 应该是 depth=1 的新实例，而不是原 outer
    assert inner_dispatch is not outer_dispatch
    assert inner_dispatch._depth == 1  # type: ignore[attr-defined]
