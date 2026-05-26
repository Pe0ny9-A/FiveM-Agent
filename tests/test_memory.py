"""怀玉阁单测：SqliteMemoryStore + Reflux + Conductor 集成。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from xuanji.memory import (
    Memory,
    MemoryKind,
    MemoryScope,
    SqliteMemoryStore,
    refluxed_fragment,
)


@pytest.fixture
def store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(tmp_path / "m.db")


# ---------------- 写读 ----------------


def test_empty_stats(store: SqliteMemoryStore) -> None:
    s = store.stats()
    assert s["total"] == 0
    assert s["namespaces"] == []


def test_write_then_recall(store: SqliteMemoryStore) -> None:
    m = Memory(
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        namespace="proj",
        text="项目用 QBox 框架，不要默认走 QBCore",
        importance=0.9,
    )
    store.write(m)
    hits = store.recall("QBox", namespace="proj")
    assert len(hits) == 1
    assert "QBox" in hits[0].text
    # 命中后 hits + 1
    assert hits[0].hits == 1


def test_namespace_isolation(store: SqliteMemoryStore) -> None:
    """不同命名空间互不可见。"""
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="a", text="apple"),
    )
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="b", text="apple"),
    )
    in_a = store.recall("apple", namespace="a")
    assert len(in_a) == 1
    assert in_a[0].namespace == "a"


def test_scope_filter(store: SqliteMemoryStore) -> None:
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="x", text="hello"),
    )
    store.write(
        Memory(scope=MemoryScope.SESSION, kind=MemoryKind.EPISODIC,
               namespace="x", text="hello"),
    )
    only_session = store.recall("hello", scopes=[MemoryScope.SESSION])
    assert len(only_session) == 1
    assert only_session[0].scope == MemoryScope.SESSION


def test_kind_filter(store: SqliteMemoryStore) -> None:
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="x", text="event"),
    )
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.PROCEDURAL,
               namespace="x", text="event"),
    )
    proc = store.recall("event", kinds=[MemoryKind.PROCEDURAL])
    assert len(proc) == 1
    assert proc[0].kind == MemoryKind.PROCEDURAL


# ---------------- 排序 ----------------


def test_recall_orders_by_importance_decay_hits(store: SqliteMemoryStore) -> None:
    """importance 高 + 最近访问 → 排在前面。"""
    now = time.time()
    fresh_high = Memory(
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        namespace="x",
        text="alpha",
        importance=0.9,
        last_accessed=now,
    )
    stale_low = Memory(
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        namespace="x",
        text="alpha",
        importance=0.2,
        last_accessed=now - 86400 * 365,  # 一年前
    )
    store.write(stale_low)
    store.write(fresh_high)
    hits = store.recall("alpha", namespace="x")
    assert hits[0].id == fresh_high.id


# ---------------- forget / consolidate ----------------


def test_forget_by_namespace(store: SqliteMemoryStore) -> None:
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="doomed", text="x"),
    )
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="alive", text="y"),
    )
    n = store.forget(namespace="doomed")
    assert n == 1
    assert store.list_by_namespace("doomed") == []
    assert len(store.list_by_namespace("alive")) == 1


def test_forget_no_filter_returns_zero(store: SqliteMemoryStore) -> None:
    """无任何条件时不应误删全表。"""
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="x", text="safe"),
    )
    n = store.forget()
    assert n == 0
    assert len(store.list_by_namespace("x")) == 1


def test_consolidate_keeps_top_n(store: SqliteMemoryStore) -> None:
    """超出 max_kept 时按 importance 倒序保留。"""
    for i in range(5):
        store.write(
            Memory(
                scope=MemoryScope.PROJECT,
                kind=MemoryKind.EPISODIC,
                namespace="ns",
                text=f"event {i}",
                importance=i / 10,  # 0.0 / 0.1 / 0.2 / 0.3 / 0.4
            ),
        )
    n = store.consolidate("ns", max_kept=3)
    assert n == 2
    remained = store.list_by_namespace("ns")
    # 留下 importance 最高的 3 条（0.2 / 0.3 / 0.4）
    importances = sorted(m.importance for m in remained)
    assert importances == pytest.approx([0.2, 0.3, 0.4])


# ---------------- FTS5 安全性 ----------------


def test_recall_handles_dangerous_input(store: SqliteMemoryStore) -> None:
    store.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="x", text="hello"),
    )
    for q in ['"', "(*)", "x:y", '"unbalanced', "OR ()", "a-b"]:
        store.recall(q)


# ---------------- Reflux ----------------


def test_reflux_fragment_empty_returns_none() -> None:
    assert refluxed_fragment([]) is None


def test_reflux_fragment_includes_scope_kind() -> None:
    m = Memory(
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        namespace="x",
        text="项目用 QBox",
    )
    frag = refluxed_fragment([m])
    assert frag is not None
    assert "QBox" in frag
    assert "[project/semantic]" in frag
    assert "过往记忆回流" in frag


# ---------------- Conductor 集成 ----------------


@pytest.mark.asyncio
async def test_conductor_reflux_injects_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Conductor.send 调用前应把命中的记忆注入 system prompt。"""
    from collections.abc import AsyncIterator, Sequence
    from typing import Any

    from xuanji.config import DeepSeekProfile
    from xuanji.llm.providers.base import (
        AssistantMessage,
        Delta,
        LLMProvider,
        Message,
        ModelCapabilities,
    )
    from xuanji.neural import Conductor

    captured_systems: list[str] = []

    class CapturingProvider(LLMProvider):
        name = "fake"

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
            captured_systems.append(system or "")
            yield Delta(type="message_done", stop_reason="end_turn")

    monkeypatch.setattr(
        "xuanji.neural.conductor.build_provider",
        lambda _p: CapturingProvider(),
    )

    mem = SqliteMemoryStore(tmp_path / "m.db")
    mem.write(
        Memory(
            scope=MemoryScope.PROJECT,
            kind=MemoryKind.SEMANTIC,
            namespace="proj",
            text="本项目用 QBox 不是 QBCore",
            importance=0.9,
        ),
    )

    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
        memory=mem,
        memory_namespace="proj",
        project_root=tmp_path,
    )
    async for _ in conductor.send("怎么加物品 QBox"):
        pass

    assert captured_systems
    sys_prompt = captured_systems[0]
    assert "过往记忆回流" in sys_prompt
    assert "QBox" in sys_prompt


@pytest.mark.asyncio
async def test_conductor_no_memory_no_reflux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """没有 memory 时 system prompt 不应出现回流段。"""
    from collections.abc import AsyncIterator
    from typing import Any

    from xuanji.config import DeepSeekProfile
    from xuanji.llm.providers.base import (
        AssistantMessage,
        Delta,
        LLMProvider,
        ModelCapabilities,
    )
    from xuanji.neural import Conductor

    captured: list[str] = []

    class P(LLMProvider):
        name = "fake"

        def capabilities(self, model: str) -> ModelCapabilities:
            return ModelCapabilities(
                name=model, provider="fake",
                context_window=128_000, max_output_tokens=4096,
            )

        async def chat(self, **kw: Any) -> AssistantMessage:
            raise NotImplementedError

        async def stream(
            self, *, system: str | None = None, **kw: Any,
        ) -> AsyncIterator[Delta]:
            captured.append(system or "")
            yield Delta(type="message_done", stop_reason="end_turn")

    monkeypatch.setattr("xuanji.neural.conductor.build_provider", lambda _p: P())
    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
        project_root=tmp_path,
    )
    async for _ in conductor.send("hi"):
        pass

    assert captured
    assert "过往记忆回流" not in captured[0]
