"""项目级记忆 XUANJI.md 单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.persona.project_memory import (
    PROJECT_MEMORY_FILENAME,
    collect_xuanji_fragments,
    find_project_xuanji_md,
    init_project_xuanji_md,
    load_project_xuanji_md,
    load_user_xuanji_md,
    render_default_template,
    user_xuanji_md_path,
)


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "cfg"))


def test_find_project_md_walks_up_tree(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    (root / PROJECT_MEMORY_FILENAME).write_text("# 项目宪法", encoding="utf-8")

    found = find_project_xuanji_md(sub)
    assert found is not None
    assert found.parent == root


def test_find_project_md_returns_none_when_absent(tmp_path: Path) -> None:
    sub = tmp_path / "alone"
    sub.mkdir()
    assert find_project_xuanji_md(sub) is None


def test_load_project_md_returns_path_and_text(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / PROJECT_MEMORY_FILENAME).write_text("hello world", encoding="utf-8")

    result = load_project_xuanji_md(root)
    assert result is not None
    path, text = result
    assert path == root / PROJECT_MEMORY_FILENAME
    assert text == "hello world"


def test_load_project_md_treats_empty_as_missing(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / PROJECT_MEMORY_FILENAME).write_text("   \n  \n", encoding="utf-8")
    assert load_project_xuanji_md(root) is None


def test_user_md_round_trip(tmp_path: Path) -> None:
    p = user_xuanji_md_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("用户偏好", encoding="utf-8")
    assert load_user_xuanji_md() == "用户偏好"


def test_collect_user_then_project_order(tmp_path: Path) -> None:
    """合成顺序：用户级在前，项目级在后（项目级权重高）。"""
    user_path = user_xuanji_md_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("USER-RULE", encoding="utf-8")

    proj = tmp_path / "myproj"
    proj.mkdir()
    (proj / PROJECT_MEMORY_FILENAME).write_text("PROJ-RULE", encoding="utf-8")

    fragments = collect_xuanji_fragments(proj)
    assert len(fragments) == 2
    assert "USER-RULE" in fragments[0]
    assert "用户级" in fragments[0]
    assert "PROJ-RULE" in fragments[1]
    assert "项目级" in fragments[1]


def test_collect_returns_empty_when_nothing(tmp_path: Path) -> None:
    sub = tmp_path / "alone"
    sub.mkdir()
    assert collect_xuanji_fragments(sub) == []


def test_init_creates_default_template(tmp_path: Path) -> None:
    root = tmp_path / "newproj"
    root.mkdir()
    path, created = init_project_xuanji_md(root)
    assert created is True
    assert path == root / PROJECT_MEMORY_FILENAME
    text = path.read_text(encoding="utf-8")
    assert "玄玑 · 项目记忆" in text
    assert "newproj" in text


def test_init_refuses_existing_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / PROJECT_MEMORY_FILENAME).write_text("旧内容", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_project_xuanji_md(root)
    # 旧内容必须仍在
    assert (root / PROJECT_MEMORY_FILENAME).read_text(encoding="utf-8") == "旧内容"


def test_init_overwrite_replaces(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / PROJECT_MEMORY_FILENAME).write_text("旧内容", encoding="utf-8")
    path, created = init_project_xuanji_md(root, overwrite=True)
    assert created is False  # 不是"created"——是"overwritten"
    assert "玄玑 · 项目记忆" in path.read_text(encoding="utf-8")


def test_init_with_custom_content(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    path, _ = init_project_xuanji_md(root, content="# 自定义内容\n")
    assert path.read_text(encoding="utf-8") == "# 自定义内容\n"


def test_render_default_template_substitutes_fields() -> None:
    text = render_default_template(
        "demo-resource",
        framework="qbox",
        inventory="ox_inventory",
        target="ox_target",
    )
    assert "demo-resource" in text
    assert "qbox" in text
    assert "ox_inventory" in text
    assert "ox_target" in text
