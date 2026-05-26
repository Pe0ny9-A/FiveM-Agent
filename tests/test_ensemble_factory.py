"""ToolFactory + 群英会单测。

ToolFactory 走 SubAgent 调 LLM 的链路用 mock 跳过；
SubAgent 也用 FakeProvider 注入静态响应。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from core.capability.registry import ToolRegistry
from core.capability.tool import ToolCtx
from core.config import DeepSeekProfile
from core.ensemble import (
    CODER_ROLE,
    RESEARCHER_ROLE,
    REVIEWER_ROLE,
    DispatchSubagentTool,
    SubAgent,
    builtin_roles,
)
from core.ensemble.supervisor import ListRolesTool
from core.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
)
from core.tools import builtin_tools
from core.tools.tool_factory import (
    FactoryRegistry,
    FactoryStatus,
    ToolFactory,
    _extract_blocks,
)

# ============================================================
# 群英会
# ============================================================


def test_builtin_roles_have_expected_set() -> None:
    roles = builtin_roles()
    assert set(roles.keys()) == {"researcher", "coder", "reviewer"}


def test_role_tool_whitelists() -> None:
    """三角色的 allowed_tools 设计要点：reviewer 不能写文件。"""
    assert "write_file" not in REVIEWER_ROLE.allowed_tools
    assert "run_shell" not in REVIEWER_ROLE.allowed_tools
    assert "write_file" in CODER_ROLE.allowed_tools
    assert "knowledge_search" in RESEARCHER_ROLE.allowed_tools


@pytest.mark.asyncio
async def test_list_roles_tool(tmp_path: Path) -> None:
    tool = ListRolesTool(builtin_roles())
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute({}, ctx)
    assert res.ok
    names = {r["name"] for r in res.output}
    assert names == {"researcher", "coder", "reviewer"}


# ----------------- SubAgent 集成 -----------------


class _FakeProvider(LLMProvider):
    """rounds: 多轮响应；每轮一个 Delta 列表。"""

    name = "fake"

    def __init__(self, rounds: list[list[Delta]]) -> None:
        self._rounds = rounds
        self._iter = 0

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model, provider="fake",
            context_window=128_000, max_output_tokens=4096,
        )

    async def chat(self, **kw: Any) -> AssistantMessage:
        raise NotImplementedError

    async def stream(
        self, *, model: str, messages: Sequence[Message],
        system: str | None = None, **kw: Any,
    ) -> AsyncIterator[Delta]:
        idx = min(self._iter, len(self._rounds) - 1)
        self._iter += 1
        for d in self._rounds[idx]:
            yield d


@pytest.mark.asyncio
async def test_subagent_runs_to_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """SubAgent 应能完成一次性任务。"""
    rounds: list[list[Delta]] = [
        [
            Delta(type="text_delta", index=0, text="研究完毕："),
            Delta(type="text_delta", index=0, text="QBox 用 ox_inventory。"),
            Delta(type="message_done", stop_reason="end_turn"),
        ],
    ]
    monkeypatch.setattr(
        "core.ensemble.subagent.build_provider",
        lambda _p: _FakeProvider(rounds),
    )

    master = ToolRegistry()
    master.register_all(builtin_tools())

    sub = SubAgent(
        RESEARCHER_ROLE,
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
        master_registry=master,
        project_root=tmp_path,
    )
    result = await sub.run("查 QBox 的物品系统")
    assert "QBox" in result.final_text
    assert result.iterations == 1
    assert result.tool_calls_made == 0
    assert not result.truncated


@pytest.mark.asyncio
async def test_subagent_filters_tools_by_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """SubAgent 的 registry 应只包含 role.allowed_tools 列出的工具。"""
    monkeypatch.setattr(
        "core.ensemble.subagent.build_provider",
        lambda _p: _FakeProvider([[Delta(type="message_done", stop_reason="end_turn")]]),
    )
    master = ToolRegistry()
    master.register_all(builtin_tools())  # 含 write_file / run_shell

    sub = SubAgent(
        REVIEWER_ROLE,  # reviewer 不能写不能 shell
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
        master_registry=master,
        project_root=tmp_path,
    )
    names = sub.registry.names()
    assert "write_file" not in names
    assert "run_shell" not in names
    assert "read_file" in names
    # list_tools 自动注入
    assert "list_tools" in names


@pytest.mark.asyncio
async def test_dispatch_subagent_tool_unknown_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """未知 role 应抛 ToolError。"""
    from core.capability.tool import ToolError

    monkeypatch.setattr(
        "core.ensemble.subagent.build_provider",
        lambda _p: _FakeProvider([[Delta(type="message_done", stop_reason="end_turn")]]),
    )
    master = ToolRegistry()
    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
        master_registry=master,
        project_root=tmp_path,
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    with pytest.raises(ToolError, match="未知角色"):
        await tool.execute({"role": "ghost", "brief": "x"}, ctx)


@pytest.mark.asyncio
async def test_dispatch_subagent_tool_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """端到端：dispatch_subagent 工具召唤 sub-agent 并返回结果。"""
    rounds: list[list[Delta]] = [
        [
            Delta(type="text_delta", index=0, text="子任务完成"),
            Delta(type="message_done", stop_reason="end_turn"),
        ],
    ]
    monkeypatch.setattr(
        "core.ensemble.subagent.build_provider",
        lambda _p: _FakeProvider(rounds),
    )
    master = ToolRegistry()
    master.register_all(builtin_tools())

    tool = DispatchSubagentTool(
        roles=builtin_roles(),
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
        master_registry=master,
        project_root=tmp_path,
    )
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    res = await tool.execute(
        {"role": "researcher", "brief": "随便查点东西"}, ctx,
    )
    assert res.ok
    assert res.output["role"] == "researcher"
    assert res.output["final_text"] == "子任务完成"


# ============================================================
# ToolFactory
# ============================================================


def test_extract_blocks_basic() -> None:
    text = (
        "preamble\n"
        "```python:tool\n"
        "class Foo: pass\n"
        "```\n"
        "between\n"
        "```python:test\n"
        "def test_foo(): pass\n"
        "```\n"
        "trailing\n"
    )
    tool, test = _extract_blocks(text)
    assert "class Foo" in tool
    assert "test_foo" in test


def test_extract_blocks_missing_returns_empty() -> None:
    """没有正确格式时返回空字符串而不是抛错——上游决定怎么处理。"""
    tool, test = _extract_blocks("just some text")
    assert tool == ""
    assert test == ""


def test_factory_registry_roundtrip(tmp_path: Path) -> None:
    """FactoryRegistry 应能正确持久化状态。"""
    reg = FactoryRegistry(tmp_path / "factory.db")
    s1 = FactoryStatus(
        slug="lint_lua",
        status="generated",
        code_path=tmp_path / "lint_lua.py",
    )
    reg.upsert(s1)
    loaded = reg.get("lint_lua")
    assert loaded is not None
    assert loaded.status == "generated"
    assert loaded.code_path == tmp_path / "lint_lua.py"


def test_factory_registry_lists_recent_first(tmp_path: Path) -> None:
    import time

    reg = FactoryRegistry(tmp_path / "f.db")
    reg.upsert(FactoryStatus(slug="a", status="draft", updated_at=time.time() - 100))
    reg.upsert(FactoryStatus(slug="b", status="draft", updated_at=time.time()))
    items = reg.all()
    assert items[0].slug == "b"  # 最近更新在前


def test_factory_publish_blocks_untested(tmp_path: Path) -> None:
    """没跑过测试或测试失败时 publish 应抛 ValueError。"""
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    drafts.mkdir(parents=True, exist_ok=True)
    staged.mkdir(parents=True, exist_ok=True)
    published.mkdir(parents=True, exist_ok=True)
    reg = FactoryRegistry(tmp_path / "f.db")
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=reg,
    )
    # 写一个 generated 但没 tested 的状态
    code_path = staged / "x.py"
    code_path.write_text("# fake", encoding="utf-8")
    reg.upsert(
        FactoryStatus(
            slug="x", status="generated",
            code_path=code_path,
            test_path=staged / "test_x.py",
            last_test_passed=None,
        ),
    )
    with pytest.raises(ValueError, match="测试未通过"):
        factory.publish("x")


def test_factory_publish_after_test_passes(tmp_path: Path) -> None:
    """test 通过后 publish 应成功。"""
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    reg = FactoryRegistry(tmp_path / "f.db")
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=reg,
    )
    code_path = staged / "good.py"
    code_path.write_text("# good\n", encoding="utf-8")
    reg.upsert(
        FactoryStatus(
            slug="good",
            status="tested",
            code_path=code_path,
            test_path=staged / "test_good.py",
            last_test_passed=True,
        ),
    )
    status = factory.publish("good")
    assert status.status == "published"
    assert (published / "good.py").exists()
    assert (published / "good.py").read_text(encoding="utf-8") == "# good\n"


def test_factory_load_draft_missing(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=FactoryRegistry(tmp_path / "f.db"),
    )
    with pytest.raises(FileNotFoundError):
        factory.load_draft("ghost")


def test_factory_test_subprocess_runs_pytest(tmp_path: Path) -> None:
    """factory.test 用 subprocess 跑 pytest，能正确捕获通过/失败。"""
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    reg = FactoryRegistry(tmp_path / "f.db")
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=reg,
    )
    code_path = staged / "smoke.py"
    test_path = staged / "test_smoke.py"
    code_path.write_text("def x(): return 1\n", encoding="utf-8")
    test_path.write_text(
        "def test_passes():\n    assert 1 + 1 == 2\n", encoding="utf-8",
    )
    reg.upsert(
        FactoryStatus(
            slug="smoke",
            status="generated",
            code_path=code_path,
            test_path=test_path,
        ),
    )
    status = factory.test("smoke", timeout_sec=30)
    assert status.last_test_passed is True
    assert status.status == "tested"


def test_factory_test_captures_failures(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    reg = FactoryRegistry(tmp_path / "f.db")
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=reg,
    )
    code_path = staged / "bad.py"
    test_path = staged / "test_bad.py"
    code_path.write_text("# bad\n", encoding="utf-8")
    test_path.write_text(
        "def test_fails():\n    assert 1 + 1 == 3\n", encoding="utf-8",
    )
    reg.upsert(
        FactoryStatus(
            slug="bad", status="generated",
            code_path=code_path, test_path=test_path,
        ),
    )
    status = factory.test("bad", timeout_sec=30)
    assert status.last_test_passed is False
    assert status.status == "generated"  # 没升级到 tested
    # 即便测试失败，publish 也应被拒
    with pytest.raises(ValueError):
        factory.publish("bad")


def test_factory_reject(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    reg = FactoryRegistry(tmp_path / "f.db")
    factory = ToolFactory(
        drafts_dir=drafts, staged_dir=staged,
        published_dir=published, registry=reg,
    )
    status = factory.reject("nope", reason="design unsuitable")
    assert status.status == "rejected"
    assert "design unsuitable" in status.last_test_output


@pytest.mark.asyncio
async def test_factory_generate_extracts_two_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """factory.generate 调 LLM 后应把两段代码切到 staged/。"""
    from core.llm.providers.base import TextBlock, Usage

    fake_response = AssistantMessage(
        blocks=[
            TextBlock(
                text=(
                    "好的，姐姐生成代码：\n"
                    "```python:tool\n"
                    "from core.capability.tool import Tool\n"
                    "class FakeTool: pass\n"
                    "```\n"
                    "```python:test\n"
                    "def test_x(): assert True\n"
                    "```\n"
                ),
            ),
        ],
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=20),
        model="fake",
    )

    class FakeProviderForGen:
        name = "fake"

        def capabilities(self, model: str) -> ModelCapabilities:
            return ModelCapabilities(
                name=model, provider="fake",
                context_window=128_000, max_output_tokens=4096,
            )

        async def chat(self, **kw: Any) -> AssistantMessage:
            return fake_response

        async def stream(self, **kw: Any) -> AsyncIterator[Delta]:
            yield Delta(type="message_done", stop_reason="end_turn")

    monkeypatch.setattr(
        "core.tools.tool_factory.build_provider",
        lambda _p: FakeProviderForGen(),
    )

    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    (drafts / "fake_tool.json").write_text(
        json.dumps(
            {
                "name": "fake_tool",
                "description": "测试用",
                "input_schema": {"type": "object"},
                "rationale": "test",
                "risk": "safe",
            },
        ),
        encoding="utf-8",
    )
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=FactoryRegistry(tmp_path / "f.db"),
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
    )
    status = await factory.generate("fake_tool")
    assert status.status == "generated"
    assert status.code_path is not None
    assert "FakeTool" in status.code_path.read_text(encoding="utf-8")
    assert status.test_path is not None
    assert "test_x" in status.test_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_factory_generate_rejects_bad_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """LLM 输出格式不对时应抛 ValueError，不能创建空文件。"""
    from core.llm.providers.base import TextBlock, Usage

    bad_response = AssistantMessage(
        blocks=[TextBlock(text="just some prose without code blocks")],
        stop_reason="end_turn",
        usage=Usage(),
        model="fake",
    )

    class FakeProviderBad:
        name = "fake"

        def capabilities(self, model: str) -> ModelCapabilities:
            return ModelCapabilities(
                name=model, provider="fake",
                context_window=128_000, max_output_tokens=4096,
            )

        async def chat(self, **kw: Any) -> AssistantMessage:
            return bad_response

        async def stream(self, **kw: Any) -> AsyncIterator[Delta]:
            yield Delta(type="message_done", stop_reason="end_turn")

    monkeypatch.setattr(
        "core.tools.tool_factory.build_provider",
        lambda _p: FakeProviderBad(),
    )

    drafts = tmp_path / "drafts"
    staged = tmp_path / "staged"
    published = tmp_path / "published"
    for d in (drafts, staged, published):
        d.mkdir(parents=True, exist_ok=True)
    (drafts / "x.json").write_text(
        json.dumps(
            {
                "name": "x",
                "description": "x",
                "input_schema": {"type": "object"},
                "rationale": "x",
            },
        ),
        encoding="utf-8",
    )
    factory = ToolFactory(
        drafts_dir=drafts,
        staged_dir=staged,
        published_dir=published,
        registry=FactoryRegistry(tmp_path / "f.db"),
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="ds"),
    )
    with pytest.raises(ValueError, match="格式不对"):
        await factory.generate("x")
