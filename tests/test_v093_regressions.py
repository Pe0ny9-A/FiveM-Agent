"""v0.9.3 修的几个 bug 的回归单测。

- Bug #3：多轮 tool loop 复读 → _PrefixDedup 兜底
- Bug #4：流式 args 残缺 → require_str / require_dict 友好错误
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from xuanji.capability.tool import ToolCtx
from xuanji.neural.conductor import _PrefixDedup
from xuanji.tools._args import require_dict, require_str
from xuanji.tools.builtin import ReadFileTool, WriteFileTool
from xuanji.tools.ingest import IngestTextTool, UpsertSymbolTool
from xuanji.tools.meta import DescribeToolTool

# ============== _PrefixDedup ==============


def test_prefix_dedup_no_ref_passes_through() -> None:
    """没有上一轮文本时全透传。"""
    d = _PrefixDedup("")
    assert d.feed("hello") == "hello"
    assert d.feed(" world") == " world"


def test_prefix_dedup_full_repeat_eats_everything() -> None:
    """整段复读上一轮时全部吞掉。"""
    ref = "姐姐扫一眼就明白。"
    d = _PrefixDedup(ref)
    out = ""
    for ch in ref:
        out += d.feed(ch)
    assert out == ""


def test_prefix_dedup_partial_repeat_then_new_content() -> None:
    """前面是上一轮开场白，后面接新内容——只吐新部分。"""
    ref = "姐姐扫一眼就明白。"
    d = _PrefixDedup(ref)
    out = ""
    for ch in ref:
        out += d.feed(ch)
    out += d.feed("接下来翻文件。")
    assert "姐姐扫一眼就明白" not in out
    assert "接下来翻文件" in out


def test_prefix_dedup_diverges_early() -> None:
    """从一开始就不同——之前吃下的那段要 flush 出来 + 后面透传。"""
    d = _PrefixDedup("我先看看")
    out = ""
    out += d.feed("我先")  # 仍是 ref 前缀，吃掉
    out += d.feed("说一下")  # 这里偏离 ref
    out += d.feed("我的判断")  # 透传
    # "我先" 是共同前缀 → 应该被去掉
    # "说一下" 是 buf 中超出 ref 的尾段
    assert out.startswith("说一下")
    assert "我的判断" in out


# ============== require_str / require_dict ==============


def test_require_str_missing_returns_friendly_error() -> None:
    """Bug #4 核心：args 残缺不抛 KeyError。"""
    raw, err = require_str({}, "path")
    assert raw is None
    assert err is not None
    assert err.ok is False
    assert "path" in (err.error or "")


def test_require_str_null_value_rejected() -> None:
    raw, err = require_str({"path": None}, "path")
    assert raw is None
    assert err is not None
    assert err.ok is False


def test_require_str_wrong_type_rejected() -> None:
    raw, err = require_str({"path": 123}, "path")
    assert raw is None
    assert err is not None
    assert "字符串" in (err.error or "")


def test_require_str_empty_default_rejected() -> None:
    raw, err = require_str({"path": ""}, "path")
    assert raw is None
    assert err is not None


def test_require_str_empty_allowed() -> None:
    raw, err = require_str({"content": ""}, "content", allow_empty=True)
    assert err is None
    assert raw == ""


def test_require_dict_missing() -> None:
    raw, err = require_dict({}, "obj")
    assert raw is None
    assert err is not None and err.ok is False


def test_require_dict_wrong_type() -> None:
    raw, err = require_dict({"obj": []}, "obj")
    assert raw is None
    assert err is not None


def test_require_dict_ok() -> None:
    raw, err = require_dict({"obj": {"a": 1}}, "obj")
    assert err is None
    assert raw == {"a": 1}


# ============== 工具调用流式残缺 → 友好错误（端到端） ==============


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.mark.asyncio
async def test_read_file_empty_args_no_keyerror(ctx: ToolCtx) -> None:
    """模拟 DeepSeek 流截断：args 是空 dict。绝不抛 KeyError。"""
    tool = ReadFileTool()
    res = await tool.execute({}, ctx)
    assert res.ok is False
    assert "path" in (res.error or "")


@pytest.mark.asyncio
async def test_write_file_empty_args_no_keyerror(ctx: ToolCtx) -> None:
    tool = WriteFileTool()
    res = await tool.execute({}, ctx)
    assert res.ok is False
    # path 缺时 path 错误优先
    assert "path" in (res.error or "")


@pytest.mark.asyncio
async def test_write_file_only_path_no_keyerror(
    ctx: ToolCtx, tmp_path: Path,
) -> None:
    """只给了 path 没给 content——content 缺也是友好错误。"""
    tool = WriteFileTool()
    res = await tool.execute({"path": str(tmp_path / "a.txt")}, ctx)
    assert res.ok is False
    assert "content" in (res.error or "")


@pytest.mark.asyncio
async def test_write_file_empty_content_allowed(
    ctx: ToolCtx, tmp_path: Path,
) -> None:
    """空文件是合法用法 → 不应被拒绝。"""
    tool = WriteFileTool()
    target = tmp_path / "empty.txt"
    res = await tool.execute({"path": str(target), "content": ""}, ctx)
    assert res.ok
    assert target.exists()
    assert target.read_text() == ""


@pytest.mark.asyncio
async def test_ingest_text_empty_args(ctx: ToolCtx) -> None:
    class _DummyStore:
        def upsert_chunks(self, chunks: list[Any]) -> None:
            pass

        def upsert_source(self, source: Any) -> None:
            pass

    tool = IngestTextTool(_DummyStore())  # type: ignore[arg-type]
    res = await tool.execute({}, ctx)
    assert res.ok is False


@pytest.mark.asyncio
async def test_upsert_symbol_empty_args(ctx: ToolCtx) -> None:
    class _DummyStore:
        def upsert_symbols(self, symbols: list[Any]) -> None:
            pass

    tool = UpsertSymbolTool(_DummyStore())  # type: ignore[arg-type]
    res = await tool.execute({}, ctx)
    assert res.ok is False


@pytest.mark.asyncio
async def test_describe_tool_missing_name(ctx: ToolCtx) -> None:
    """Bug #4 之前会抛 ToolError。"""
    from xuanji.capability.registry import ToolRegistry

    tool = DescribeToolTool(ToolRegistry())
    res = await tool.execute({}, ctx)
    assert res.ok is False
    assert "name" in (res.error or "")
