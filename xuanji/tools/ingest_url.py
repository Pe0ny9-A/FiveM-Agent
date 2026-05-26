"""ingest_url：拉网页 → 简单 HTML→md → 切片入库。

风险：RiskTag.NET → DefaultPolicy 自动 HITL；小宝在 CLI 端弹窗确认 URL 后才发请求。

简化策略：
- 不引入 BeautifulSoup（M0 阶段克制依赖），用正则剥 HTML 标签
- 保留 <pre><code> 块为代码块（用 ``` 包起来）
- 处理常见块级标签为 markdown：h1-h6 / p / li / pre
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

import httpx

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.knowledge.store.base import KnowledgeStore
from xuanji.tools.ingest import _ingest_chunks

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)
_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def html_to_markdown(html: str) -> tuple[str | None, str]:
    """极简 HTML → markdown。返回 (page_title, body)。

    只处理最常见的块级标签，目的不是完美还原而是把可读文本喂给玄玑。
    """
    title_match = _TITLE_RE.search(html)
    title = _strip_tags(title_match.group(1)).strip() if title_match else None

    # 1. 干掉 script/style
    body = _SCRIPT_RE.sub("", html)

    # 2. <pre> 转 ``` 代码块（先做，避免被后面的剥标签吃掉）
    def _pre_replace(m: re.Match[str]) -> str:
        inner = _strip_tags(m.group(1))
        return f"\n\n```\n{inner.strip()}\n```\n\n"

    body = _PRE_RE.sub(_pre_replace, body)

    # 3. <h1-6> 转 markdown 标题
    def _h_replace(m: re.Match[str]) -> str:
        level = int(m.group(1))
        text = _strip_tags(m.group(2)).strip()
        return f"\n\n{'#' * level} {text}\n\n"

    body = _HEADING_RE.sub(_h_replace, body)

    # 4. <li> → "- " 列表项
    body = re.sub(r"<li[^>]*>", "\n- ", body, flags=re.IGNORECASE)
    body = re.sub(r"</li>", "", body, flags=re.IGNORECASE)

    # 5. <p> / <br> → 空行
    body = re.sub(r"</?p[^>]*>", "\n\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)

    # 6. 剥光剩余标签
    body = _TAG_RE.sub("", body)

    # 7. 清理多余空白
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return title, body


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)


class IngestUrlTool(Tool):
    """拉一个网页入库。RiskTag.NET → 走 HITL。"""

    name = "ingest_url"
    description = (
        "从 URL 拉取页面、转 markdown、切片入库。"
        "用于：玄玑发现知识库缺某段官方文档时主动补——但每个 URL 都会先问小宝确认。"
        "只跑 GET，不带 cookies/认证。失败/超时会返回 error 而不是抛异常。"
    )
    risk = RiskTag.NET
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "目标 URL（http/https）"},
            "namespace": {
                "type": "string",
                "description": "命名空间，例如 'fivem.qbcore@1.x'",
            },
            "source_title": {
                "type": "string",
                "description": "可选：来源标题，不传用 <title>",
            },
            "timeout_sec": {"type": "number", "default": 15},
            "max_bytes": {
                "type": "integer",
                "default": 1_000_000,
                "description": "防御性下载上限",
            },
        },
        "required": ["url", "namespace"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ToolError("url 必须是 http:// 或 https:// 开头")
        ns = (args.get("namespace") or "").strip()
        if not ns:
            raise ToolError("namespace 不能为空")
        timeout = float(args.get("timeout_sec", 15))
        max_bytes = int(args.get("max_bytes", 1_000_000))

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "xuanji/0.2 (FiveM dev assistant)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            return ToolResult(ok=False, error=f"HTTP 失败：{type(e).__name__}: {e}")

        content = resp.content[:max_bytes]
        try:
            html = content.decode(resp.encoding or "utf-8", errors="replace")
        except (UnicodeDecodeError, LookupError):
            html = content.decode("utf-8", errors="replace")

        title, md = html_to_markdown(html)
        source_title = args.get("source_title") or title or url
        if not md.strip():
            return ToolResult(ok=False, error="抓取成功但解析后内容为空")

        n = _ingest_chunks(
            self._store,
            namespace=ns,
            source_title=source_title,
            text=md,
            url=url,
        )
        return ToolResult(
            ok=True,
            output={
                "url": url,
                "title": source_title,
                "namespace": ns,
                "chunks_written": n,
                "html_bytes": len(content),
                "md_chars": len(md),
                "truncated": len(resp.content) > max_bytes,
            },
        )


__all__ = ["IngestUrlTool", "html_to_markdown"]
