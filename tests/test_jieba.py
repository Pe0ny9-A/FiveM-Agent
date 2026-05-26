"""中文分词集成回归测试。

验证 jieba 接入后，中文短语检索从"整段命中"扩展到"按词命中"——
解决 0.2.0 之前 unicode61 单字 token 与查询 phrase 不对齐的问题。
"""

from __future__ import annotations

from pathlib import Path

from core.knowledge import Chunk, SqliteKnowledgeStore
from core.knowledge.tokenize import is_jieba_available, preprocess_text
from core.memory.models import Memory, MemoryKind, MemoryScope
from core.memory.store.sqlite import SqliteMemoryStore


def test_jieba_available_in_test_env() -> None:
    """开发环境必须能用 jieba（pyproject.toml 里是 required dep）。"""
    assert is_jieba_available()


def test_preprocess_inserts_spaces_in_chinese() -> None:
    out = preprocess_text("可使用物品 测试")
    # jieba 切分后应至少有 3 段空格分隔（"可使用 物品" + "测试"）
    parts = out.split()
    assert len(parts) >= 3


def test_preprocess_keeps_english_intact() -> None:
    out = preprocess_text("Lookup QBCore.Functions.GetPlayer")
    assert "QBCore.Functions.GetPlayer" in out


def test_preprocess_passes_through_empty() -> None:
    assert preprocess_text("") == ""
    assert preprocess_text("   ") == "   "


def test_chinese_phrase_search_in_knowledge(tmp_path: Path) -> None:
    """知识库里写中文，按词检索能命中——回归 0.2.0 之前的问题。"""
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    store.upsert_chunks(
        [
            Chunk(
                id="ns@1:c#0",
                namespace="ns@1",
                source_title="T",
                text="QBCore 的可使用物品需要先 CreateUseableItem 注册",
            ),
        ],
    )
    # 用「物品」单词检索（jieba 会把"可使用物品"切成"可使用 物品"）
    hits = store.search("物品")
    assert hits, "中文词检索应命中"
    # 完整短语也应命中
    hits2 = store.search("可使用物品")
    assert hits2


def test_chinese_phrase_search_in_memory(tmp_path: Path) -> None:
    """记忆库的中文检索同样应按词召回。"""
    store = SqliteMemoryStore(tmp_path / "m.db")
    store.write(
        Memory(
            scope=MemoryScope.PROJECT,
            kind=MemoryKind.SEMANTIC,
            namespace="proj",
            text="本项目用 QBox 框架而非 QBCore，注意可使用物品要走 ox_inventory 的 server.export",
            importance=0.8,
        ),
    )
    # 单词查
    assert store.recall("物品", namespace="proj")
    assert store.recall("可使用", namespace="proj")
    assert store.recall("QBox", namespace="proj")
    # 多词查
    assert store.recall("ox_inventory 物品", namespace="proj")


def test_skill_chinese_search_now_works(tmp_path: Path) -> None:
    """0.2.0 失败的 'test_save_then_search_skill' 中文 query 现在应 work。"""
    import asyncio

    from core.capability.tool import ToolCtx
    from core.tools.skills import SaveSkillTool, SearchSkillTool

    store = SqliteMemoryStore(tmp_path / "m.db")
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")

    asyncio.run(
        SaveSkillTool(store).execute(
            {
                "summary": "在 QBox 项目里加可使用物品",
                "steps": "1. items.lua 加配置\n2. server.export\n3. 测试",
                "tools_used": ["read_file", "write_file"],
                "tags": ["qbox"],
            },
            ctx,
        )
    )

    res = asyncio.run(
        SearchSkillTool(store).execute({"query": "可使用物品"}, ctx)
    )
    assert res.ok
    assert len(res.output) >= 1, "中文短语查技能现在应该能命中"


def test_update_chunk_keeps_fts_in_sync(tmp_path: Path) -> None:
    """同 id 重写后 FTS5 不应残留旧文本。"""
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    store.upsert_chunks(
        [
            Chunk(
                id="ns@1:c#0",
                namespace="ns@1",
                source_title="T",
                text="原始内容关于 QBCore 框架",
            ),
        ],
    )
    assert store.search("QBCore")
    # 改写
    store.upsert_chunks(
        [
            Chunk(
                id="ns@1:c#0",
                namespace="ns@1",
                source_title="T",
                text="新内容关于 QBox 框架",
            ),
        ],
    )
    assert not store.search("QBCore"), "旧 FTS5 条目没清掉"
    assert store.search("QBox")


def test_clear_namespace_purges_fts(tmp_path: Path) -> None:
    store = SqliteKnowledgeStore(tmp_path / "k.db")
    store.upsert_chunks(
        [
            Chunk(id="a:1#0", namespace="a", source_title="T", text="alpha 关键词"),
            Chunk(id="b:1#0", namespace="b", source_title="T", text="alpha 关键词"),
        ],
    )
    n = store.clear_namespace("a")
    assert n == 1
    hits = store.search("关键词")
    namespaces = {h.chunk.namespace for h in hits}
    assert namespaces == {"b"}, f"a 应被清掉，剩 {namespaces}"


def test_memory_forget_purges_fts(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db")
    store.write(
        Memory(
            scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
            namespace="proj", text="待删的中文内容",
        ),
    )
    assert store.recall("中文")
    store.forget(namespace="proj")
    # FTS5 应同步清空
    assert not store.recall("中文")
