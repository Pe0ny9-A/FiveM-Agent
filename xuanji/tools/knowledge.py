"""稷下学宫工具：knowledge_search / lookup_symbol。

设计：
- 这两个工具持有同一个 KnowledgeStore，通过工厂在 ToolRegistry 注入时绑定
- 没有副作用 → risk=SAFE，直接放行
- 输出做了精简（裁剪文本长度），避免巨量内容撑爆 LLM 上下文
"""

from __future__ import annotations

from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.knowledge.store.base import KnowledgeStore

_TEXT_PREVIEW_LEN = 600


def _trim(s: str, n: int = _TEXT_PREVIEW_LEN) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "…"


class KnowledgeSearchTool(Tool):
    """全文检索 FiveM 知识库。"""

    name = "knowledge_search"
    description = (
        "在 FiveM 知识库（QBCore/ox_lib/ox_inventory/cfx 等命名空间）"
        "做全文检索，返回相关文本片段与命中的 API 卡片锚点。"
        "查询时尽量带上具体关键词（如 'CreateUseableItem ox_inventory'）。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索查询，可以是问题或关键词"},
            "namespaces": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "命名空间过滤，例如 ['fivem.qbcore@1.x']。"
                    "不填则跨全部命名空间检索。"
                ),
            },
            "k": {"type": "integer", "description": "返回 top-k，默认 5", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            raise ToolError("query 不能为空")
        namespaces = args.get("namespaces")
        k = int(args.get("k", 5))
        hits = self._store.search(query, namespaces=namespaces, k=k)

        out: list[dict[str, Any]] = []
        for h in hits:
            item: dict[str, Any] = {
                "namespace": h.chunk.namespace,
                "source": h.chunk.source_title,
                "section": h.chunk.section,
                "score": round(h.score, 3),
                "text": _trim(h.chunk.text),
            }
            if h.chunk.url:
                item["url"] = h.chunk.url
            if h.matched_symbol:
                item["anchor_symbol"] = h.matched_symbol.name
            out.append(item)

        return ToolResult(
            ok=True,
            output=out,
            extra={
                "query": query,
                "namespaces": namespaces,
                "count": len(out),
            },
        )


class LookupSymbolTool(Tool):
    """精准查询 API/事件/native 卡片。"""

    name = "lookup_symbol"
    description = (
        "按全限定名（如 'QBCore.Functions.CreateUseableItem'）精准查询 API 卡片，"
        "返回签名、参数、说明、示例。前缀模糊也支持。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Symbol 全限定名或片段，例如 'CreateUseableItem' 或 'lib.callback.register'",
            },
            "namespaces": {
                "type": "array",
                "items": {"type": "string"},
                "description": "命名空间过滤，不填则跨全部",
            },
        },
        "required": ["name"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            raise ToolError("name 不能为空")
        namespaces = args.get("namespaces")
        symbols = self._store.lookup_symbol(name, namespaces=namespaces)

        out: list[dict[str, Any]] = []
        for s in symbols:
            item: dict[str, Any] = {
                "namespace": s.namespace,
                "name": s.name,
                "kind": s.kind,
                "side": s.side,
            }
            if s.signature:
                item["signature"] = s.signature
            if s.summary:
                item["summary"] = s.summary
            if s.params:
                item["params"] = s.params
            if s.returns:
                item["returns"] = s.returns
            if s.example:
                item["example"] = _trim(s.example, 1200)
            if s.url:
                item["url"] = s.url
            out.append(item)

        return ToolResult(
            ok=True,
            output=out,
            extra={"query": name, "count": len(out)},
        )


def knowledge_tools(store: KnowledgeStore) -> list[Tool]:
    """工厂：传入 KnowledgeStore，返回两个工具实例。"""
    return [KnowledgeSearchTool(store), LookupSymbolTool(store)]
