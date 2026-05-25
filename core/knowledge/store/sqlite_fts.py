"""SQLite FTS5 知识库实现。

- 三张表：sources / chunks / symbols；外加一张 chunks_fts 虚拟表挂 FTS5
- chunks 与 chunks_fts 用触发器保持同步
- 中文分词用 unicode61（带 remove_diacritics=2），M2+ 可换 jieba 或 cppjieba
- search 走 FTS5 MATCH + bm25 排序，再尝试 lookup_symbol 给精准锚点加分
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.knowledge.models import Chunk, Namespace, Source, Symbol
from core.knowledge.store.base import SearchHit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    namespace TEXT NOT NULL,
    title     TEXT NOT NULL,
    url       TEXT,
    version   TEXT,
    metadata  TEXT,
    PRIMARY KEY (namespace, title)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    namespace     TEXT NOT NULL,
    source_title  TEXT NOT NULL,
    section       TEXT,
    text          TEXT NOT NULL,
    url           TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_namespace ON chunks(namespace);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    namespace UNINDEXED,
    section UNINDEXED,
    source_title UNINDEXED,
    content=chunks,
    content_rowid=rowid,
    tokenize='unicode61 remove_diacritics 2'
);

-- 触发器：chunks 与 chunks_fts 同步
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, namespace, section, source_title)
    VALUES (new.rowid, new.text, new.namespace, new.section, new.source_title);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, namespace, section, source_title)
    VALUES ('delete', old.rowid, old.text, old.namespace, old.section, old.source_title);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, namespace, section, source_title)
    VALUES ('delete', old.rowid, old.text, old.namespace, old.section, old.source_title);
    INSERT INTO chunks_fts(rowid, text, namespace, section, source_title)
    VALUES (new.rowid, new.text, new.namespace, new.section, new.source_title);
END;

CREATE TABLE IF NOT EXISTS symbols (
    id         TEXT PRIMARY KEY,
    namespace  TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    side       TEXT NOT NULL,
    signature  TEXT,
    summary    TEXT,
    params     TEXT,
    returns    TEXT,
    example    TEXT,
    url        TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_namespace ON symbols(namespace);
"""


# FTS5 MATCH 语法里这些字符是元字符，需要剥离才能安全做 phrase 查询
_FTS_DANGEROUS = set('"\'()*:^-')


def _sanitize_query(q: str) -> str:
    """把用户输入转成 FTS5 安全的 phrase 查询。

    把每个 token 用双引号包成 phrase，避免用户输入里的运算符把语法搞坏。
    """
    cleaned = "".join(c if c not in _FTS_DANGEROUS else " " for c in q)
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


