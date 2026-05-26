"""项目级记忆工具：让玄玑读写 XUANJI.md。

两个工具：
- `read_project_memory`：查询当前项目根 XUANJI.md（也包含用户级）
- `init_project_memory`：在当前 cwd 写一份 XUANJI.md 模板

写入是 RiskTag.IO，覆盖既有文件需 overwrite=True 才允许，
否则交给 Gate 拦——再加上模型幻觉时也只能在工程根目录里改这一个文件。
"""

from __future__ import annotations

from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from xuanji.persona.project_memory import (
    PROJECT_MEMORY_FILENAME,
    find_project_xuanji_md,
    init_project_xuanji_md,
    load_project_xuanji_md,
    load_user_xuanji_md,
    user_xuanji_md_path,
)


class ReadProjectMemoryTool(Tool):
    """查询当前项目级 + 用户级 XUANJI.md。"""

    name = "read_project_memory"
    description = (
        "读取当前项目根的 XUANJI.md 和用户级 XUANJI.md，返回原文与路径。"
        "玄玑在回答前若拿不准项目约定，可以先调它确认有没有项目宪法。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        out: dict[str, Any] = {"project": None, "user": None}
        proj = load_project_xuanji_md(ctx.project_root)
        if proj is not None:
            path, text = proj
            out["project"] = {"path": str(path), "content": text}
        user_text = load_user_xuanji_md()
        if user_text is not None:
            out["user"] = {"path": str(user_xuanji_md_path()), "content": user_text}
        return ToolResult(
            ok=True,
            output=out,
            extra={
                "project_found": out["project"] is not None,
                "user_found": out["user"] is not None,
            },
        )


class InitProjectMemoryTool(Tool):
    """在当前工程根写一份 XUANJI.md 项目记忆模板。"""

    name = "init_project_memory"
    description = (
        f"在当前工程根创建 {PROJECT_MEMORY_FILENAME}（项目级记忆/规则文件）。"
        "玄玑在熟悉一个新项目时主动调用它，根据 detector 结果填好 framework/inventory/target，"
        "之后再补充关键约定和禁区。覆盖既有文件需 overwrite=true。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "overwrite": {
                "type": "boolean",
                "description": "若 XUANJI.md 已存在，是否覆盖。默认 false，已存在时返回 ok=False。",
                "default": False,
            },
            "content": {
                "type": "string",
                "description": "完整自定义内容；不传则用 detector 结果填默认模板",
            },
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        overwrite = bool(args.get("overwrite", False))
        content = args.get("content")
        already = find_project_xuanji_md(ctx.project_root) is not None
        try:
            path, created = init_project_xuanji_md(
                ctx.project_root,
                overwrite=overwrite,
                content=content,
            )
        except FileExistsError as e:
            return ToolResult(ok=False, error=str(e))
        action = "created" if created else "overwritten"
        return ToolResult(
            ok=True,
            output=f"{action}: {path}",
            extra={
                "path": str(path),
                "action": action,
                "had_existing": already,
            },
        )


def project_memory_tools() -> list[Tool]:
    return [
        ReadProjectMemoryTool(),
        InitProjectMemoryTool(),
    ]


__all__ = [
    "InitProjectMemoryTool",
    "ReadProjectMemoryTool",
    "project_memory_tools",
]
