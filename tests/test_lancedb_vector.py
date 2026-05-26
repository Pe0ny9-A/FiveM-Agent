"""LanceDBVectorStore 单测：跟 InMemoryVectorStore 同 fixture，行为对齐。

依赖 lancedb / pyarrow（vector extra）。装了就跑，没装就 skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("pyarrow")

from xuanji.knowledge.vector import LanceDBVectorStore


@pytest.fixture
def store(tmp_path: Path) -> LanceDBVectorStore:
    return LanceDBVectorStore(str(tmp_path / "lance"), table="t", dim=8)


def test_upsert_and_search(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {"namespace": "ns1"})
    store.upsert("b", [0.9] * 8, {"namespace": "ns2"})
    hits = store.search([0.1] * 8, k=2)
    assert len(hits) == 2
    assert hits[0].id == "a"
    assert hits[0].score > hits[1].score


def test_upsert_batch(store: LanceDBVectorStore) -> None:
    store.upsert_batch([
        ("x", [0.0] * 8, {"namespace": "ns1"}),
        ("y", [0.5] * 8, {"namespace": "ns2"}),
    ])
    assert store.size() == 2


def test_upsert_overwrites_same_id(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {"namespace": "v1"})
    store.upsert("a", [0.9] * 8, {"namespace": "v2"})
    assert store.size() == 1
    hits = store.search([0.9] * 8, k=1)
    assert hits[0].metadata["namespace"] == "v2"


def test_dim_mismatch_raises(store: LanceDBVectorStore) -> None:
    with pytest.raises(ValueError, match="维度不匹配"):
        store.upsert("a", [0.1] * 4, {})
    with pytest.raises(ValueError, match="维度不匹配"):
        store.search([0.1] * 4, k=1)


def test_filter_by_namespace(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {"namespace": "ns1"})
    store.upsert("b", [0.1] * 8, {"namespace": "ns2"})
    hits = store.search([0.1] * 8, k=10, filter_namespace="ns1")
    assert len(hits) == 1
    assert hits[0].id == "a"


def test_delete(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {})
    assert store.delete("a") is True
    assert store.size() == 0
    assert store.delete("ghost") is False


def test_delete_namespace(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {"namespace": "ns1"})
    store.upsert("b", [0.2] * 8, {"namespace": "ns1"})
    store.upsert("c", [0.3] * 8, {"namespace": "ns2"})
    n = store.delete_namespace("ns1")
    assert n == 2
    assert store.size() == 1


def test_metadata_roundtrip(store: LanceDBVectorStore) -> None:
    store.upsert("a", [0.1] * 8, {"namespace": "n", "extra": {"k": "v"}, "n": 42})
    hits = store.search([0.1] * 8, k=1)
    assert hits[0].metadata["namespace"] == "n"
    assert hits[0].metadata["extra"] == {"k": "v"}
    assert hits[0].metadata["n"] == 42


def test_persists_across_instances(tmp_path: Path) -> None:
    """同一目录新 store 实例应能看到旧数据。"""
    a = LanceDBVectorStore(str(tmp_path / "lance"), table="t", dim=8)
    a.upsert("x", [0.1] * 8, {"namespace": "ns"})

    b = LanceDBVectorStore(str(tmp_path / "lance"), table="t", dim=8)
    assert b.size() == 1
    hits = b.search([0.1] * 8, k=1)
    assert hits[0].id == "x"
