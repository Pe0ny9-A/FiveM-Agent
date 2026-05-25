"""自演化工具集单测：meta / memory / ingest / skills / factory。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.capability.registry import ToolRegistry
from core.capability.tool import RiskTag, ToolCtx, ToolError
from core.knowledge.store.sqlite_fts import SqliteKnowledgeStore
from core.memory.models import Memory, MemoryKind, MemoryScope
from core.memory.store.sqlite import SqliteMemoryStore
from core.tools import builtin_tools
from core.tools.factory import ProposeToolTool
from core.tools.ingest import (
    IngestFileTool,
    IngestTextTool,
    UpsertSymbolTool,
    ingest_tools_offline,
)
from core.tools.ingest_url import html_to_markdown
from core.tools.knowledge import knowledge_tools
from core.tools.memory import RecallMemoryTool, WriteMemoryTool
from core.tools.meta import (
    DescribeToolTool,
    ListSkillsTool,
    ListToolsTool,
    ReadSkillTool,
    meta_tools,
)
from core.tools.skills import (
    SKILLS_NAMESPACE,
    RunSkillTool,
    SaveSkillTool,
    SearchSkillTool,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.fixture
def kstore(tmp_path: Path) -> SqliteKnowledgeStore:
    return SqliteKnowledgeStore(tmp_path / "k.db")


@pytest.fixture
def mstore(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(tmp_path / "m.db")


# ---------------- meta tools ----------------


@pytest.mark.asyncio
async def test_list_tools_returns_all(mstore: SqliteMemoryStore, ctx: ToolCtx) -> None:
    """list_tools 应能看到所有已注册的工具，包括它自己。"""
    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    registry.register_all(meta_tools(registry, mstore))
    tool = ListToolsTool(registry)

    res = await tool.execute({}, ctx)
    assert res.ok
    names = {item["name"] for item in res.output}
    assert "read_file" in names
    assert "list_tools" in names  # 自察自己也在列表里


@pytest.mark.asyncio
async def test_list_tools_filter_by_risk(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    tool = ListToolsTool(registry)
    res = await tool.execute({"filter_risk": "exec"}, ctx)
    assert res.ok
    names = {item["name"] for item in res.output}
    assert "run_shell" in names
    assert "read_file" not in names


@pytest.mark.asyncio
async def test_describe_tool_returns_schema(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    tool = DescribeToolTool(registry)
    res = await tool.execute({"name": "read_file"}, ctx)
    assert res.ok
    assert res.output["name"] == "read_file"
    assert res.output["risk"] == "safe"
    assert "path" in res.output["schema"]["properties"]


@pytest.mark.asyncio
async def test_describe_tool_unknown(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    tool = DescribeToolTool(ToolRegistry())
    res = await tool.execute({"name": "ghost"}, ctx)
    assert not res.ok
    assert "不存在" in (res.error or "")


@pytest.mark.asyncio
async def test_list_and_read_skill_round_trip(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    """save_skill → list_skills → read_skill 闭环。"""
    save = SaveSkillTool(mstore)
    res = await save.execute(
        {
            "summary": "在 ox_inventory 项目里加可使用物品",
            "steps": "1. items.lua 加配置\n2. server.export\n3. 测试",
            "tools_used": ["write_file", "ripgrep"],
            "tags": ["ox_inventory"],
        },
        ctx,
    )
    assert res.ok
    sid = res.output["id"]

    listed = await ListSkillsTool(mstore).execute({}, ctx)
    assert listed.ok
    assert any(s["id"] in sid for s in listed.output)

    read = await ReadSkillTool(mstore).execute({"id": sid[:8]}, ctx)
    assert read.ok
    assert "items.lua" in read.output["text"]
    assert read.output["scope"] == "user"


# ---------------- memory tools ----------------


@pytest.mark.asyncio
async def test_write_memory_persists(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    tool = WriteMemoryTool(mstore, "proj")
    res = await tool.execute(
        {"text": "项目用 QBox 不是 QBCore", "kind": "semantic", "importance": 0.85},
        ctx,
    )
    assert res.ok
    listed = mstore.list_by_namespace("proj", kinds=[MemoryKind.SEMANTIC])
    assert len(listed) == 1
    assert listed[0].importance == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_write_memory_rejects_working_scope(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    """working 不在合法 scope 列表里，应抛 ToolError。"""
    tool = WriteMemoryTool(mstore, "proj")
    with pytest.raises(ToolError, match="scope"):
        await tool.execute({"text": "x", "scope": "working"}, ctx)


@pytest.mark.asyncio
async def test_write_memory_clamps_importance(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    """importance 越界应被 clamp 到 [0, 1]。"""
    tool = WriteMemoryTool(mstore, "proj")
    res = await tool.execute({"text": "x", "importance": 5.0}, ctx)
    assert res.ok
    assert res.output["importance"] == 1.0


@pytest.mark.asyncio
async def test_recall_memory_filters_by_kind(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    mstore.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
               namespace="proj", text="alpha-fact"),
    )
    mstore.write(
        Memory(scope=MemoryScope.PROJECT, kind=MemoryKind.PROCEDURAL,
               namespace="proj", text="alpha-skill"),
    )
    tool = RecallMemoryTool(mstore, "proj")
    res = await tool.execute({"query": "alpha", "kinds": ["semantic"]}, ctx)
    assert res.ok
    kinds = {m["kind"] for m in res.output}
    assert kinds == {"semantic"}


# ---------------- ingest tools ----------------


@pytest.mark.asyncio
async def test_ingest_text_writes_chunks(
    kstore: SqliteKnowledgeStore, ctx: ToolCtx,
) -> None:
    tool = IngestTextTool(kstore)
    md = (
        "# 标题\n\n"
        "这是一段示例。\n\n"
        "## 子章节\n\n"
        "里面提到 lib.callback.register 怎么用。"
    )
    res = await tool.execute(
        {
            "namespace": "user.demo@1",
            "source_title": "演示笔记",
            "text": md,
        },
        ctx,
    )
    assert res.ok
    assert res.output["chunks_written"] >= 1
    hits = kstore.search("lib.callback.register")
    assert hits


@pytest.mark.asyncio
async def test_ingest_file_reads_and_chunks(
    kstore: SqliteKnowledgeStore, ctx: ToolCtx, tmp_path: Path,
) -> None:
    md = "# Doc\n\n关于 ox_target 的笔记。\n\n## 用法\n\nlib.target...\n"
    f = tmp_path / "notes.md"
    f.write_text(md, encoding="utf-8")
    tool = IngestFileTool(kstore)
    res = await tool.execute({"path": "notes.md", "namespace": "user.demo@1"}, ctx)
    assert res.ok
    assert res.output["chunks_written"] >= 1
    hits = kstore.search("ox_target")
    assert hits


@pytest.mark.asyncio
async def test_upsert_symbol_then_lookup(
    kstore: SqliteKnowledgeStore, ctx: ToolCtx,
) -> None:
    tool = UpsertSymbolTool(kstore)
    res = await tool.execute(
        {
            "namespace": "user.demo@1",
            "name": "MyApi.DoStuff",
            "kind": "function",
            "side": "server",
            "signature": "MyApi.DoStuff(x) -> y",
            "summary": "示例 API",
        },
        ctx,
    )
    assert res.ok
    syms = kstore.lookup_symbol("MyApi.DoStuff")
    assert syms
    assert syms[0].signature == "MyApi.DoStuff(x) -> y"


def test_ingest_tools_offline_factory(kstore: SqliteKnowledgeStore) -> None:
    tools = ingest_tools_offline(kstore)
    names = {t.name for t in tools}
    assert names == {"ingest_text", "ingest_file", "upsert_symbol"}
    # 都是 SAFE 风险，不会触发 HITL
    for t in tools:
        assert t.risk == RiskTag.SAFE


# ---------------- ingest_url 解析 ----------------


def test_html_to_markdown_basic() -> None:
    html = (
        "<html><head><title>Hello</title></head>"
        "<body><h1>Title</h1><p>some text</p>"
        "<pre><code>local x = 1</code></pre>"
        "<ul><li>a</li><li>b</li></ul></body></html>"
    )
    title, md = html_to_markdown(html)
    assert title == "Hello"
    assert "# Title" in md
    assert "some text" in md
    assert "```" in md
    assert "local x = 1" in md
    assert "- a" in md
    assert "- b" in md


def test_html_to_markdown_strips_scripts() -> None:
    html = "<body><script>alert('xss')</script><p>safe</p></body>"
    _, md = html_to_markdown(html)
    assert "alert" not in md
    assert "safe" in md


# ---------------- skill tools ----------------


@pytest.mark.asyncio
async def test_save_then_search_skill(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    save = SaveSkillTool(mstore)
    await save.execute(
        {
            "summary": "在 QBox 项目里加可使用物品",
            "steps": "1. items.lua 加配置\n2. ...\n3. 测试",
            "tools_used": ["read_file", "write_file"],
            "tags": ["qbox"],
        },
        ctx,
    )

    # 中文短语在 unicode61 tokenizer 下检索不稳定（M3+ 接 jieba 解决）；
    # 这里用英文/混合 token 验证检索通路通畅
    search = SearchSkillTool(mstore)
    res = await search.execute({"query": "QBox items.lua"}, ctx)
    assert res.ok
    assert len(res.output) == 1
    assert res.output[0]["tools_used"] == ["read_file", "write_file"]


@pytest.mark.asyncio
async def test_run_skill_returns_full_steps(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    save = SaveSkillTool(mstore)
    saved = await save.execute(
        {
            "summary": "测试技能",
            "steps": "step A\nstep B",
            "tools_used": ["foo"],
        },
        ctx,
    )
    sid = saved.output["id"]

    run = RunSkillTool(mstore)
    res = await run.execute({"id": sid[:6]}, ctx)
    assert res.ok
    assert "step A" in res.output["steps"]
    assert res.output["tools_used"] == ["foo"]


@pytest.mark.asyncio
async def test_search_skill_only_in_skills_namespace(
    mstore: SqliteMemoryStore, ctx: ToolCtx,
) -> None:
    """write_memory 写到 'proj' 不应被 search_skill 命中（默认 skills namespace）。"""
    mstore.write(
        Memory(
            scope=MemoryScope.PROJECT,
            kind=MemoryKind.PROCEDURAL,
            namespace="proj",
            text="不是 skills 命名空间",
        ),
    )
    res = await SearchSkillTool(mstore).execute({"query": "不是"}, ctx)
    assert res.ok
    assert res.output == []


def test_skills_namespace_constant() -> None:
    assert SKILLS_NAMESPACE == "skills"


# ---------------- factory · propose_tool ----------------


@pytest.mark.asyncio
async def test_propose_tool_writes_draft(tmp_path: Path, ctx: ToolCtx) -> None:
    drafts = tmp_path / "drafts"
    tool = ProposeToolTool(drafts)
    res = await tool.execute(
        {
            "name": "lint_lua_resource",
            "description": "对一个 FiveM resource 跑 luacheck",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "rationale": "没有现成工具能跑 luacheck，run_shell 太宽泛",
            "risk": "exec",
        },
        ctx,
    )
    assert res.ok
    saved_path = Path(res.output["draft_path"])
    assert saved_path.exists()
    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert data["status"] == "draft"
    assert data["risk"] == "exec"
    assert data["name"] == "lint_lua_resource"


@pytest.mark.asyncio
async def test_propose_tool_rejects_bad_name(tmp_path: Path, ctx: ToolCtx) -> None:
    tool = ProposeToolTool(tmp_path)
    with pytest.raises(ToolError, match="snake_case"):
        await tool.execute(
            {
                "name": "Bad-Name!",
                "description": "x",
                "input_schema": {"type": "object"},
                "rationale": "y",
            },
            ctx,
        )


@pytest.mark.asyncio
async def test_propose_tool_rejects_non_object_schema(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    tool = ProposeToolTool(tmp_path)
    with pytest.raises(ToolError, match="JSONSchema"):
        await tool.execute(
            {
                "name": "ok_name",
                "description": "x",
                "input_schema": {"type": "string"},  # 非 object
                "rationale": "y",
            },
            ctx,
        )


# ---------------- 集成：所有工具不冲突注册 ----------------


def test_all_evolve_tools_register_without_conflict(
    kstore: SqliteKnowledgeStore, mstore: SqliteMemoryStore, tmp_path: Path,
) -> None:
    """复刻 chat loop 的注入顺序，确认没有名字冲突。"""
    from core.tools import (
        ingest_tools_offline,
        memory_tools,
        skill_tools,
        tool_factory_tools,
    )
    from core.tools.ingest_url import IngestUrlTool

    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    registry.register_all(knowledge_tools(kstore))
    registry.register_all(ingest_tools_offline(kstore))
    registry.register(IngestUrlTool(kstore))
    registry.register_all(memory_tools(mstore, "proj"))
    registry.register_all(skill_tools(mstore))
    registry.register_all(tool_factory_tools(tmp_path))
    registry.register_all(meta_tools(registry, mstore))

    names = registry.names()
    assert len(names) == len(set(names))
    # 关键 evolve 工具都在
    for must in [
        "list_tools", "describe_tool", "list_skills", "read_skill",
        "recall_memory", "write_memory",
        "ingest_text", "ingest_file", "upsert_symbol", "ingest_url",
        "save_skill", "search_skill", "run_skill",
        "propose_tool",
    ]:
        assert must in names, f"缺工具：{must}"
