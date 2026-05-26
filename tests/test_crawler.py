"""爬虫单测——只测离线逻辑，不真发网络请求。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from xuanji.knowledge import SqliteKnowledgeStore
from xuanji.knowledge.crawler import (
    CrawlPlan,
    CrawlSession,
    _extract_links,
    _normalize_url,
)


def test_normalize_url_strips_fragment() -> None:
    assert _normalize_url("https://x.com/a#section") == "https://x.com/a"
    assert _normalize_url("https://x.com/a") == "https://x.com/a"


def test_extract_links_resolves_relative() -> None:
    html = (
        '<html><body>'
        '<a href="/foo">F</a>'
        '<a href="bar.html">B</a>'
        '<a href="https://other.com/q">O</a>'
        '<a href="javascript:void(0)">J</a>'
        '<a href="">E</a>'
        '</body></html>'
    )
    links = _extract_links("https://x.com/dir/page", html)
    assert "https://x.com/foo" in links
    assert "https://x.com/dir/bar.html" in links
    assert "https://other.com/q" in links
    assert not any("javascript" in link for link in links)


def test_crawl_plan_infers_allowed_domains() -> None:
    plan = CrawlPlan(
        start_urls=["https://docs.x.com/a", "https://docs.x.com/b"],
        namespace="ns@1",
    )
    assert "docs.x.com" in plan.allowed_domains


@pytest.mark.asyncio
async def test_crawl_session_bfs_with_mock(tmp_path: Path) -> None:
    """用 httpx MockTransport 模拟一个三页站点。"""
    pages = {
        "https://x.com/a": (
            "<html><head><title>A</title></head>"
            "<body><h1>Page A</h1>"
            "<a href='/b'>to B</a><a href='/c'>to C</a>"
            "</body></html>"
        ),
        "https://x.com/b": (
            "<html><head><title>B</title></head>"
            "<body><h1>Page B</h1></body></html>"
        ),
        "https://x.com/c": (
            "<html><head><title>C</title></head>"
            "<body><h1>Page C</h1>"
            "<a href='https://other.com/skip'>外链不爬</a></body></html>"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        url_no_frag, _ = url.split("#", 1) if "#" in url else (url, "")
        if url_no_frag in pages:
            return httpx.Response(200, text=pages[url_no_frag])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # patch httpx.AsyncClient 让它用 mock transport
    real_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    plan = CrawlPlan(
        start_urls=["https://x.com/a"],
        namespace="ns@1",
        max_pages=10,
        max_depth=2,
        request_interval_sec=0.0,  # 单测里不等
    )
    session = CrawlSession(plan, store)

    import unittest.mock

    with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
        report = await session.run()

    assert report.pages_fetched == 3  # a, b, c
    assert report.pages_ingested == 3
    assert report.pages_failed == 0
    assert report.chunks_written >= 3

    # 内容应入了知识库
    hits = store.search("Page B")
    assert hits


@pytest.mark.asyncio
async def test_crawl_session_skips_unchanged(tmp_path: Path) -> None:
    """二次爬取相同内容时，content-hash 命中应跳过 ingest。"""
    page = "<html><head><title>T</title></head><body>same content</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    plan = CrawlPlan(
        start_urls=["https://x.com/p"],
        namespace="ns@1",
        max_pages=2,
        max_depth=0,
        request_interval_sec=0.0,
    )
    cache: dict[str, str] = {}

    import unittest.mock

    with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
        # 第一次：写入
        r1 = await CrawlSession(plan, store, hash_cache=cache).run()
        assert r1.pages_ingested == 1
        # 第二次：cache 命中 → 跳过
        r2 = await CrawlSession(plan, store, hash_cache=cache).run()
        assert r2.pages_skipped_unchanged == 1
        assert r2.pages_ingested == 0


@pytest.mark.asyncio
async def test_crawl_respects_allowed_domains(tmp_path: Path) -> None:
    """外域链接不应被爬。"""
    pages = {
        "https://allowed.com/a": (
            "<html><body>"
            "<a href='https://blocked.com/x'>外链</a>"
            "</body></html>"
        ),
        "https://blocked.com/x": (
            "<html><body><h1>SECRET_TOKEN_42</h1></body></html>"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages.get(str(request.url), ""))

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    plan = CrawlPlan(
        start_urls=["https://allowed.com/a"],
        namespace="ns@1",
        max_pages=10,
        max_depth=2,
        request_interval_sec=0.0,
    )
    import unittest.mock

    with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
        report = await CrawlSession(plan, store).run()

    assert report.pages_fetched == 1
    # 外域内容不应被抓取入库
    assert not store.search("SECRET_TOKEN_42")


@pytest.mark.asyncio
async def test_crawl_max_pages_limit(tmp_path: Path) -> None:
    """max_pages 应限制总爬取数。"""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(
            200,
            text=(
                "<html><body>"
                f"<a href='/p{counter['n']+1}'>next</a>"
                "</body></html>"
            ),
        )

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    plan = CrawlPlan(
        start_urls=["https://x.com/p1"],
        namespace="ns@1",
        max_pages=3,
        max_depth=10,
        request_interval_sec=0.0,
    )
    import unittest.mock

    with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
        report = await CrawlSession(plan, store).run()
    assert report.pages_fetched == 3


# ---------------- crawl_site 工具 ----------------


@pytest.mark.asyncio
async def test_crawl_site_tool_validates_url(tmp_path: Path) -> None:
    from xuanji.capability.tool import ToolCtx, ToolError
    from xuanji.tools.crawl import CrawlSiteTool

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    tool = CrawlSiteTool(store)
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")

    with pytest.raises(ToolError, match="非法 URL"):
        await tool.execute(
            {"start_urls": ["javascript:alert(1)"], "namespace": "ns@1"}, ctx,
        )
    with pytest.raises(ToolError, match="namespace"):
        await tool.execute({"start_urls": ["https://x.com"]}, ctx)


@pytest.mark.asyncio
async def test_crawl_site_tool_persists_cache(tmp_path: Path) -> None:
    """hash cache 持久化到磁盘，跨调用复用。"""
    from xuanji.capability.tool import ToolCtx
    from xuanji.tools.crawl import CrawlSiteTool

    page = "<html><head><title>T</title></head><body>cached content</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    store = SqliteKnowledgeStore(tmp_path / "k.db")
    cache_file = tmp_path / "cache.json"
    tool = CrawlSiteTool(store, hash_cache_path=cache_file)
    ctx = ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")

    import unittest.mock

    with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
        # 第一次爬
        res1 = await tool.execute(
            {
                "start_urls": ["https://x.com/p"],
                "namespace": "ns@1",
                "max_pages": 1,
                "max_depth": 0,
                "request_interval_sec": 0.0,
            },
            ctx,
        )
        assert res1.ok
        assert cache_file.exists()

        # 第二次：拿新 tool 实例（模拟下一次 chat 启动），cache 应被复用
        tool2 = CrawlSiteTool(store, hash_cache_path=cache_file)
        res2 = await tool2.execute(
            {
                "start_urls": ["https://x.com/p"],
                "namespace": "ns@1",
                "max_pages": 1,
                "max_depth": 0,
                "request_interval_sec": 0.0,
            },
            ctx,
        )
        assert res2.ok
        assert res2.output["pages_skipped_unchanged"] == 1