class SqliteKnowledgeStore:
    """SQLite + FTS5 实现的 KnowledgeStore。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- 写 ----------------

    def upsert_source(self, source: Source) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (namespace, title, url, version, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(namespace, title) DO UPDATE SET
                    url=excluded.url,
                    version=excluded.version,
                    metadata=excluded.metadata
                """,
                (
                    source.namespace,
                    source.title,
                    source.url,
                    source.version,
                    json.dumps(source.metadata, ensure_ascii=False),
                ),
            )

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            for c in chunks:
                conn.execute("DELETE FROM chunks WHERE id = ?", (c.id,))
                conn.execute(
                    """
                    INSERT INTO chunks (id, namespace, source_title, section, text, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (c.id, c.namespace, c.source_title, c.section, c.text, c.url),
                )

    def upsert_symbols(self, symbols: list[Symbol]) -> None:
        if not symbols:
            return
        with self._connect() as conn:
            for s in symbols:
                conn.execute(
                    """
                    INSERT INTO symbols (
                        id, namespace, name, kind, side,
                        signature, summary, params, returns, example, url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        namespace=excluded.namespace,
                        name=excluded.name,
                        kind=excluded.kind,
                        side=excluded.side,
                        signature=excluded.signature,
                        summary=excluded.summary,
                        params=excluded.params,
                        returns=excluded.returns,
                        example=excluded.example,
                        url=excluded.url
                    """,
                    (
                        s.id,
                        s.namespace,
                        s.name,
                        s.kind,
                        s.side,
                        s.signature,
                        s.summary,
                        json.dumps(s.params, ensure_ascii=False),
                        s.returns,
                        s.example,
                        s.url,
                    ),
                )

    # ---------------- 读 ----------------

    def search(
        self,
        query: str,
        *,
        namespaces: list[Namespace] | None = None,
        k: int = 8,
    ) -> list[SearchHit]:
        fts_q = _sanitize_query(query)
        if not fts_q:
            return []
        with self._connect() as conn:
            sql = """
                SELECT c.id, c.namespace, c.source_title, c.section, c.text, c.url,
                       bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
            """
            params: list[Any] = [fts_q]
            if namespaces:
                placeholders = ",".join("?" * len(namespaces))
                sql += f" AND c.namespace IN ({placeholders})"
                params.extend(namespaces)
            sql += " ORDER BY score LIMIT ?"
            params.append(k)
            rows = conn.execute(sql, params).fetchall()

        # bm25() 是越小越相关；翻成相关性分数（越大越相关）便于阅读
        hits: list[SearchHit] = []
        for r in rows:
            chunk = Chunk(
                id=r["id"],
                namespace=r["namespace"],
                source_title=r["source_title"],
                section=r["section"],
                text=r["text"],
                url=r["url"],
            )
            score = -float(r["score"])
            # 试着给 chunk 找一个匹配的 symbol 作为锚点
            anchor = self._guess_anchor_symbol(query, chunk.namespace)
            hits.append(SearchHit(chunk=chunk, score=score, matched_symbol=anchor))
        return hits

    def _guess_anchor_symbol(self, query: str, ns: Namespace) -> Symbol | None:
        """从查询里抽可能的 symbol 名，命中即返回第一个。

        启发式：
        - 含 '.' 或 '_' 的 token（如 lib.callback.register / lib_callback_register）
        - 或长度 ≥ 4 且包含 ASCII 字母的 token（如 CreateUseableItem / GetPlayer）
        中文词与短词被排除，避免对每个普通词都打数据库。
        """
        seen: set[str] = set()
        for raw in query.replace(",", " ").split():
            token = raw.strip("，。！？、:：()（）'\"")
            if not token or token in seen:
                continue
            seen.add(token)
            looks_like_symbol = (
                "." in token
                or "_" in token
                or (len(token) >= 4 and any("a" <= c.lower() <= "z" for c in token))
            )
            if not looks_like_symbol:
                continue
            hits = self.lookup_symbol(token, namespaces=[ns])
            if hits:
                return hits[0]
        return None

    def lookup_symbol(
        self,
        name: str,
        *,
        namespaces: list[Namespace] | None = None,
    ) -> list[Symbol]:
        with self._connect() as conn:
            sql = "SELECT * FROM symbols WHERE name = ? OR name LIKE ?"
            params: list[Any] = [name, f"%{name}%"]
            if namespaces:
                placeholders = ",".join("?" * len(namespaces))
                sql += f" AND namespace IN ({placeholders})"
                params.extend(namespaces)
            sql += " ORDER BY (name = ?) DESC, length(name) ASC LIMIT 10"
            params.append(name)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_symbol(r) for r in rows]

    def list_sources(self) -> list[Source]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT namespace, title, url, version, metadata FROM sources "
                "ORDER BY namespace, title"
            ).fetchall()
        out: list[Source] = []
        for r in rows:
            out.append(
                Source(
                    namespace=r["namespace"],
                    title=r["title"],
                    url=r["url"],
                    version=r["version"],
                    metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                ),
            )
        return out

    def list_namespaces(self) -> list[Namespace]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT namespace FROM chunks "
                "UNION SELECT DISTINCT namespace FROM symbols "
                "ORDER BY 1"
            ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            n_sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            n_symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            namespaces = self.list_namespaces()
        return {
            "path": str(self._path),
            "sources": n_sources,
            "chunks": n_chunks,
            "symbols": n_symbols,
            "namespaces": namespaces,
        }

    def clear_namespace(self, namespace: Namespace) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM chunks WHERE namespace = ?", (namespace,))
            n_chunks = cur.rowcount
            conn.execute("DELETE FROM symbols WHERE namespace = ?", (namespace,))
            conn.execute("DELETE FROM sources WHERE namespace = ?", (namespace,))
        return n_chunks

    @staticmethod
    def _row_to_symbol(r: sqlite3.Row) -> Symbol:
        return Symbol(
            id=r["id"],
            namespace=r["namespace"],
            name=r["name"],
            kind=r["kind"],
            side=r["side"],
            signature=r["signature"],
            summary=r["summary"] or "",
            params=json.loads(r["params"]) if r["params"] else [],
            returns=r["returns"],
            example=r["example"],
            url=r["url"],
        )
