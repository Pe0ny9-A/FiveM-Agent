"""元工具：玄玑自察自管。

让玄玑通过工具调用看见自己——已有什么工具/技能、各工具的 schema、当前 session 状态。
没有这些工具，玄玑不知道自己有什么能力，也就谈不上"用工具去补足缺口"的自演化循环。

设计要点：
- 都是 RiskTag.SAFE，零副作用
- 输出格式精简，避免吃掉模型上下文
- ListSkillsTool / ReadSkillTool 在阶段 E 接 procedural memory 后自动有内容
"""

from __future__ import annotations

from typing import Any, ClassVar

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.memory.models import MemoryKind, MemoryScope
from xuanji.memory.store.base import MemoryStore


class ListToolsTool(Tool):
    """列出当前注册的所有工具。"""

    name = "list_tools"
    description = (
        "列出玄玑当前可用的所有工具，含名字、风险等级、一句话描述。"
        "在动手前先用它确认有没有现成工具能用，避免重复造轮子或自己写 shell。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "filter_risk": {
                "type": "string",
                "enum": ["safe", "io", "exec", "net", "destructive"],
                "description": "可选：仅列出某个风险等级的工具",
            },
        },
    }

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        risk_filter = args.get("filter_risk")
        items: list[dict[str, Any]] = []
        for t in self._registry.all():
            if risk_filter and t.risk.value != risk_filter:
                continue
            items.append(
                {
                    "name": t.name,
                    "risk": t.risk.value,
                    "description": (t.description or "").strip().replace("\n", " ")[:200],
                },
            )
        return ToolResult(ok=True, output=items, extra={"count": len(items)})


class DescribeToolTool(Tool):
    """查看某个工具的完整 schema 与描述。"""

    name = "describe_tool"
    description = (
        "查看指定工具的完整 JSONSchema、描述、风险等级。"
        "在调用一个不熟的工具前用它看清参数结构。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "工具名"},
        },
        "required": ["name"],
    }

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name = args.get("name")
        if not name:
            raise ToolError("name 不能为空")
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"工具不存在：{name}")
        return ToolResult(
            ok=True,
            output={
                "name": tool.name,
                "version": tool.version,
                "description": tool.description,
                "risk": tool.risk.value,
                "schema": tool.schema,
            },
        )


class ListSkillsTool(Tool):
    """列出当前可用技能（procedural memory）。"""

    name = "list_skills"
    description = (
        "列出玄玑学到的可复用技能（procedural 记忆）——这些是「做某类事的套路」，"
        "比如「在 QBox 项目里加可使用物品的标准步骤」「对话树离线生成 → 落 lua → 接 ox_target」。"
        "做新任务前先看看有没有匹配的技能。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "命名空间过滤；不填则看全局通用技能",
            },
            "limit": {"type": "integer", "default": 50},
        },
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        namespace = args.get("namespace") or "skills"
        limit = int(args.get("limit", 50))
        items = self._store.list_by_namespace(
            namespace,
            kinds=[MemoryKind.PROCEDURAL],
            limit=limit,
        )
        out = [
            {
                "id": m.id[:8],
                "summary": m.summary or m.text[:80],
                "tags": m.tags,
                "importance": round(m.importance, 2),
                "hits": m.hits,
            }
            for m in items
        ]
        return ToolResult(ok=True, output=out, extra={"namespace": namespace, "count": len(out)})


class ReadSkillTool(Tool):
    """读取一个技能的完整正文。"""

    name = "read_skill"
    description = "按 id 前缀或全名读取一个技能的完整内容（步骤、引用的工具、注意事项）。"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "技能的 id 前缀（至少 6 位）或完整 id"},
        },
        "required": ["id"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        sid = args["id"]
        # 先尝试精确
        m = self._store.get(sid)
        if m is None:
            # 模糊：在 skills namespace 找前缀匹配
            for cand in self._store.list_by_namespace(
                "skills",
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
                "text": m.text,
                "tags": m.tags,
                "metadata": m.metadata,
                "namespace": m.namespace,
                "scope": m.scope.value,
            },
        )


def meta_tools(registry: ToolRegistry, memory: MemoryStore) -> list[Tool]:
    """工厂：返回所有元工具实例。

    registry 必须传入"最终注册满"的实例，否则 list_tools 看不到自己。
    """
    return [
        ListToolsTool(registry),
        DescribeToolTool(registry),
        ListSkillsTool(memory),
        ReadSkillTool(memory),
    ]


__all__ = [
    "DescribeToolTool",
    "ListSkillsTool",
    "ListToolsTool",
    "MemoryScope",  # 给 CLI 复用
    "ReadSkillTool",
    "meta_tools",
]
