"""ToolFactory 闭环单测。

覆盖：
- FactoryRegistry SQLite CRUD（upsert/get/all）
- ToolFactory.list_drafts / load_draft
- _extract_blocks 切两段代码块
- ToolFactory.test 跑通过 / 跑失败两条路径
- ToolFactory.publish 在 tested 状态门控
- ToolFactory.reject 直接打死
- published_loader 扫到一份发布过的代码并实例化

不接 LLM——generate 步骤直接 monkey 替换，落 staged 文件后跑 test 验证。
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

import pytest

from xuanji.tools.published_loader import load_published_tools
from xuanji.tools.tool_factory import (
    FactoryRegistry,
    FactoryStatus,
    ToolFactory,
    _extract_blocks,
)

# ---------------- _extract_blocks ----------------


def test_extract_blocks_splits_two_segments() -> None:
    text = textwrap.dedent(
        """\
        随便一段引子。
        ```python:tool
        class A: pass
        ```
        中间废话。
        ```python:test
        def test_a(): assert True
        ```
        结束。
        """
    )
    tool, test = _extract_blocks(text)
    assert "class A" in tool
    assert "def test_a" in test


def test_extract_blocks_returns_empty_when_missing() -> None:
    tool, test = _extract_blocks("没有任何代码块")
    assert tool == ""
    assert test == ""


# ---------------- FactoryRegistry ----------------


def test_registry_roundtrip(tmp_path: Path) -> None:
    reg = FactoryRegistry(tmp_path / "f.db")
    st = FactoryStatus(slug="ping", status="draft", updated_at=time.time())
    reg.upsert(st)
    got = reg.get("ping")
    assert got is not None
    assert got.slug == "ping"
    assert got.status == "draft"
    assert reg.get("nope") is None
    assert len(reg.all()) == 1


def test_registry_upsert_overwrites_status(tmp_path: Path) -> None:
    reg = FactoryRegistry(tmp_path / "f.db")
    reg.upsert(FactoryStatus(slug="x", status="draft"))
    reg.upsert(FactoryStatus(slug="x", status="generated", code_path=Path("/tmp/x.py")))
    got = reg.get("x")
    assert got is not None
    assert got.status == "generated"
    assert got.code_path == Path("/tmp/x.py")


# ---------------- ToolFactory test/publish/reject ----------------


def _make_factory(tmp_path: Path) -> ToolFactory:
    return ToolFactory(
        drafts_dir=tmp_path / "drafts",
        staged_dir=tmp_path / "staged",
        published_dir=tmp_path / "published",
        registry=FactoryRegistry(tmp_path / "f.db"),
    )


def _seed_draft(factory: ToolFactory, slug: str = "echo_tool") -> None:
    factory.drafts_dir.mkdir(parents=True, exist_ok=True)
    (factory.drafts_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "name": slug,
                "description": "echo back the args",
                "risk": "safe",
                "input_schema": {"type": "object", "properties": {}},
                "rationale": "demo",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _stage_passing(factory: ToolFactory, slug: str) -> None:
    """直接落 staged 文件，模拟 generate 步骤已完成。"""
    code = "RESULT = 42\n"
    code_path = factory.staged_dir / f"{slug}.py"
    test_path = factory.staged_dir / f"test_{slug}.py"
    # test 用 importlib 直接 import 同目录的 .py 文件——避免依赖项目内 import 路径
    test_src = (
        f"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\n"
        f"from {slug} import RESULT\n\ndef test_ok():\n    assert RESULT == 42\n"
    )
    code_path.write_text(code, encoding="utf-8")
    test_path.write_text(test_src, encoding="utf-8")
    factory.registry.upsert(
        FactoryStatus(
            slug=slug,
            status="generated",
            draft_path=factory.drafts_dir / f"{slug}.json",
            code_path=code_path,
            test_path=test_path,
            updated_at=time.time(),
        )
    )


def _stage_failing(factory: ToolFactory, slug: str) -> None:
    code = "RESULT = 0\n"
    test_src = (
        f"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\n"
        f"from {slug} import RESULT\n\ndef test_ok():\n    assert RESULT == 999\n"
    )
    code_path = factory.staged_dir / f"{slug}.py"
    test_path = factory.staged_dir / f"test_{slug}.py"
    code_path.write_text(code, encoding="utf-8")
    test_path.write_text(test_src, encoding="utf-8")
    factory.registry.upsert(
        FactoryStatus(
            slug=slug,
            status="generated",
            draft_path=factory.drafts_dir / f"{slug}.json",
            code_path=code_path,
            test_path=test_path,
            updated_at=time.time(),
        )
    )


def test_list_drafts_finds_files(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    _seed_draft(factory, "a")
    _seed_draft(factory, "b")
    drafts = factory.list_drafts()
    assert {p.stem for p in drafts} == {"a", "b"}


def test_load_draft_missing_raises(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    with pytest.raises(FileNotFoundError):
        factory.load_draft("nope")


def test_test_passing_marks_tested(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    slug = "echo_tool"
    _seed_draft(factory, slug)
    _stage_passing(factory, slug)
    status = factory.test(slug, timeout_sec=30.0)
    assert status.last_test_passed is True
    assert status.status == "tested"


def test_test_failing_keeps_generated(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    slug = "broken_tool"
    _seed_draft(factory, slug)
    _stage_failing(factory, slug)
    status = factory.test(slug, timeout_sec=30.0)
    assert status.last_test_passed is False
    assert status.status == "generated"


def test_test_without_generate_raises(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    with pytest.raises(FileNotFoundError):
        factory.test("never_generated")


def test_publish_requires_tested(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    slug = "echo_tool"
    _seed_draft(factory, slug)
    _stage_passing(factory, slug)
    # 还没跑 test 就 publish——应被拒
    with pytest.raises(ValueError, match=r"未通过|未跑"):
        factory.publish(slug)


def test_publish_after_tested_copies_file(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    slug = "echo_tool"
    _seed_draft(factory, slug)
    _stage_passing(factory, slug)
    factory.test(slug, timeout_sec=30.0)
    status = factory.publish(slug)
    assert status.status == "published"
    assert (factory.published_dir / f"{slug}.py").exists()


def test_reject_marks_status(tmp_path: Path) -> None:
    factory = _make_factory(tmp_path)
    slug = "echo_tool"
    _seed_draft(factory, slug)
    _stage_passing(factory, slug)
    status = factory.reject(slug, reason="不合 schema")
    assert status.status == "rejected"
    assert "rejected" in status.last_test_output


# ---------------- published_loader ----------------


_PUBLISHED_TOOL_SRC = '''\
"""测试用：一个最小可用 Tool 子类。"""

from __future__ import annotations

from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult


class EchoPublishedTool(Tool):
    name = "echo_published"
    description = "测试用 echo 工具"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output={"echo": args.get("text", "")})
'''


def test_load_published_tools_discovers_subclass(tmp_path: Path) -> None:
    published = tmp_path / "published"
    published.mkdir()
    (published / "echo_published.py").write_text(_PUBLISHED_TOOL_SRC, encoding="utf-8")
    tools = load_published_tools(published)
    assert len(tools) == 1
    assert tools[0].name == "echo_published"
    assert tools[0].risk.value == "safe"


def test_load_published_tools_skips_broken_files(tmp_path: Path) -> None:
    published = tmp_path / "published"
    published.mkdir()
    (published / "good.py").write_text(
        _PUBLISHED_TOOL_SRC.replace("EchoPublishedTool", "GoodTool").replace(
            'name = "echo_published"', 'name = "good_tool"'
        ),
        encoding="utf-8",
    )
    (published / "broken.py").write_text("this is not python !!!\n", encoding="utf-8")
    tools = load_published_tools(published)
    # broken 跳过，good 加载成功
    names = [t.name for t in tools]
    assert names == ["good_tool"]


def test_load_published_tools_empty_dir(tmp_path: Path) -> None:
    assert load_published_tools(tmp_path / "no_such_dir") == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert load_published_tools(empty) == []


def test_load_published_tools_skips_underscore_files(tmp_path: Path) -> None:
    published = tmp_path / "published"
    published.mkdir()
    (published / "__init__.py").write_text("", encoding="utf-8")
    (published / "_private.py").write_text(_PUBLISHED_TOOL_SRC, encoding="utf-8")
    assert load_published_tools(published) == []


# ---------------- 端到端：publish 后 loader 能发现 ----------------


def test_publish_then_loader_finds_it(tmp_path: Path) -> None:
    """模拟一次完整闭环：seed → stage → test → publish → load_published。"""
    factory = _make_factory(tmp_path)
    slug = "tiny_published"
    _seed_draft(factory, slug)
    # 真 staged 文件用 Tool 子类，test 文件用 import 检验
    code_path = factory.staged_dir / f"{slug}.py"
    test_path = factory.staged_dir / f"test_{slug}.py"
    code_path.write_text(
        _PUBLISHED_TOOL_SRC.replace("EchoPublishedTool", "TinyPublishedTool")
        .replace('name = "echo_published"', 'name = "tiny_published"'),
        encoding="utf-8",
    )
    test_path.write_text(
        f"import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, str(Path(__file__).parent))\n"
        f"from {slug} import TinyPublishedTool\n\n"
        f"def test_class_exists():\n    assert TinyPublishedTool.name == 'tiny_published'\n",
        encoding="utf-8",
    )
    factory.registry.upsert(
        FactoryStatus(
            slug=slug,
            status="generated",
            draft_path=factory.drafts_dir / f"{slug}.json",
            code_path=code_path,
            test_path=test_path,
            updated_at=time.time(),
        )
    )
    factory.test(slug, timeout_sec=30.0)
    factory.publish(slug)

    # publish 后 loader 应能从 published_dir 发现这个工具
    tools = load_published_tools(factory.published_dir)
    assert any(t.name == "tiny_published" for t in tools)
