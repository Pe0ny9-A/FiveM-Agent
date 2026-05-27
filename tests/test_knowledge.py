"""稷下学宫单测：SqliteKnowledgeStore + 工具 + 种子。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.capability.tool import ToolCtx
from xuanji.knowledge import Chunk, Source, SqliteKnowledgeStore, Symbol
from xuanji.knowledge.sources import seed_chunks, seed_sources, seed_symbols
from xuanji.tools.knowledge import KnowledgeSearchTool, LookupSymbolTool


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


def test_search_symbols_by_prefix_basic(store: SqliteKnowledgeStore) -> None:
    """前缀搜索：用于 IDE 内联补全。"""
    store.upsert_symbols(
        [
            Symbol(
                id="qb::QBCore.Functions.GetPlayer",
                namespace="fivem.qbcore@1.x",
                name="QBCore.Functions.GetPlayer",
                kind="function",
                side="server",
            ),
            Symbol(
                id="qb::QBCore.Functions.GetPlayers",
                namespace="fivem.qbcore@1.x",
                name="QBCore.Functions.GetPlayers",
                kind="function",
                side="server",
            ),
            Symbol(
                id="qb::QBCore.Functions.CreateUseableItem",
                namespace="fivem.qbcore@1.x",
                name="QBCore.Functions.CreateUseableItem",
                kind="function",
                side="server",
            ),
            Symbol(
                id="ox::lib.callback.register",
                namespace="fivem.ox_lib@3.x",
                name="lib.callback.register",
                kind="function",
                side="any",
            ),
        ],
    )
    # 前缀命中 QBCore.Functions.Get*
    hits = store.search_symbols_by_prefix("QBCore.Functions.Get")
    names = sorted(h.name for h in hits)
    assert names == ["QBCore.Functions.GetPlayer", "QBCore.Functions.GetPlayers"]

    # 大小写不敏感
    hits = store.search_symbols_by_prefix("qbcore.functions.create")
    assert len(hits) == 1
    assert hits[0].name == "QBCore.Functions.CreateUseableItem"

    # namespace 过滤
    hits = store.search_symbols_by_prefix(
        "lib.", namespaces=["fivem.ox_lib@3.x"],
    )
    assert len(hits) == 1
    assert hits[0].name == "lib.callback.register"

    hits = store.search_symbols_by_prefix(
        "lib.", namespaces=["fivem.qbcore@1.x"],
    )
    assert hits == []

    # 空 prefix 不打全表
    assert store.search_symbols_by_prefix("") == []


def test_search_symbols_by_prefix_kind_and_limit(
    store: SqliteKnowledgeStore,
) -> None:
    store.upsert_symbols(
        [
            Symbol(
                id="ns::Foo",
                namespace="ns",
                name="Foo",
                kind="function",
            ),
            Symbol(
                id="ns::FooEvent",
                namespace="ns",
                name="FooEvent",
                kind="event",
            ),
            Symbol(
                id="ns::FooExport",
                namespace="ns",
                name="FooExport",
                kind="export",
            ),
        ],
    )
    # kind 过滤
    only_events = store.search_symbols_by_prefix("Foo", kinds=["event"])
    assert [s.name for s in only_events] == ["FooEvent"]
    # limit
    capped = store.search_symbols_by_prefix("Foo", limit=2)
    assert len(capped) == 2


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


def test_seeds_include_qbox_esx_oxmysql_natives(store: SqliteKnowledgeStore) -> None:
    """1.2.0-C：扩源后 QBox/ESX/oxmysql/natives 四个命名空间齐了。"""
    for s in seed_sources():
        store.upsert_source(s)
    store.upsert_symbols(seed_symbols())
    store.upsert_chunks(seed_chunks())

    # 新增四个命名空间各自有 symbol
    namespaces = store.list_namespaces()
    for ns in ("fivem.qbox@main", "fivem.esx@1.13", "fivem.oxmysql@2.x", "fivem.natives@latest"):
        assert ns in namespaces, f"种子缺命名空间 {ns}"

    # QBox：核心 export 能查到
    assert store.lookup_symbol("exports.qbx_core:GetPlayer")
    # ESX：xPlayer 取法 + 注册可使用物品
    assert store.lookup_symbol("ESX.GetPlayerFromId")
    assert store.lookup_symbol("ESX.RegisterUsableItem")
    # oxmysql：query / transaction
    assert store.lookup_symbol("MySQL.query")
    assert store.lookup_symbol("MySQL.transaction")
    # natives：高频几个
    for n in ("PlayerPedId", "GetEntityCoords", "RegisterNetEvent", "TriggerServerEvent"):
        assert store.lookup_symbol(n), f"种子缺 native {n}"

    # 概念性 chunk：搜"框架选" / "占位符" 应命中扩源新写的 chunk
    assert store.search("QBCore QBox 迁移") or store.search("QBox 迁移")
    assert store.search("oxmysql ? 占位符") or store.search("oxmysql 占位符")


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
    from xuanji.capability.tool import ToolError

    tool = KnowledgeSearchTool(store)
    with pytest.raises(ToolError, match="不能为空"):
        await tool.execute({"query": "  "}, ctx)
