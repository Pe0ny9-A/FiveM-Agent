"""技能工具：让玄玑创建/搜索/调用技能。

设计原则：
- 技能 = procedural memory，不引入新执行单元
- 写技能 = write_memory(kind=procedural, namespace='skills') 的语义包装
  · 强制带 summary（让 list_skills 看得清）
  · 可在 metadata 里挂"建议工具序列"，未来供合议提示
- 跨 namespace 共享：默认放 'skills'（全局），也可放 'skills.<project>'（项目专属）
- 调用一个技能 = "把技能正文塞进 system prompt 让玄玑按步执行"
  → run_skill 不是真的"执行"，而是返回技能正文 + 建议工具，由玄玑下一轮自己决策
"""

from __future__ import annotations

from typing import Any, ClassVar

from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from core.memory.models import Memory, MemoryKind, MemoryScope
from core.memory.store.base import MemoryStore

SKILLS_NAMESPACE = "skills"
"""技能默认命名空间——跨项目通用。项目专属技能用 'skills.<project>'。"""


class SaveSkillTool(Tool):
    """把一个做事套路保存成可复用技能。"""

    name = "save_skill"
    description = (
        "把一个做事套路（步骤清单 + 注意事项 + 建议调用的工具）保存为技能。"
        "什么是好技能：(1) 跨场景复用，比如「在 QBox 项目里加可使用物品的标准 6 步」；"
        "(2) 把分散的工具调用编成连贯流程；(3) 沉淀一次踩坑的教训。"
        "不要保存：一次性的具体任务、私密信息、过期套路（用 forget 删除）。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "一句话标题，如 '在 ox_inventory 项目里加可使用物品'",
            },
            "steps": {
                "type": "string",
                "description": (
                    "完整步骤正文（markdown），每一步用 1. 2. 3. 编号，"
                    "可在末尾加「注意」「踩过的坑」。"
                ),
            },
            "tools_used": {
                "type": "array",
                "items": {"type": "string"},
                "description": "执行此技能时建议调用的工具名列表，可为空",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签，例如 ['qbcore', 'inventory']",
            },
            "namespace": {
                "type": "string",
                "default": SKILLS_NAMESPACE,
                "description": "默认 'skills' 全局；项目专属用 'skills.<project>'",
            },
            "importance": {"type": "number", "default": 0.7},
        },
        "required": ["summary", "steps"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        summary = (args.get("summary") or "").strip()
        steps = (args.get("steps") or "").strip()
        if not summary or not steps:
            raise ToolError("summary 和 steps 都不能为空")
        ns = args.get("namespace") or SKILLS_NAMESPACE
        importance = max(0.0, min(1.0, float(args.get("importance", 0.7))))

        m = Memory(
            scope=MemoryScope.USER,  # 技能是跨项目的偏好级资产
            kind=MemoryKind.PROCEDURAL,
            namespace=ns,
            text=steps,
            summary=summary,
            importance=importance,
            tags=list(args.get("tags") or []),
            metadata={"tools_used": list(args.get("tools_used") or [])},
        )
        saved = self._store.write(m)
        return ToolResult(
            ok=True,
            output={
                "id": saved.id,
                "summary": saved.summary,
                "namespace": saved.namespace,
                "tools_used": saved.metadata.get("tools_used", []),
            },
        )


class SearchSkillTool(Tool):
    """按关键词搜索技能。"""

    name = "search_skill"
    description = (
        "按关键词搜索技能（procedural memory）。"
        "比 list_skills 更聚焦——遇到一个新任务时先用它找有没有现成套路，再决定是用技能还是直接动手。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "namespace": {
                "type": "string",
                "description": f"默认全局 '{SKILLS_NAMESPACE}'；项目专属传 'skills.<project>'",
            },
            "k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            raise ToolError("query 不能为空")
        ns = args.get("namespace") or SKILLS_NAMESPACE
        hits = self._store.recall(
            query,
            kinds=[MemoryKind.PROCEDURAL],
            namespace=ns,
            k=int(args.get("k", 5)),
        )
        out = [
            {
                "id": m.id[:8],
                "summary": m.summary or m.text[:100],
                "tags": m.tags,
                "tools_used": m.metadata.get("tools_used", []),
                "importance": round(m.importance, 2),
                "hits": m.hits,
            }
            for m in hits
        ]
        return ToolResult(ok=True, output=out, extra={"namespace": ns, "count": len(out)})


class RunSkillTool(Tool):
    """读取一个技能的完整内容并展开。"""

    name = "run_skill"
    description = (
        "「执行」一个技能——展开它的完整步骤与建议工具，让玄玑按步骤自己决策。"
        "注意：玄玑不会替你跑工具，而是把技能正文展示出来，下一轮你按内容调用对应工具。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "技能 id 前缀（≥6 位）或全名"},
        },
        "required": ["id"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        sid = args["id"]
        m = self._store.get(sid)
        if m is None:
            for cand in self._store.list_by_namespace(
                SKILLS_NAMESPACE,
                kinds=[MemoryKind.PROCEDURAL],
                limit=200,
            ):
                if cand.id.startswith(sid):
                    m = cand
                    break
        if m is None or m.kind != MemoryKind.PROCEDURAL:
            return ToolResult(ok=False, error=f"找不到技能：{sid}")

        return ToolResult(
            ok=True,
            output={
                "id": m.id,
                "summary": m.summary,
                "steps": m.text,
                "tools_used": m.metadata.get("tools_used", []),
                "tags": m.tags,
            },
        )


def skill_tools(store: MemoryStore) -> list[Tool]:
    return [SaveSkillTool(store), SearchSkillTool(store), RunSkillTool(store)]


__all__ = [
    "SKILLS_NAMESPACE",
    "RunSkillTool",
    "SaveSkillTool",
    "SearchSkillTool",
    "skill_tools",
]
