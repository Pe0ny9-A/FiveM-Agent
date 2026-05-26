"""init_project_memory / read_project_memory 工具单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.capability.tool import ToolCtx
from xuanji.persona.project_memory import PROJECT_MEMORY_FILENAME, user_xuanji_md_path
from xuanji.tools.project import (
    InitProjectMemoryTool,
    ReadProjectMemoryTool,
    project_memory_tools,
)


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "cfg"))


def test_factory_returns_two_tools() -> None:
    tools = project_memory_tools()
    names = {t.name for t in tools}
    assert names == {"init_project_memory", "read_project_memory"}


async def test_init_creates_template(tmp_path: Path) -> None:
    tool = InitProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({}, ctx)
    assert result.ok is True
    assert (tmp_path / PROJECT_MEMORY_FILENAME).is_file()
    assert result.extra is not None
    assert result.extra["action"] == "created"
    assert result.extra["had_existing"] is False


async def test_init_refuses_overwrite_by_default(tmp_path: Path) -> None:
    (tmp_path / PROJECT_MEMORY_FILENAME).write_text("旧", encoding="utf-8")
    tool = InitProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({}, ctx)
    assert result.ok is False
    assert "已存在" in (result.error or "")
    # 文件未被覆盖
    assert (tmp_path / PROJECT_MEMORY_FILENAME).read_text(encoding="utf-8") == "旧"


async def test_init_with_overwrite(tmp_path: Path) -> None:
    (tmp_path / PROJECT_MEMORY_FILENAME).write_text("旧", encoding="utf-8")
    tool = InitProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({"overwrite": True}, ctx)
    assert result.ok is True
    assert result.extra is not None
    assert result.extra["action"] == "overwritten"
    text = (tmp_path / PROJECT_MEMORY_FILENAME).read_text(encoding="utf-8")
    assert "玄玑 · 项目记忆" in text


async def test_init_custom_content(tmp_path: Path) -> None:
    tool = InitProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({"content": "# 自定义\n"}, ctx)
    assert result.ok is True
    assert (tmp_path / PROJECT_MEMORY_FILENAME).read_text(encoding="utf-8") == "# 自定义\n"


async def test_read_returns_project_and_user(tmp_path: Path) -> None:
    # user-level
    user_path = user_xuanji_md_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("USER-RULES", encoding="utf-8")
    # project-level
    (tmp_path / PROJECT_MEMORY_FILENAME).write_text("PROJ-RULES", encoding="utf-8")

    tool = ReadProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({}, ctx)
    assert result.ok is True
    assert result.output["project"]["content"] == "PROJ-RULES"
    assert result.output["user"]["content"] == "USER-RULES"
    assert result.extra is not None
    assert result.extra["project_found"] is True
    assert result.extra["user_found"] is True


async def test_read_returns_none_when_absent(tmp_path: Path) -> None:
    tool = ReadProjectMemoryTool()
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")
    result = await tool.execute({}, ctx)
    assert result.ok is True
    assert result.output["project"] is None
    assert result.output["user"] is None
