"""5 个原子工具的单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.body.sandbox import InProcSandbox
from xuanji.capability.tool import ToolCtx
from xuanji.tools.builtin import (
    ListDirTool,
    ReadFileTool,
    RipgrepTool,
    RunShellTool,
    WriteFileTool,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s1", trace_id="t1")


# ----------- read_file -----------


@pytest.mark.asyncio
async def test_read_file_returns_content(tmp_path: Path, ctx: ToolCtx) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("姐姐在", encoding="utf-8")
    result = await ReadFileTool().execute({"path": "hello.txt"}, ctx)
    assert result.ok
    assert result.output == "姐姐在"


@pytest.mark.asyncio
async def test_read_file_missing_raises(ctx: ToolCtx) -> None:
    sandbox = InProcSandbox()
    out = await sandbox.run(ReadFileTool(), {"path": "nope.txt"}, ctx)
    assert not out.ok
    assert "不存在" in (out.error or "")


# ----------- write_file -----------


@pytest.mark.asyncio
async def test_write_file_creates_dirs_and_writes(tmp_path: Path, ctx: ToolCtx) -> None:
    result = await WriteFileTool().execute(
        {"path": "sub/dir/out.txt", "content": "玄玑在"}, ctx
    )
    assert result.ok
    assert (tmp_path / "sub" / "dir" / "out.txt").read_text(encoding="utf-8") == "玄玑在"


# ----------- list_dir -----------


@pytest.mark.asyncio
async def test_list_dir_returns_entries(tmp_path: Path, ctx: ToolCtx) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    result = await ListDirTool().execute({"path": "."}, ctx)
    assert result.ok
    names = {e["name"] for e in result.output}
    assert "a.txt" in names
    assert "sub" in names


# ----------- ripgrep -----------


@pytest.mark.asyncio
async def test_ripgrep_finds_lines(tmp_path: Path, ctx: ToolCtx) -> None:
    (tmp_path / "a.lua").write_text(
        "QBCore.Functions.CreateUseableItem('water', cb)\nlocal x = 1\n",
        encoding="utf-8",
    )
    result = await RipgrepTool().execute(
        {"pattern": r"CreateUseableItem", "glob": "*.lua"}, ctx
    )
    assert result.ok
    assert len(result.output) == 1
    assert result.output[0]["line"] == 1
    assert "CreateUseableItem" in result.output[0]["text"]


@pytest.mark.asyncio
async def test_ripgrep_invalid_regex_errors(ctx: ToolCtx) -> None:
    sandbox = InProcSandbox()
    out = await sandbox.run(RipgrepTool(), {"pattern": "(unclosed"}, ctx)
    assert not out.ok
    assert "正则" in (out.error or "")


# ----------- run_shell -----------


@pytest.mark.asyncio
async def test_run_shell_echo(tmp_path: Path, ctx: ToolCtx) -> None:
    """跨平台的最小烟雾测试。echo 在 cmd 与 sh 下行为一致。"""
    result = await RunShellTool().execute(
        {"command": "echo hello", "timeout_sec": 5}, ctx
    )
    assert result.ok
    assert "hello" in result.output["stdout"]
    assert result.output["exit_code"] == 0
