"""Skills 子系统单测：parse_skill / SkillsLoader / 三个工具。

不引入额外 fixture，用 tmp_path 即可。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.capability.tool import ToolCtx
from xuanji.skills import SkillParseError, SkillsLoader, parse_skill
from xuanji.tools.skill_files import (
    ListSkillFilesTool,
    MatchSkillFileTool,
    ReadSkillFileTool,
    skill_file_tools,
)

SKILL_VALID = """\
---
name: qbox-add-item
description: 在 QBox 项目里加一个可使用物品的标准步骤
triggers:
  - QBox
  - useable item
  - 可使用物品
tools:
  - read_file
  - write_file
allowed_tools:
  - read_file
  - write_file
metadata:
  xuanji:
    mode: dev
    role_hint: 百工匠
    risk_floor: io
  custom:
    author: 小宝
---

# 步骤

1. 打开 fxmanifest.lua
2. 在 shared_scripts 里加上 useable item 注册
3. 验证：进游戏 /useitem testitem
"""

SKILL_NO_FRONTMATTER = """\
# 没有 frontmatter
就是一段 markdown
"""

SKILL_BAD_YAML = """\
---
name: bad
triggers: [unclosed
---

正文
"""

SKILL_NOT_MAPPING = """\
---
- just
- a
- list
---

正文
"""

SKILL_MIN = """\
---
name: minimal
description: 最小可用 skill
---

仅 name + description
"""


def test_parse_skill_valid(tmp_path: Path) -> None:
    p = tmp_path / "qbox.md"
    p.write_text(SKILL_VALID, encoding="utf-8")
    skill = parse_skill(p)
    assert skill.name == "qbox-add-item"
    assert "QBox" in skill.frontmatter.triggers
    assert "可使用物品" in skill.frontmatter.triggers
    assert skill.frontmatter.allowed_tools == ["read_file", "write_file"]
    assert skill.frontmatter.xuanji.mode == "dev"
    assert skill.frontmatter.xuanji.role_hint == "百工匠"
    assert skill.frontmatter.xuanji.risk_floor == "io"
    assert "fxmanifest.lua" in skill.body


def test_parse_skill_minimal(tmp_path: Path) -> None:
    p = tmp_path / "min.md"
    p.write_text(SKILL_MIN, encoding="utf-8")
    skill = parse_skill(p)
    assert skill.name == "minimal"
    assert skill.frontmatter.triggers == []
    assert skill.frontmatter.xuanji.mode is None


def test_parse_skill_no_frontmatter_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(SKILL_NO_FRONTMATTER, encoding="utf-8")
    with pytest.raises(SkillParseError, match="frontmatter"):
        parse_skill(p)


def test_parse_skill_bad_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(SKILL_BAD_YAML, encoding="utf-8")
    with pytest.raises(SkillParseError, match="YAML"):
        parse_skill(p)


def test_parse_skill_root_not_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(SKILL_NOT_MAPPING, encoding="utf-8")
    with pytest.raises(SkillParseError, match="mapping"):
        parse_skill(p)


def test_skills_loader_lists_and_caches(tmp_path: Path) -> None:
    (tmp_path / "qbox.md").write_text(SKILL_VALID, encoding="utf-8")
    (tmp_path / "min.md").write_text(SKILL_MIN, encoding="utf-8")
    loader = SkillsLoader(tmp_path)
    skills = loader.all()
    assert {s.name for s in skills} == {"qbox-add-item", "minimal"}
    # 第二次调用应命中缓存（mtime 没变）
    skills2 = loader.all()
    assert len(skills2) == 2


def test_skills_loader_picks_up_changes(tmp_path: Path) -> None:
    f = tmp_path / "qbox.md"
    f.write_text(SKILL_VALID, encoding="utf-8")
    loader = SkillsLoader(tmp_path)
    assert loader.get("qbox-add-item") is not None

    # 修改并改 mtime
    f.write_text(SKILL_MIN, encoding="utf-8")
    import os
    import time
    os.utime(f, (time.time() + 1, time.time() + 1))
    assert loader.get("qbox-add-item") is None
    assert loader.get("minimal") is not None


def test_skills_loader_collects_errors(tmp_path: Path) -> None:
    (tmp_path / "good.md").write_text(SKILL_VALID, encoding="utf-8")
    (tmp_path / "broken.md").write_text(SKILL_BAD_YAML, encoding="utf-8")
    loader = SkillsLoader(tmp_path)
    skills = loader.all()
    assert len(skills) == 1
    assert skills[0].name == "qbox-add-item"
    errors = loader.errors()
    assert any("broken.md" in k for k in errors)


def test_skills_loader_match(tmp_path: Path) -> None:
    (tmp_path / "qbox.md").write_text(SKILL_VALID, encoding="utf-8")
    loader = SkillsLoader(tmp_path)
    hits = loader.match("我想在 QBox 里加个物品")
    assert len(hits) == 1
    assert hits[0].name == "qbox-add-item"
    # 不命中
    hits2 = loader.match("nothing matches")
    assert hits2 == []


def test_skills_loader_handles_missing_dir(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path / "doesnt-exist")
    assert loader.all() == []


def _ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.mark.asyncio
async def test_list_skill_files_tool(tmp_path: Path) -> None:
    (tmp_path / "qbox.md").write_text(SKILL_VALID, encoding="utf-8")
    tools = skill_file_tools(tmp_path)
    list_tool = next(t for t in tools if isinstance(t, ListSkillFilesTool))
    res = await list_tool.execute({}, _ctx(tmp_path))
    assert res.ok
    assert len(res.output) == 1
    assert res.output[0]["name"] == "qbox-add-item"
    assert "QBox" in res.output[0]["triggers"]


@pytest.mark.asyncio
async def test_read_skill_file_tool(tmp_path: Path) -> None:
    (tmp_path / "qbox.md").write_text(SKILL_VALID, encoding="utf-8")
    tools = skill_file_tools(tmp_path)
    read_tool = next(t for t in tools if isinstance(t, ReadSkillFileTool))
    res = await read_tool.execute({"name": "qbox-add-item"}, _ctx(tmp_path))
    assert res.ok
    assert "fxmanifest.lua" in res.output["body"]
    assert res.output["metadata"]["xuanji"]["mode"] == "dev"


@pytest.mark.asyncio
async def test_read_skill_file_tool_unknown_raises(tmp_path: Path) -> None:
    from xuanji.capability.tool import ToolError
    tools = skill_file_tools(tmp_path)
    read_tool = next(t for t in tools if isinstance(t, ReadSkillFileTool))
    with pytest.raises(ToolError, match="找不到"):
        await read_tool.execute({"name": "ghost"}, _ctx(tmp_path))


@pytest.mark.asyncio
async def test_match_skill_file_tool(tmp_path: Path) -> None:
    (tmp_path / "qbox.md").write_text(SKILL_VALID, encoding="utf-8")
    tools = skill_file_tools(tmp_path)
    match_tool = next(t for t in tools if isinstance(t, MatchSkillFileTool))
    res = await match_tool.execute({"query": "QBox 项目里搞物品"}, _ctx(tmp_path))
    assert res.ok
    assert len(res.output) == 1
    assert "QBox" in res.output[0]["matched_triggers"]
