"""议会式群英会单测。

覆盖：
- Verdict JSON 解析容错（markdown 包裹 / 前后带解释 / 完全乱码）
- Judge.judge 用 fake provider 返回结构化 Verdict
- CouncilEngine.convene 并行跑 + Judge 合成 + 进度事件 + 写记忆
- 单 Councilor 失败/超时不阻塞议会
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from xuanji.capability.registry import ToolRegistry
from xuanji.config import AnthropicProfile, DeepSeekProfile
from xuanji.config.profiles import Profile
from xuanji.ensemble.council import (
    CouncilEngine,
    CouncilorOutcome,
    CouncilorSpec,
    CouncilSpec,
)
from xuanji.ensemble.judge import (
    Judge,
    Verdict,
    _safe_parse_verdict_json,
)
from xuanji.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
    TextBlock,
    Usage,
)
from xuanji.memory.store.sqlite import SqliteMemoryStore
from xuanji.tools import builtin_tools

# --------------------------------------------------------------------------
# Verdict JSON 解析容错
# --------------------------------------------------------------------------


def test_safe_parse_plain_json() -> None:
    raw = '{"summary":"ok","chosen_path":null,"consensus_points":[],"divergence_points":[],"risks":[]}'
    parsed = _safe_parse_verdict_json(raw)
    assert parsed is not None
    assert parsed["summary"] == "ok"


def test_safe_parse_markdown_fenced() -> None:
    raw = (
        "好的，我裁决如下：\n"
        "```json\n"
        '{"summary": "选 QBox", "chosen_path": "QBox"}\n'
        "```\n"
        "如有异议请人工复核。"
    )
    parsed = _safe_parse_verdict_json(raw)
    assert parsed is not None
    assert parsed["summary"] == "选 QBox"
    assert parsed["chosen_path"] == "QBox"


def test_safe_parse_extracts_object_from_prose() -> None:
    raw = '裁决：{"summary":"x","consensus_points":["a","b"]}\n附注：略。'
    parsed = _safe_parse_verdict_json(raw)
    assert parsed is not None
    assert parsed["summary"] == "x"
    assert parsed["consensus_points"] == ["a", "b"]


def test_safe_parse_garbage_returns_none() -> None:
    assert _safe_parse_verdict_json("完全没有任何 JSON 的纯文本") is None
    assert _safe_parse_verdict_json("") is None


# --------------------------------------------------------------------------
# Judge fake provider
# --------------------------------------------------------------------------


class _FakeJudgeProvider(LLMProvider):
    """对每次 chat 返回固定的 AssistantMessage（用 verdict_text 当 TextBlock）。"""

    name = "fake-judge"

    def __init__(self, verdict_text: str) -> None:
        self._verdict_text = verdict_text
        self.calls: list[dict[str, Any]] = []

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model, provider="fake-judge",
            context_window=200_000, max_output_tokens=4096,
        )

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        system: str | None = None,
        **kw: Any,
    ) -> AssistantMessage:
        self.calls.append({"model": model, "system": system, "messages": list(messages)})
        return AssistantMessage(
            blocks=[TextBlock(text=self._verdict_text)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=20),
            model=model,
        )

    async def stream(self, **kw: Any) -> AsyncIterator[Delta]:
        yield Delta(type="message_done", stop_reason="end_turn")


@pytest.mark.asyncio
async def test_judge_parses_clean_json(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict_json = json.dumps(
        {
            "summary": "推荐用 QBox",
            "chosen_path": "QBox",
            "consensus_points": ["都偏好 ox_inventory"],
            "divergence_points": ["性能 vs 兼容性的取舍"],
            "risks": ["生态较小"],
        },
        ensure_ascii=False,
    )
    fake = _FakeJudgeProvider(verdict_json)
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        lambda _p: fake,
    )
    profile = AnthropicProfile(
        label="anthropic",
        api_key="sk-test-placeholder",
        default_model="claude-opus-4-7",
    )
    judge = Judge(profile=profile, model="claude-opus-4-7")

    outcomes = [
        CouncilorOutcome(
            role="稷下生",
            profile_name="ds",
            model="ds-v4",
            final_text="QBox 文档完善，建议用",
            iterations=1,
            tool_calls_made=0,
            truncated=False,
        ),
        CouncilorOutcome(
            role="百工匠",
            profile_name="oa",
            model="gpt-5",
            final_text="QBCore 也行但稍弱",
            iterations=1,
            tool_calls_made=0,
            truncated=False,
        ),
    ]

    verdict = await judge.judge(question="QBox 还是 QBCore", outcomes=outcomes)

    assert verdict.summary == "推荐用 QBox"
    assert verdict.chosen_path == "QBox"
    assert verdict.consensus_points == ["都偏好 ox_inventory"]
    assert verdict.risks == ["生态较小"]
    assert verdict.decided_by == "claude-opus-4-7"
    assert verdict.councilors == ["稷下生/ds/ds-v4", "百工匠/oa/gpt-5"]
    assert verdict.decided_at > 0


@pytest.mark.asyncio
async def test_judge_falls_back_on_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeJudgeProvider("我没法 JSON——请见谅")
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        lambda _p: fake,
    )
    profile = AnthropicProfile(
        label="anthropic",
        api_key="sk-test-placeholder",
        default_model="claude-opus-4-7",
    )
    judge = Judge(profile=profile, model="claude-opus-4-7")
    outcomes = [
        CouncilorOutcome(
            role="稷下生", profile_name="ds", model="m",
            final_text="x", iterations=1, tool_calls_made=0, truncated=False,
        ),
        CouncilorOutcome(
            role="百工匠", profile_name="oa", model="m",
            final_text="y", iterations=1, tool_calls_made=0, truncated=False,
        ),
    ]
    verdict = await judge.judge(question="q", outcomes=outcomes)
    assert verdict.chosen_path is None
    # fallback 把原文塞进 summary
    assert "Judge 解析失败" in verdict.summary or "我没法" in verdict.summary
    # 风险表里有提示
    assert any("人工复核" in r for r in verdict.risks)


# --------------------------------------------------------------------------
# CouncilEngine（用 fake subagent provider）
# --------------------------------------------------------------------------


class _FakeSubagentProvider(LLMProvider):
    """SubAgent.run 用的 stream provider——一轮回完。"""

    name = "fake-sub"

    def __init__(self, text: str) -> None:
        self._text = text

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model, provider="fake-sub",
            context_window=128_000, max_output_tokens=4096,
        )

    async def chat(self, **kw: Any) -> AssistantMessage:
        raise NotImplementedError

    async def stream(self, **kw: Any) -> AsyncIterator[Delta]:
        yield Delta(type="text_delta", index=0, text=self._text)
        yield Delta(type="message_done", stop_reason="end_turn")


@pytest.mark.asyncio
async def test_council_convene_full_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """两个 Councilor 都顺利跑完 → Judge 合成 → 写 episodic memory。"""
    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        lambda _p: _FakeSubagentProvider("Councilor 输出"),
    )
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        lambda _p: _FakeJudgeProvider(
            json.dumps(
                {
                    "summary": "议会通过",
                    "chosen_path": "PathA",
                    "consensus_points": ["共识1"],
                    "divergence_points": [],
                    "risks": ["风险一条"],
                },
                ensure_ascii=False,
            ),
        ),
    )

    ds_profile = DeepSeekProfile(
        label="ds", api_key="sk-test-placeholder", default_model="ds-v4",
    )
    anthropic_profile = AnthropicProfile(
        label="anthropic",
        api_key="sk-test-placeholder",
        default_model="claude-opus-4-7",
    )
    profiles: dict[str, Profile] = {
        "ds": ds_profile, "anthropic": anthropic_profile,
    }

    master = ToolRegistry()
    master.register_all(builtin_tools())
    memory = SqliteMemoryStore(tmp_path / "memory.db")

    engine = CouncilEngine(
        profiles=profiles,
        default_profile=ds_profile,
        active_profile_name="ds",
        master_registry=master,
        project_root=tmp_path,
        memory=memory,
    )

    events: list[tuple[str, dict[str, Any]]] = []

    async def on_progress(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    spec = CouncilSpec(
        question="该选 PathA 还是 PathB？",
        councilors=[
            CouncilorSpec(role="researcher"),
            CouncilorSpec(role="reviewer"),
        ],
        deadline_seconds=10.0,
    )
    outcome = await engine.convene(spec, on_progress=on_progress)

    assert outcome.verdict.chosen_path == "PathA"
    assert outcome.verdict.summary == "议会通过"
    assert outcome.memory_id is not None
    assert len(outcome.councilors) == 2
    for o in outcome.councilors:
        assert o.error is None
        assert o.final_text == "Councilor 输出"

    event_names = [e[0] for e in events]
    assert event_names[0] == "council_started"
    assert "council_judging" in event_names
    assert event_names[-1] == "council_done"
    # 至少两条 councilor_started + 两条 councilor_done
    assert event_names.count("councilor_started") == 2
    assert event_names.count("councilor_done") == 2

    # 写到了 council_decisions 命名空间
    saved = memory.list_by_namespace("council_decisions", limit=5)
    assert len(saved) == 1
    assert "PathA" in saved[0].text


@pytest.mark.asyncio
async def test_council_unknown_role_marks_truncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """role 名错了——单个 Councilor 标 truncated，议会照常完成。"""
    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        lambda _p: _FakeSubagentProvider("ok"),
    )
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        lambda _p: _FakeJudgeProvider(
            '{"summary":"x","chosen_path":null,"consensus_points":[],"divergence_points":[],"risks":[]}',
        ),
    )
    ds_profile = DeepSeekProfile(
        label="ds", api_key="sk-test-placeholder", default_model="ds",
    )
    engine = CouncilEngine(
        profiles={"ds": ds_profile},
        default_profile=ds_profile,
        master_registry=ToolRegistry(),
        project_root=tmp_path,
    )
    spec = CouncilSpec(
        question="q",
        councilors=[
            CouncilorSpec(role="ghost"),
            CouncilorSpec(role="researcher"),
        ],
    )
    outcome = await engine.convene(spec)
    bad, good = outcome.councilors
    assert bad.truncated
    assert bad.error is not None and "未知角色" in bad.error
    assert not good.truncated


@pytest.mark.asyncio
async def test_council_judge_profile_prefers_anthropic_opus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """有 anthropic profile 时，Judge 自动用 Opus。"""
    captured: list[tuple[str, str]] = []

    def fake_judge_provider(profile: Any) -> _FakeJudgeProvider:
        captured.append((type(profile).__name__, getattr(profile, "default_model", "")))
        return _FakeJudgeProvider(
            '{"summary":"y","chosen_path":null,"consensus_points":[],"divergence_points":[],"risks":[]}',
        )

    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        lambda _p: _FakeSubagentProvider("ok"),
    )
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        fake_judge_provider,
    )

    ds = DeepSeekProfile(
        label="ds", api_key="sk-test-placeholder", default_model="ds",
    )
    anthropic = AnthropicProfile(
        label="anthropic",
        api_key="sk-test-placeholder",
        default_model="claude-haiku-4-5",  # 故意写个非 Opus
    )

    engine = CouncilEngine(
        profiles={"ds": ds, "anthropic": anthropic},
        default_profile=ds,
        master_registry=ToolRegistry(),
        project_root=tmp_path,
    )
    spec = CouncilSpec(
        question="q",
        councilors=[
            CouncilorSpec(role="researcher"),
            CouncilorSpec(role="reviewer"),
        ],
    )
    outcome = await engine.convene(spec)
    # Judge 选了 anthropic，model 强制 Opus
    assert outcome.verdict.decided_by == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_council_timeout_isolates_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """单个 Councilor 跑超时，议会仍能拿到另一个的结果。"""

    class _SlowProvider(LLMProvider):
        name = "slow"

        def capabilities(self, model: str) -> ModelCapabilities:
            return ModelCapabilities(
                name=model, provider="slow",
                context_window=128_000, max_output_tokens=4096,
            )

        async def chat(self, **kw: Any) -> AssistantMessage:
            raise NotImplementedError

        async def stream(self, **kw: Any) -> AsyncIterator[Delta]:
            await asyncio.sleep(5.0)
            yield Delta(type="message_done", stop_reason="end_turn")

    call_count = {"n": 0}

    def _provider_factory(_p: Any) -> LLMProvider:
        call_count["n"] += 1
        # 第一个 Councilor 慢，第二个快
        if call_count["n"] == 1:
            return _SlowProvider()
        return _FakeSubagentProvider("快速完成")

    monkeypatch.setattr(
        "xuanji.ensemble.subagent.build_provider",
        _provider_factory,
    )
    monkeypatch.setattr(
        "xuanji.ensemble.judge.build_provider",
        lambda _p: _FakeJudgeProvider(
            '{"summary":"finished","chosen_path":null,"consensus_points":[],"divergence_points":[],"risks":[]}',
        ),
    )
    ds = DeepSeekProfile(
        label="ds", api_key="sk-test-placeholder", default_model="ds",
    )
    engine = CouncilEngine(
        profiles={"ds": ds},
        default_profile=ds,
        master_registry=ToolRegistry(),
        project_root=tmp_path,
    )
    spec = CouncilSpec(
        question="q",
        councilors=[
            CouncilorSpec(role="researcher"),
            CouncilorSpec(role="reviewer"),
        ],
        deadline_seconds=0.3,
    )
    outcome = await engine.convene(spec)
    slow_outcome = outcome.councilors[0]
    fast_outcome = outcome.councilors[1]
    assert slow_outcome.truncated
    assert slow_outcome.error is not None and "超时" in slow_outcome.error
    assert not fast_outcome.truncated
    assert fast_outcome.final_text == "快速完成"


# --------------------------------------------------------------------------
# CouncilSpec validation
# --------------------------------------------------------------------------


def test_council_spec_requires_two_councilors() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        CouncilSpec(
            question="q",
            councilors=[CouncilorSpec(role="researcher")],
        )


def test_council_spec_question_non_empty() -> None:
    with pytest.raises(ValueError):
        CouncilSpec(
            question="",
            councilors=[
                CouncilorSpec(role="researcher"),
                CouncilorSpec(role="reviewer"),
            ],
        )


def test_verdict_round_trips_via_pydantic() -> None:
    v = Verdict(
        summary="x",
        chosen_path="A",
        consensus_points=["c1"],
        divergence_points=["d1"],
        risks=["r1"],
        decided_by="m",
        councilors=["x/y/z"],
        decided_at=12345.0,
    )
    dumped = v.model_dump()
    restored = Verdict(**dumped)
    assert restored.summary == "x"
    assert restored.councilors == ["x/y/z"]
