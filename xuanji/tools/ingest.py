"""知识 ingestion 工具：让玄玑自动补充知识库。

四件套：
- ingest_text：直接把一段文本切片入库（给小宝粘贴文档用）
- ingest_file：从工程内文件读入（read_file 是 SAFE，这里同档）
- upsert_symbol：精准添加 / 更新一张 API 卡片（结构化）
- ingest_url：拉网页 → 转 markdown → 切片入库（**RiskTag.NET，走司辰阁 HITL**）

后三者放本文件，ingest_url 单列在 ingest_url.py（依赖 httpx 网络）。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, ClassVar

from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from core.knowledge.chunker import chunk_markdown
from core.knowledge.models import Chunk, Source, Symbol
from core.knowledge.store.base import KnowledgeStore


def _stable_id(*parts: str) -> str:
    """对 URL/路径生成短 hash 作为 id 后缀，避免重复 ingest 创建重复条目。"""
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:10]


def _slugify(text: str) -> str:
    """简单的 slug：保留字母数字与中文，其余转 -。"""
    s = re.sub(r"[^\w一-鿿]+", "-", text.strip(), flags=re.UNICODE)
    return s.strip("-").lower()[:60] or "untitled"


def _ingest_chunks(
    store: KnowledgeStore,
    *,
    namespace: str,
    source_title: str,
    text: str,
    url: str | None,
    section_prefix: str | None = None,
) -> int:
    """切分 + 入库。返回写入的 chunk 数。"""
    parts = chunk_markdown(text)
    if not parts:
        return 0
    chunks: list[Chunk] = []
    seed = _stable_id(namespace, source_title, url or "")
    for i, (title, body) in enumerate(parts):
        section = title or section_prefix
        chunk_slug = _slugify(title or f"part-{i}")
        chunks.append(
            Chunk(
                id=f"{namespace}:{chunk_slug}#{seed}-{i}",
                namespace=namespace,
                source_title=source_title,
                section=section,
                text=body,
                url=url,
            ),
        )
    store.upsert_chunks(chunks)
    store.upsert_source(
        Source(namespace=namespace, title=source_title, url=url, version=None),
    )
    return len(chunks)


# ----------------------------- ingest_text -----------------------------


class IngestTextTool(Tool):
    """直接把一段文本入库——小宝粘贴文档时最直接。"""

    name = "ingest_text"
    description = (
        "把一段 markdown / 纯文本切片后写入知识库。"
        "用于：小宝粘贴一段文档片段、玄玑总结一份会议结论想沉淀、把外部资料手动喂给玄玑。"
        "切分策略：按 markdown 标题分节，超长再按空行切，保留代码块完整。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "命名空间，例如 'user.myproject@1' 或 'fivem.qbcore@1.x'",
            },
            "source_title": {
                "type": "string",
                "description": "来源标题，便于检索时显示出处",
            },
            "text": {"type": "string", "description": "完整文本内容"},
            "url": {"type": "string", "description": "可选：来源 URL"},
        },
        "required": ["namespace", "source_title", "text"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        ns = (args.get("namespace") or "").strip()
        title = (args.get("source_title") or "").strip()
        text = args.get("text") or ""
        if not ns or not title or not text.strip():
            raise ToolError("namespace / source_title / text 都不能为空")
        n = _ingest_chunks(
            self._store,
            namespace=ns,
            source_title=title,
            text=text,
            url=args.get("url"),
        )
        return ToolResult(
            ok=True,
            output={"namespace": ns, "source_title": title, "chunks_written": n},
        )


# ----------------------------- ingest_file -----------------------------


class IngestFileTool(Tool):
    """从工程内文件读入并入库。读纯文本文件没有副作用，所以是 SAFE。"""

    name = "ingest_file"
    description = (
        "读取工程内的 markdown / 文本文件，切片后写入知识库。"
        "用于：把项目自带的 README / docs/ / NOTES.md 等长期资料吃进知识库，方便后续召回。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径，相对工程根或绝对"},
            "namespace": {
                "type": "string",
                "description": "命名空间，例如 'user.myproject@1'",
            },
            "source_title": {
                "type": "string",
                "description": "来源标题，不传则用文件名",
            },
            "max_bytes": {
                "type": "integer",
                "default": 500_000,
                "description": "防御性上限，避免读到巨大文件",
            },
        },
        "required": ["path", "namespace"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        raw_path = args["path"]
        p = Path(raw_path)
        if not p.is_absolute():
            p = ctx.project_root / p
        if not p.exists():
            raise ToolError(f"文件不存在：{p}")
        if not p.is_file():
            raise ToolError(f"不是文件：{p}")
        max_bytes = int(args.get("max_bytes", 500_000))
        data = p.read_bytes()[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        title = args.get("source_title") or p.name
        n = _ingest_chunks(
            self._store,
            namespace=args["namespace"],
            source_title=title,
            text=text,
            url=str(p),
        )
        return ToolResult(
            ok=True,
            output={
                "path": str(p),
                "namespace": args["namespace"],
                "source_title": title,
                "chunks_written": n,
                "truncated": p.stat().st_size > max_bytes,
            },
        )


# ----------------------------- upsert_symbol -----------------------------


class UpsertSymbolTool(Tool):
    """精准添加/更新一张 API 卡片。"""

    name = "upsert_symbol"
    description = (
        "添加或更新一张结构化 API 卡片（Symbol）——比 chunk 更精准的「锚点」。"
        "用于：玄玑学到一个新的 API/事件/native（比如 ox_lib 的某个新 export），"
        "想以后能被 lookup_symbol 精准查到。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "name": {
                "type": "string",
                "description": "全限定名，如 'QBCore.Functions.GetPlayer' 或 'lib.callback.register'",
            },
            "kind": {
                "type": "string",
                "enum": ["function", "event", "export", "native", "module"],
                "default": "function",
            },
            "side": {
                "type": "string",
                "enum": ["client", "server", "shared", "any"],
                "default": "any",
            },
            "signature": {"type": "string", "description": "签名串，例如 'foo(x, y) -> z'"},
            "summary": {"type": "string", "description": "一句话说明"},
            "params": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "desc": {"type": "string"},
                    },
                },
            },
            "returns": {"type": "string"},
            "example": {"type": "string", "description": "示例代码片段"},
            "url": {"type": "string"},
        },
        "required": ["namespace", "name"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        ns = args["namespace"]
        name = args["name"]
        sym = Symbol(
            id=f"{ns}::{name}",
            namespace=ns,
            name=name,
            kind=args.get("kind", "function"),
            side=args.get("side", "any"),
            signature=args.get("signature"),
            summary=(args.get("summary") or "").strip(),
            params=list(args.get("params") or []),
            returns=args.get("returns"),
            example=args.get("example"),
            url=args.get("url"),
        )
        self._store.upsert_symbols([sym])
        return ToolResult(
            ok=True,
            output={"id": sym.id, "namespace": ns, "name": name},
            extra={"upserted": True},
        )


def ingest_tools_offline(store: KnowledgeStore) -> list[Tool]:
    """工厂：返回不需要网络的三个 ingestion 工具。"""
    return [
        IngestTextTool(store),
        IngestFileTool(store),
        UpsertSymbolTool(store),
    ]


__all__ = [
    "IngestFileTool",
    "IngestTextTool",
    "UpsertSymbolTool",
    "ingest_tools_offline",
]
