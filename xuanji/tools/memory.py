"""记忆工具：让玄玑可在对话中主动读写记忆。

设计要点：
- recall_memory：与 chat 自动 reflux 走同一 store，但允许玄玑明确发起检索（带过滤条件）
- write_memory：玄玑判断"这条值得记"时主动落库
  · 默认写到 project namespace（与 Conductor.memory_namespace 一致）
  · 默认 importance=0.6（中等偏上），调用方可覆盖
  · 写入只允许 project / session / user 三层；working 层不暴露给工具
- 写入是 IO 风险但只动玄玑自己的 SQLite，工程外路径策略不适用 → 标记 SAFE
"""

from __future__ import annotations

from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.memory.models import Memory, MemoryKind, MemoryScope
from xuanji.memory.store.base import MemoryStore

# 玄玑能写入的 scope（屏蔽 working 层，避免被模型当垃圾桶）
_WRITABLE_SCOPES = {
    MemoryScope.SESSION.value,
    MemoryScope.PROJECT.value,
    MemoryScope.USER.value,
}


class RecallMemoryTool(Tool):
    """主动召回记忆（与 chat 的 reflux 共享同一 store）。"""

    name = "recall_memory"
    description = (
        "按关键词召回过往记忆。Conductor 每轮已自动注入 top-5，"
        "但玄玑遇到「小宝是不是之前说过 X」这种具体疑问时可主动查更精确的关键词。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "召回查询"},
            "kinds": {
                "type": "array",
                "items": {"enum": ["episodic", "semantic", "procedural"]},
                "description": "可选：仅查某些类型",
            },
            "scopes": {
                "type": "array",
                "items": {"enum": ["session", "project", "user"]},
                "description": "可选：仅查某些作用域",
            },
            "k": {"type": "integer", "default": 8},
            "cross_namespace": {
                "type": "boolean",
                "default": False,
                "description": "true 则跨命名空间查（默认仅在当前 project 内）",
            },
        },
        "required": ["query"],
    }

    def __init__(self, store: MemoryStore, current_namespace: str) -> None:
        self._store = store
        self._current_ns = current_namespace

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            raise ToolError("query 不能为空")
        kinds = [MemoryKind(k) for k in args.get("kinds", [])] or None
        scopes = [MemoryScope(s) for s in args.get("scopes", [])] or None
        k = int(args.get("k", 8))
        ns = None if args.get("cross_namespace") else self._current_ns
        hits = self._store.recall(
            query, scopes=scopes, kinds=kinds, namespace=ns, k=k,
        )
        out = [
            {
                "id": m.id[:8],
                "scope": m.scope.value,
                "kind": m.kind.value,
                "namespace": m.namespace,
                "summary": m.summary or m.text[:120],
                "importance": round(m.importance, 2),
                "hits": m.hits,
            }
            for m in hits
        ]
        return ToolResult(
            ok=True,
            output=out,
            extra={"query": query, "count": len(out), "namespace": ns},
        )


class WriteMemoryTool(Tool):
    """主动写入一条记忆。"""

    name = "write_memory"
    description = (
        "把一个值得长期保留的事实/约定/解题套路写进记忆库。"
        "什么时候写：(1) 小宝明确说「记一下」；(2) 你判断这条信息会跨对话复用，"
        "比如「项目用 QBox 而非 QBCore」「每次部署前要先跑 X 命令」；"
        "(3) 解决了一个非显然的问题，把套路写成 procedural 留给以后。"
        "不要写：当下临时上下文、可以从代码读出来的事实、私密信息。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "记忆主体"},
            "summary": {
                "type": "string",
                "description": "一句话摘要（≤80 字），reflux 时优先用这个塞 system prompt",
            },
            "kind": {
                "type": "string",
                "enum": ["episodic", "semantic", "procedural"],
                "default": "semantic",
                "description": (
                    "episodic=具体事件；semantic=事实卡片；procedural=做事套路。"
                    "不确定时用 semantic。"
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["session", "project", "user"],
                "default": "project",
                "description": (
                    "session=本会话即丢；project=项目内共享（默认）；"
                    "user=跨项目用户偏好（如代码风格）。"
                ),
            },
            "namespace": {
                "type": "string",
                "description": "命名空间，不传则用当前 project namespace",
            },
            "importance": {
                "type": "number",
                "default": 0.6,
                "description": "0~1，会影响 reflux 排序权重",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选标签，便于以后过滤",
            },
        },
        "required": ["text"],
    }

    def __init__(self, store: MemoryStore, current_namespace: str) -> None:
        self._store = store
        self._current_ns = current_namespace

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        text = (args.get("text") or "").strip()
        if not text:
            raise ToolError("text 不能为空")
        scope_str = args.get("scope", "project")
        if scope_str not in _WRITABLE_SCOPES:
            raise ToolError(f"scope 必须在 {sorted(_WRITABLE_SCOPES)} 内")
        kind_str = args.get("kind", "semantic")
        importance = float(args.get("importance", 0.6))
        importance = max(0.0, min(1.0, importance))

        m = Memory(
            scope=MemoryScope(scope_str),
            kind=MemoryKind(kind_str),
            namespace=args.get("namespace") or self._current_ns,
            text=text,
            summary=args.get("summary"),
            importance=importance,
            tags=list(args.get("tags") or []),
        )
        saved = self._store.write(m)
        return ToolResult(
            ok=True,
            output={
                "id": saved.id,
                "scope": saved.scope.value,
                "kind": saved.kind.value,
                "namespace": saved.namespace,
                "importance": saved.importance,
            },
            extra={"created": True},
        )


def memory_tools(store: MemoryStore, current_namespace: str) -> list[Tool]:
    """工厂：返回 recall + write 两件套。"""
    return [
        RecallMemoryTool(store, current_namespace),
        WriteMemoryTool(store, current_namespace),
    ]


__all__ = ["RecallMemoryTool", "WriteMemoryTool", "memory_tools"]
