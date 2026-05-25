"""文本切分。M1 用简单的"按 markdown 标题 + 段落长度"启发式。

策略：
- 优先按二级及以上标题切（# / ## / ###），保留标题作为 section
- 单段超长（> max_chars）再按空行切
- 保留代码块整段，不在 ``` 中间断开

未来 M3+ 接 LLM 语义切分时换实现，接口保持一致。
"""

from __future__ import annotations

import re

# 默认每段最大字符数；中文按字符算够用，英文偏向句子结尾切
DEFAULT_MAX_CHARS = 1500
DEFAULT_MIN_CHARS = 200

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def chunk_markdown(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[tuple[str | None, str]]:
    """切 markdown。返回 [(section_title, body), ...]。

    短段会与相邻段合并，避免过碎。
    """
    if not text.strip():
        return []

    sections = _split_by_headings(text)
    chunks: list[tuple[str | None, str]] = []
    for title, body in sections:
        body = body.strip()
        if not body:
            continue
        if len(body) <= max_chars:
            chunks.append((title, body))
        else:
            for piece in _split_long_body(body, max_chars):
                chunks.append((title, piece))

    # 合并过短的相邻片段
    merged: list[tuple[str | None, str]] = []
    for title, body in chunks:
        if merged and len(merged[-1][1]) < min_chars and merged[-1][0] == title:
            prev_title, prev_body = merged[-1]
            merged[-1] = (prev_title, prev_body + "\n\n" + body)
        else:
            merged.append((title, body))
    return merged


def _split_by_headings(text: str) -> list[tuple[str | None, str]]:
    """按 markdown 标题切。第一段标题之前的内容 title=None。"""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(None, text)]
    out: list[tuple[str | None, str]] = []
    if matches[0].start() > 0:
        intro = text[: matches[0].start()].strip()
        if intro:
            out.append((None, intro))
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((title, text[body_start:body_end].strip()))
    return out


def _split_long_body(body: str, max_chars: int) -> list[str]:
    """按空行切超长段落。代码块（``` 包起来）整体保留。"""
    # 先把代码块当成"原子段"切出来
    parts: list[str] = []
    in_code = False
    buf: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip().startswith("```"):
            buf.append(line)
            in_code = not in_code
            if not in_code:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(line)
    if buf:
        parts.append("".join(buf))

    # 再把每个非代码块段按空行切到 max_chars
    out: list[str] = []
    for part in parts:
        if part.lstrip().startswith("```") or len(part) <= max_chars:
            if part.strip():
                out.append(part.strip())
            continue
        cur = ""
        for paragraph in part.split("\n\n"):
            if len(cur) + len(paragraph) + 2 > max_chars and cur:
                out.append(cur.strip())
                cur = paragraph
            else:
                cur = cur + "\n\n" + paragraph if cur else paragraph
        if cur.strip():
            out.append(cur.strip())
    return out


__all__ = ["DEFAULT_MAX_CHARS", "DEFAULT_MIN_CHARS", "chunk_markdown"]
