"""稷下学宫单测：SqliteKnowledgeStore + 工具 + 种子。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.capability.tool import ToolCtx
from core.knowledge import Chunk, Source, SqliteKnowledgeStore, Symbol
from core.knowledge.sources import seed_chunks, seed_sources, seed_symbols
from core.tools.knowledge import KnowledgeSearchTool, LookupSymbolTool


@pytest.fixture
def store(tmp_path: Path) -> SqliteKnowledgeStore:
    return SqliteKnowledgeStore(tmp_path / "k.db")


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


# ---------------- 基础读写 ----------------


def test_empty_store_stats(store: SqliteKnowledgeStore) -> None:
    s = store.stats()
    assert s["sources"] == 0
    assert s["chunks"] == 0
    assert s["symbols"] == 0
    assert s["namespaces"] == []


def test_upsert_source_and_list(store: SqliteKnowledgeStore) -> None:
    src = Source(namespace="ns@1", title="T", url="http://x", version="1")
    store.upsert_source(src)
    sources = store.list_sources()
    assert len(sources) == 1
    assert sources[0].title == "T"


def test_upsert_chunks_then_search(store: SqliteKnowledgeStore) -> None:
    chunks = [
        Chunk(
            id="ns@1:a#0",
            namespace="ns@1",
            source_title="T",
            section="a",
            text="QBCore CreateUseableItem 用法示例 water",
        ),
        Chunk(
            id="ns@1:b#0",
            namespace="ns@1",
            source_title="T",
            section="b",
            text="一段无关的文本，不应被命中",
        ),
    ]
    store.upsert_chunks(chunks)
    hits = store.search("CreateUseableItem")
    assert len(hits) == 1
    assert hits[0].chunk.section == "a"


def test_search_namespace_filter(store: SqliteKnowledgeStore) -> None:
    store.upsert_chunks(
        [
            Chunk(id="a@1:c#0", namespace="a@1", source_title="T", text="hello world"),
            Chunk(id="b@1:c#0", namespace="b@1", source_title="T", text="hello world"),
        ],
    )
    hits = store.search("hello", namespaces=["a@1"])
    assert len(hits) == 1
    assert hits[0].chunk.namespace == "a@1"


def test_lookup_symbol_exact_and_fuzzy(store: SqliteKnowledgeStore) -> None:
    store.upsert_symbols(
        [
            Symbol(
                id="ns::QBCore.Functions.GetPlayer",
                namespace="ns",
                name="QBCore.Functions.GetPlayer",
                kind="function",
                side="server",
                summary="get player",
            ),
            Symbol(
                id="ns::Player.Functions.AddItem",
                namespace="ns",
                name="Player.Functions.AddItem",
                kind="function",
                side="server",
                summary="add item",
            ),
        ],
    )
    exact = store.lookup_symbol("QBCore.Functions.GetPlayer")
    assert len(exact) == 1
    fuzzy = store.lookup_symbol("AddItem")
    assert len(fuzzy) == 1
    assert fuzzy[0].name == "Player.Functions.AddItem"


def test_clear_namespace(store: SqliteKnowledgeStore) -> None:
    store.upsert_chunks(
        [Chunk(id="x@1:c#0", namespace="x@1", source_title="T", text="abc")],
    )
    store.upsert_symbols(
        [Symbol(id="x@1::F", namespace="x@1", name="F", kind="function")],
    )
    n = store.clear_namespace("x@1")
    assert n == 1
    assert store.search("abc") == []
    assert store.lookup_symbol("F") == []


# ---------------- FTS5 安全性 ----------------


def test_search_handles_dangerous_input(store: SqliteKnowledgeStore) -> None:
    """用户输入里的 FTS5 元字符不应让 SQLite 报错。"""
    store.upsert_chunks(
        [Chunk(id="ns@1:a#0", namespace="ns@1", source_title="T", text="hello")],
    )
    # 这些字符直接传给 FTS5 MATCH 会语法错；_sanitize_query 应剥离
    for q in ['"', "(*)", "x:y", '"unbalanced', "OR ()", "a-b", ""]:
        # 不应抛出
        store.search(q)


# ---------------- 种子数据 ----------------


def test_seeds_load_and_searchable(store: SqliteKnowledgeStore) -> None:
    for s in seed_sources():
        store.upsert_source(s)
    store.upsert_symbols(seed_symbols())
    store.upsert_chunks(seed_chunks())

    # QBCore CreateUseableItem 必须命中
    hits = store.search("CreateUseableItem")
    assert hits
    assert any("CreateUseableItem" in h.chunk.text or
               (h.matched_symbol and "CreateUseableItem" in h.matched_symbol.name)
               for h in hits)

    # ox_lib callback 必须能查到 symbol
    syms = store.lookup_symbol("lib.callback.register")
    assert syms
    assert syms[0].side == "server"


def test_seeds_include_npc_ai(store: SqliteKnowledgeStore) -> None:
    """种子库必须覆盖 NPC 插件开发常用 API 与模板。"""
    for s in seed_sources():
        store.upsert_source(s)
    store.upsert_symbols(seed_symbols())
    store.upsert_chunks(seed_chunks())

    # native：CreatePed / TaskWanderStandard / SetBlockingOfNonTemporaryEvents
    for native_name in ("CreatePed", "TaskWanderStandard", "SetBlockingOfNonTemporaryEvents"):
        syms = store.lookup_symbol(native_name)
        assert syms, f"种子库缺 {native_name}"

    # 模板：spawn_static_npc / patrol_route / dialogue_tree / behavior_state_machine
    for tpl in (
        "pattern.spawn_static_npc",
        "pattern.patrol_route",
        "pattern.dialogue_tree",
        "pattern.behavior_state_machine",
    ):
        syms = store.lookup_symbol(tpl)
        assert syms, f"种子库缺模板 {tpl}"

    # 概念性 chunk：搜"巡逻 NPC"应命中
    hits = store.search("巡逻 NPC")
    assert hits, "找不到 NPC 巡逻相关 chunk"

    # 命名空间被收录
    namespaces = store.list_namespaces()
    assert "fivem.npc_ai@1.x" in namespaces


# ---------------- 工具适配 ----------------


@pytest.mark.asyncio
async def test_knowledge_search_tool(store: SqliteKnowledgeStore, ctx: ToolCtx) -> None:
    store.upsert_chunks(
        [
            Chunk(
                id="ns@1:a#0",
                namespace="ns@1",
                source_title="T",
                text="QBCore.Functions.CreateUseableItem 注册可使用物品",
            ),
        ],
    )
    store.upsert_symbols(
        [
            Symbol(
                id="ns@1::QBCore.Functions.CreateUseableItem",
                namespace="ns@1",
                name="QBCore.Functions.CreateUseableItem",
                kind="function",
                side="server",
                summary="register a useable item",
            ),
        ],
    )
    tool = KnowledgeSearchTool(store)
    res = await tool.execute({"query": "CreateUseableItem 用法"}, ctx)
    assert res.ok
    assert res.output
    # 锚点 symbol 应能被找到
    assert any(item.get("anchor_symbol") == "QBCore.Functions.CreateUseableItem"
               for item in res.output)


@pytest.mark.asyncio
async def test_lookup_symbol_tool(store: SqliteKnowledgeStore, ctx: ToolCtx) -> None:
    store.upsert_symbols(
        [
            Symbol(
                id="ns::F",
                namespace="ns",
                name="My.Func",
                kind="function",
                signature="My.Func(x) -> y",
                summary="do thing",
                params=[{"name": "x", "type": "number"}],
                example="local r = My.Func(1)",
            ),
        ],
    )
    tool = LookupSymbolTool(store)
    res = await tool.execute({"name": "My.Func"}, ctx)
    assert res.ok
    assert len(res.output) == 1
    assert res.output[0]["signature"] == "My.Func(x) -> y"
    assert res.output[0]["example"]


@pytest.mark.asyncio
async def test_knowledge_search_empty_query_errors(
    store: SqliteKnowledgeStore, ctx: ToolCtx,
) -> None:
    """空 query 应抛 ToolError。"""
    from core.capability.tool import ToolError

    tool = KnowledgeSearchTool(store)
    with pytest.raises(ToolError, match="不能为空"):
        await tool.execute({"query": "  "}, ctx)
