"""crawl_site 工具：让玄玑批量爬一个站点。

风险：RiskTag.NET → 司辰阁默认 HITL；用户必须确认整次爬取后才会开始。
不像 ingest_url（一个 URL 一次确认），crawl_site 一次确认放行整个 BFS。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from core.knowledge.crawler import CrawlPlan, CrawlSession
from core.knowledge.store.base import KnowledgeStore


class CrawlSiteTool(Tool):
    """爬一个站点把内容入库。"""

    name = "crawl_site"
    description = (
        "从 start_urls 出发 BFS 爬一个站点，把每页转 markdown 切片入库。"
        "支持增量去重（相同 URL 内容未变就跳过）。"
        "高风险（NET），整次爬取一次性走司辰阁 HITL 确认。"
        "用于：玄玑发现知识库缺一整段官方文档体系时，批量补充——比 ingest_url 一次次拉省事。"
    )
    risk = RiskTag.NET
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "start_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "起点 URL（http/https），通常 1-3 个",
            },
            "namespace": {
                "type": "string",
                "description": "目标命名空间，例如 'fivem.qbcore@1.x'",
            },
            "allowed_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "允许的域名白名单；不传则从 start_urls 推断",
            },
            "max_pages": {
                "type": "integer",
                "default": 30,
                "description": "最大爬取页数，防止失控",
            },
            "max_depth": {"type": "integer", "default": 2},
            "request_interval_sec": {
                "type": "number",
                "default": 1.0,
                "description": "同域名两次请求间最少间隔（秒），礼貌爬取",
            },
        },
        "required": ["start_urls", "namespace"],
    }

    def __init__(
        self,
        store: KnowledgeStore,
        hash_cache_path: Path | None = None,
    ) -> None:
        self._store = store
        self._hash_cache_path = hash_cache_path
        self._cache: dict[str, str] | None = None

    def _load_cache(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        cache: dict[str, str] = {}
        if self._hash_cache_path and self._hash_cache_path.exists():
            import json

            try:
                cache = json.loads(self._hash_cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cache = {}
        self._cache = cache
        return cache

    def _save_cache(self, cache: dict[str, str]) -> None:
        if self._hash_cache_path is None:
            return
        import json

        self._hash_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._hash_cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        start_urls = args.get("start_urls") or []
        if not start_urls:
            raise ToolError("start_urls 不能为空")
        for u in start_urls:
            if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                raise ToolError(f"非法 URL：{u!r}")
        ns = (args.get("namespace") or "").strip()
        if not ns:
            raise ToolError("namespace 不能为空")

        plan = CrawlPlan(
            start_urls=list(start_urls),
            namespace=ns,
            allowed_domains=list(args.get("allowed_domains") or []),
            max_pages=int(args.get("max_pages", 30)),
            max_depth=int(args.get("max_depth", 2)),
            request_interval_sec=float(args.get("request_interval_sec", 1.0)),
        )

        cache = self._load_cache()
        session = CrawlSession(plan, self._store, hash_cache=cache)
        try:
            report = await session.run()
        except Exception as e:
            return ToolResult(ok=False, error=f"爬取失败：{type(e).__name__}: {e}")
        self._save_cache(cache)

        return ToolResult(
            ok=True,
            output={
                "namespace": ns,
                "pages_fetched": report.pages_fetched,
                "pages_ingested": report.pages_ingested,
                "pages_skipped_unchanged": report.pages_skipped_unchanged,
                "pages_failed": report.pages_failed,
                "chunks_written": report.chunks_written,
                "failures": report.failures[:10],
            },
        )


__all__ = ["CrawlSiteTool"]
