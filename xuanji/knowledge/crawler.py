"""爬虫：sitemap.xml 解析 + BFS + 增量去重 + content-hash 跳过未变更页。

设计：
- CrawlPlan：起点 URL、域名白名单、最大页数、最大深度
- CrawlSession：执行单元，跑一轮拉取
- 增量：用 (url, content_hash) 表跳过未变更，所以重复爬不会重复 ingest
- 礼貌爬取：固定并发 4 + per-host rate limit (1s 间隔) 避免被站点限流
- 没有 robots.txt 检查（M4+ 接 reppy）；用户应自己确保有权限爬

不引入 Scrapy 等重型依赖：复用 httpx + asyncio.Queue 完成。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from xuanji.knowledge.store.base import KnowledgeStore
from xuanji.tools.ingest import _ingest_chunks
from xuanji.tools.ingest_url import html_to_markdown

_ANCHOR_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<]+)\s*</loc>", re.IGNORECASE)


@dataclass
class CrawlPlan:
    """爬取计划。"""

    start_urls: list[str]
    namespace: str
    allowed_domains: list[str] = field(default_factory=list)
    max_pages: int = 50
    max_depth: int = 3
    timeout_sec: float = 15
    request_interval_sec: float = 1.0
    """同一域名两次请求之间最少间隔（礼貌爬取）。"""
    user_agent: str = "xuanji-crawler/0.3"

    def __post_init__(self) -> None:
        if not self.allowed_domains:
            # 默认从 start_urls 推断
            seen: set[str] = set()
            for u in self.start_urls:
                host = urlparse(u).hostname
                if host:
                    seen.add(host)
            self.allowed_domains = sorted(seen)


@dataclass
class CrawlReport:
    """爬取结果摘要。"""

    pages_fetched: int = 0
    pages_ingested: int = 0
    pages_skipped_unchanged: int = 0
    pages_failed: int = 0
    chunks_written: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    """(url, error_message) pairs."""


def _normalize_url(url: str) -> str:
    """剥 fragment，保证去重一致。"""
    cleaned, _ = urldefrag(url)
    return cleaned


def _is_allowed(url: str, allowed_domains: list[str]) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def _extract_links(base_url: str, html: str) -> list[str]:
    """从 HTML 抽链接，标准化为绝对 URL，剥 fragment，去重。"""
    seen: set[str] = set()
    for match in _ANCHOR_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        absolute = _normalize_url(urljoin(base_url, href))
        if absolute.startswith(("http://", "https://")):
            seen.add(absolute)
    return sorted(seen)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _fetch_one(
    client: httpx.AsyncClient, url: str, timeout: float
) -> tuple[str | None, str]:
    """返回 (html_content_or_none, error_message)。"""
    try:
        resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return None, f"{type(e).__name__}: {e}"
    try:
        return resp.text, ""
    except UnicodeDecodeError:
        return resp.content.decode("utf-8", errors="replace"), ""


async def parse_sitemap(client: httpx.AsyncClient, sitemap_url: str) -> list[str]:
    """解析 sitemap.xml，返回里面所有 <loc>。

    支持嵌套 sitemap（sitemap index）：递归展开一层。
    """
    html, _ = await _fetch_one(client, sitemap_url, timeout=15)
    if html is None:
        return []
    locs = [m.group(1).strip() for m in _SITEMAP_LOC_RE.finditer(html)]
    # 简单判断：如果 loc 又指向 .xml 则递归一层
    out: list[str] = []
    for loc in locs:
        if loc.endswith(".xml"):
            sub_html, _ = await _fetch_one(client, loc, timeout=15)
            if sub_html is None:
                continue
            for m in _SITEMAP_LOC_RE.finditer(sub_html):
                out.append(m.group(1).strip())
        else:
            out.append(loc)
    return out


# ============================================================
# CrawlSession：BFS + 增量
# ============================================================


class CrawlSession:
    """单次爬取会话。

    用法：
        session = CrawlSession(plan, store, hash_cache=hash_cache)
        report = await session.run()

    hash_cache：dict[url, content_hash]，跨会话保留可实现"未变更跳过"。
    爬虫工具 CLI 时用 SQLite 持久化；单测可用 dict。
    """

    def __init__(
        self,
        plan: CrawlPlan,
        store: KnowledgeStore,
        *,
        hash_cache: dict[str, str] | None = None,
    ) -> None:
        self.plan = plan
        self.store = store
        self.hash_cache = hash_cache if hash_cache is not None else {}
        self._last_request: dict[str, float] = {}  # host → last fetch time

    async def _wait_rate_limit(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        now = time.monotonic()
        last = self._last_request.get(host, 0.0)
        wait = self.plan.request_interval_sec - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request[host] = time.monotonic()

    async def run(self) -> CrawlReport:
        report = CrawlReport()
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        for u in self.plan.start_urls:
            queue.append((_normalize_url(u), 0))

        async with httpx.AsyncClient(
            headers={"User-Agent": self.plan.user_agent},
            follow_redirects=True,
        ) as client:
            while queue and report.pages_fetched < self.plan.max_pages:
                url, depth = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)
                if not _is_allowed(url, self.plan.allowed_domains):
                    continue

                await self._wait_rate_limit(url)
                html, err = await _fetch_one(client, url, self.plan.timeout_sec)
                report.pages_fetched += 1

                if html is None:
                    report.pages_failed += 1
                    report.failures.append((url, err))
                    continue

                title, md = html_to_markdown(html)
                content_hash = _content_hash(md)
                if self.hash_cache.get(url) == content_hash:
                    report.pages_skipped_unchanged += 1
                else:
                    if md.strip():
                        n = _ingest_chunks(
                            self.store,
                            namespace=self.plan.namespace,
                            source_title=title or url,
                            text=md,
                            url=url,
                        )
                        report.chunks_written += n
                        report.pages_ingested += 1
                        self.hash_cache[url] = content_hash

                # 抽链接、深度未到则入队
                if depth + 1 <= self.plan.max_depth:
                    for link in _extract_links(url, html):
                        if link not in visited and _is_allowed(
                            link, self.plan.allowed_domains
                        ):
                            queue.append((link, depth + 1))
        return report


__all__ = [
    "CrawlPlan",
    "CrawlReport",
    "CrawlSession",
    "_extract_links",  # 单测用
    "_normalize_url",
    "parse_sitemap",
]
