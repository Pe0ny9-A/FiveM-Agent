"""propose_tool：玄玑提出新工具草案，落到磁盘等小宝 review。

**安全底线**：玄玑永远不能让代码自动 publish。本工具只产出 JSON 草案到
`<data_dir>/tool_drafts/<slug>.json`，由小宝读后人工实现 Python 代码并注册。

未来 M4 的 ToolFactory 会接 LLM 生成实现 → 单测 → review → published 完整流水线，
但即便那时也是"模型写代码 → 落沙箱单测 → 模型不能自己 publish"。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, ClassVar

from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult


def _slug(text: str) -> str:
    s = re.sub(r"[^\w]+", "_", text.strip(), flags=re.UNICODE)
    return s.strip("_").lower()[:60] or "untitled"


class ProposeToolTool(Tool):
    """玄玑提出新工具草案，落到磁盘等小宝实现。"""

    name = "propose_tool"
    description = (
        "玄玑发现现有工具不够用时，可调本工具产出新工具草案——但**不会自动实现**。"
        "草案是一份 JSON 文件，含工具名、描述、参数 schema、风险等级、设计理由。"
        "小宝读后决定要不要写成真正的 Python 工具。这是玄玑工具进化的安全入口。"
        "调用前先用 list_tools 确认现有工具确实没有等价能力，避免重复提案。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "建议工具名，snake_case，例如 'lint_lua_resource'",
            },
            "description": {
                "type": "string",
                "description": "工具描述，告诉以后的 LLM 何时用它",
            },
            "input_schema": {
                "type": "object",
                "description": "完整 JSONSchema，参数定义",
            },
            "risk": {
                "type": "string",
                "enum": ["safe", "io", "exec", "net", "destructive"],
                "default": "safe",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "为什么需要这个工具？现有工具为什么不够？"
                    "（小宝 review 时会重点看这一段）"
                ),
            },
            "example_calls": {
                "type": "array",
                "items": {"type": "object"},
                "description": "1-3 个示例调用（args 对象），帮小宝理解使用场景",
            },
        },
        "required": ["name", "description", "input_schema", "rationale"],
    }

    def __init__(self, drafts_dir: Path) -> None:
        self._drafts_dir = drafts_dir

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]{1,62}", name):
            raise ToolError(
                f"工具名必须是 snake_case (字母/数字/下划线，2~63 字符)：{name!r}"
            )
        description = (args.get("description") or "").strip()
        rationale = (args.get("rationale") or "").strip()
        if not description or not rationale:
            raise ToolError("description 与 rationale 都不能为空")

        risk = args.get("risk", "safe")
        schema = args.get("input_schema") or {}
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ToolError("input_schema 必须是 type=object 的 JSONSchema 对象")

        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        draft = {
            "name": name,
            "description": description,
            "risk": risk,
            "input_schema": schema,
            "rationale": rationale,
            "example_calls": list(args.get("example_calls") or []),
            "proposed_at": time.time(),
            "session_id": ctx.session_id,
            "trace_id": ctx.trace_id,
            "status": "draft",
        }
        path = self._drafts_dir / f"{_slug(name)}.json"
        path.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return ToolResult(
            ok=True,
            output={
                "draft_path": str(path),
                "name": name,
                "status": "saved-as-draft",
                "next_step": (
                    "小宝可用 'xuanji tool drafts' 查看；"
                    "review 通过后人工实现并加到 ToolRegistry。"
                ),
            },
        )


def tool_factory_tools(drafts_dir: Path) -> list[Tool]:
    return [ProposeToolTool(drafts_dir)]


__all__ = ["ProposeToolTool", "tool_factory_tools"]
