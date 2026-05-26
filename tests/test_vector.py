"""向量检索骨架与混合检索单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.knowledge import (
    Chunk,
    HashingEmbedder,
    InMemoryVectorStore,
    SqliteKnowledgeStore,
)


def test_hashing_embedder_deterministic() -> None:
    """同输入永远同输出，跨进程一致。"""
    e = HashingEmbedder()
    v1 = e.embed("QBCore.Functions.GetPlayer")
    v2 = e.embed("QBCore.Functions.GetPlayer")
    assert v1 == v2
    assert len(v1) == e.dim


def test_hashing_embedder_different_inputs_differ() -> None:
    e = HashingEmbedder()
    v1 = e.embed("QBCore")
    v2 = e.embed("QBox")
    assert v1 != v2


def test_hashing_embedder_l2_normalized() -> None:
    """归一化后模长应≈1。"""
    e = HashingEmbedder()
    v = e.embed("hello world test")
    norm_sq = sum(x * x for x in v)
    assert abs(norm_sq - 1.0) < 0.01


def test_hashing_embedder_batch() -> None:
    e = HashingEmbedder()
    out = e.embed_batch(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(v) == e.dim for v in out)


# ---------------- InMemoryVectorStore ----------------


def test_inmemory_vector_store_basic() -> None:
    store = InMemoryVectorStore(dim=4)
    store.upsert("a", [1.0, 0.0, 0.0, 0.0], {"namespace": "ns@1"})
    store.upsert("b", [0.0, 1.0, 0.0, 0.0], {"namespace": "ns@1"})
    assert store.size() == 2
    hits = store.search([1.0, 0.0, 0.0, 0.0], k=2)
    assert hits[0].id == "a"
    assert hits[0].score > hits[1].score


def test_inmemory_vector_store_namespace_filter() -> None:
    store = InMemoryVectorStore(dim=4)
    store.upsert("a", [1.0, 0.0, 0.0, 0.0], {"namespace": "alpha"})
    store.upsert("b", [1.0, 0.0, 0.0, 0.0], {"namespace": "beta"})
    hits = store.search([1.0, 0.0, 0.0, 0.0], k=10, filter_namespace="alpha")
    assert len(hits) == 1
    assert hits[0].id == "a"


def test_inmemory_vector_store_dim_mismatch() -> None:
    store = InMemoryVectorStore(dim=4)
    with pytest.raises(ValueError, match="维度"):
        store.upsert("a", [1.0, 2.0, 3.0], {})  # 3 != 4
    store.upsert("a", [1.0, 0.0, 0.0, 0.0], {})
    with pytest.raises(ValueError, match="维度"):
        store.search([1.0, 2.0], k=1)


def test_inmemory_vector_store_delete_namespace() -> None:
    store = InMemoryVectorStore(dim=4)
    for i in range(3):
        store.upsert(f"a{i}", [1.0, 0.0, 0.0, 0.0], {"namespace": "alpha"})
    for i in range(2):
        store.upsert(f"b{i}", [0.0, 1.0, 0.0, 0.0], {"namespace": "beta"})
    n = store.delete_namespace("alpha")
    assert n == 3
    assert store.size() == 2


# ---------------- 混合检索 ----------------


def test_attach_vector_index_dim_mismatch(tmp_path: Path) -> None:
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    embedder = HashingEmbedder(dim=128)
    vstore = InMemoryVectorStore(dim=256)
    with pytest.raises(ValueError, match="dim"):
        store.attach_vector_index(embedder, vstore)


def test_hybrid_search_falls_back_when_no_vector(tmp_path: Path) -> None:
    """没挂向量索引时 hybrid_search 应等价于 search。"""
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    store.upsert_chunks(
        [Chunk(id="ns@1:c#0", namespace="ns@1", source_title="T", text="alpha 关键词")],
    )
    hits = store.hybrid_search("alpha")
    assert hits
    assert hits[0].source == "fts"


def test_hybrid_search_uses_both_signals(tmp_path: Path) -> None:
    """挂载向量索引后，混合检索应能召回 FTS 漏掉但语义近的内容。"""
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    embedder = HashingEmbedder()
    vstore = InMemoryVectorStore(dim=embedder.dim)
    store.attach_vector_index(embedder, vstore)

    store.upsert_chunks(
        [
            Chunk(
                id="ns@1:a#0",
                namespace="ns@1",
                source_title="T",
                text="QBCore CreateUseableItem 注册可使用物品",
            ),
            Chunk(
                id="ns@1:b#0",
                namespace="ns@1",
                source_title="T",
                text="完全无关的内容讨论天气和食物",
            ),
        ],
    )
    # 向量索引应该被同步写入
    assert vstore.size() == 2

    hits = store.hybrid_search("CreateUseableItem", k=2)
    assert hits
    assert hits[0].chunk.id == "ns@1:a#0"
    assert hits[0].source == "hybrid"


def test_clear_namespace_purges_vector_index(tmp_path: Path) -> None:
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    embedder = HashingEmbedder()
    vstore = InMemoryVectorStore(dim=embedder.dim)
    store.attach_vector_index(embedder, vstore)
    store.upsert_chunks(
        [
            Chunk(id="a:1#0", namespace="a", source_title="T", text="alpha"),
            Chunk(id="b:1#0", namespace="b", source_title="T", text="beta"),
        ],
    )
    assert vstore.size() == 2
    store.clear_namespace("a")
    assert vstore.size() == 1


def test_search_hit_source_field(tmp_path: Path) -> None:
    """SearchHit.source 字段标识来源。"""
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    store.upsert_chunks(
        [Chunk(id="a:1#0", namespace="a", source_title="T", text="alpha")],
    )
    hits = store.search("alpha")
    assert hits[0].source == "fts"
