"""Skills 文件系统工具：list_skill_files / read_skill_file / match_skill_file。

这套工具操作 `data_dir() / "skills" / *.md` ——markdown + YAML frontmatter，
与 Claude Code / Codex 的 skills 目录互通。

跟 xuanji.tools.skills 里基于 procedural memory 的 list_skills/run_skill 是两回事：
- 那套是玄玑「学到的套路」，跑在 SQLite 记忆库里
- 这套是文件系统里的「技能卡片」，可双向跟 CC/Codex 迁移
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.skills import SkillsLoader


class _LoaderHolder:
    """共享 loader：同一个进程多个工具实例不要各扫各的。"""

    def __init__(self, root: Path) -> None:
        self.loader = SkillsLoader(root)


class ListSkillFilesTool(Tool):
    """列出 skills 目录里的所有 markdown skill 文件。"""

    name = "list_skill_files"
    description = (
        "列出 skills 目录下的所有 markdown skill 文件（与 Claude Code / Codex 互通格式）。"
        "返回每个 skill 的 name / description / triggers / 路径。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, holder: _LoaderHolder) -> None:
        self._holder = holder

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        skills = self._holder.loader.all()
        return ToolResult(
            ok=True,
            output=[
                {
                    "name": s.name,
                    "description": s.frontmatter.description,
                    "triggers": s.frontmatter.triggers,
                    "path": str(s.path),
                    "tools": s.frontmatter.tools,
                    "allowed_tools": s.frontmatter.allowed_tools,
                }
                for s in skills
            ],
            extra={
                "count": len(skills),
                "errors": self._holder.loader.errors(),
                "root": str(self._holder.loader.root),
            },
        )


class ReadSkillFileTool(Tool):
    """读取单个 skill 的 frontmatter + body。"""

    name = "read_skill_file"
    description = "读取指定 skill 文件的 frontmatter 与 markdown 正文。"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "skill 名（frontmatter.name）"},
        },
        "required": ["name"],
    }

    def __init__(self, holder: _LoaderHolder) -> None:
        self._holder = holder

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name = args["name"]
        skill = self._holder.loader.get(name)
        if skill is None:
            raise ToolError(f"找不到名为 {name!r} 的 skill")
        return ToolResult(
            ok=True,
            output={
                "name": skill.name,
                "description": skill.frontmatter.description,
                "triggers": skill.frontmatter.triggers,
                "tools": skill.frontmatter.tools,
                "allowed_tools": skill.frontmatter.allowed_tools,
                "metadata": skill.frontmatter.metadata,
                "body": skill.body,
                "path": str(skill.path),
            },
        )


class MatchSkillFileTool(Tool):
    """按 query 子串匹配 triggers，返回命中的 skills。"""

    name = "match_skill_file"
    description = (
        "在 skills 目录里查 triggers 命中 query 子串的 skill。"
        "用于「拿到用户输入后先看看有没有现成的 skill 卡片可注入」。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户输入或主题关键词"},
        },
        "required": ["query"],
    }

    def __init__(self, holder: _LoaderHolder) -> None:
        self._holder = holder

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        hits = self._holder.loader.match(args["query"])
        return ToolResult(
            ok=True,
            output=[
                {
                    "name": s.name,
                    "description": s.frontmatter.description,
                    "matched_triggers": [
                        t for t in s.frontmatter.triggers
                        if t.lower() in args["query"].lower()
                    ],
                }
                for s in hits
            ],
            extra={"count": len(hits)},
        )


def skill_file_tools(skills_root: Path) -> list[Tool]:
    """工厂：返回三件套，所有实例共享同一个 loader。"""
    holder = _LoaderHolder(skills_root)
    return [
        ListSkillFilesTool(holder),
        ReadSkillFileTool(holder),
        MatchSkillFileTool(holder),
    ]


__all__ = [
    "ListSkillFilesTool",
    "MatchSkillFileTool",
    "ReadSkillFileTool",
    "skill_file_tools",
]
