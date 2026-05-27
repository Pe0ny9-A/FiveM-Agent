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

from xuanji.config.sqlite_conn import tune_for_multiprocess
from xuanji.knowledge.models import Chunk, Namespace, Source, Symbol
from xuanji.knowledge.store.base import SearchHit
from xuanji.knowledge.tokenize import preprocess_text
from xuanji.knowledge.vector import Embedder, VectorStore

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

-- chunks_fts 是独立 FTS5 表（非 external content），存 jieba 预处理后的"索引版"。
-- 不挂 content=chunks，因此触发器里我们手动塞预处理文本——unicode61 才能按词切。
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    namespace UNINDEXED,
    section UNINDEXED,
    source_title UNINDEXED,
    chunk_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);

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

    流程：jieba 切词 → 剥离 FTS5 元字符 → token 用 phrase 匹配并 OR 合成。
    中文连续短语经 jieba 切成多个词，能与 FTS5 倒排表里的 token 对齐，
    解决纯 phrase 匹配时中文整段查不到的问题。
    """
    pre = preprocess_text(q)
    cleaned = "".join(c if c not in _FTS_DANGEROUS else " " for c in pre)
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
            self._migrate_chunks_fts(conn)
        self._vector_store: VectorStore | None = None
        self._embedder: Embedder | None = None

    def _migrate_chunks_fts(self, conn: sqlite3.Connection) -> None:
        """把 0.1 老 schema 的 chunks_fts（external content + 触发器，无 chunk_id 列）
        平滑升级到 0.7+ 的独立 FTS5 表（含 chunk_id，jieba 预处理文本）。

        Why：CREATE VIRTUAL TABLE IF NOT EXISTS 看到老表就跳过，不会升级；老 schema 上每次
        INSERT INTO chunks_fts (..., chunk_id) 都会因列不存在而失败。
        How：建表时自检——若表已存在且不含 chunk_id，DROP 触发器 + 表 → 用新 schema 重建 →
        从 chunks 表回填（FTS 索引存 jieba 预处理文本，与 upsert_chunks 一致）。
        """
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
        ).fetchone()
        if row is None:
            return
        create_sql: str = row["sql"] or ""
        if "chunk_id" in create_sql:
            return

        for trig in ("chunks_ai", "chunks_ad", "chunks_au"):
            conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
        conn.execute("DROP TABLE chunks_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                text,
                namespace UNINDEXED,
                section UNINDEXED,
                source_title UNINDEXED,
                chunk_id UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """,
        )
        rows = conn.execute(
            "SELECT rowid, id, namespace, source_title, section, text FROM chunks"
        ).fetchall()
        for r in rows:
            conn.execute(
                """
                INSERT INTO chunks_fts (rowid, text, namespace, section, source_title, chunk_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r["rowid"],
                    preprocess_text(r["text"]),
                    r["namespace"],
                    r["section"] or "",
                    r["source_title"],
                    r["id"],
                ),
            )

    def attach_vector_index(self, embedder: Embedder, store: VectorStore) -> None:
        """挂载向量索引。挂上后写 chunks 自动 embed + upsert，
        search 可走 hybrid_search() 做 FTS5 + 向量融合。"""
        if embedder.dim != store.dim:
            raise ValueError(
                f"embedder.dim ({embedder.dim}) != store.dim ({store.dim})"
            )
        self._embedder = embedder
        self._vector_store = store

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        tune_for_multiprocess(conn)
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
                # 拿当前条目的 rowid（如果存在）以便 FTS5 同步删除
                old_row = conn.execute(
                    "SELECT rowid FROM chunks WHERE id = ?", (c.id,)
                ).fetchone()
                if old_row is not None:
                    conn.execute(
                        "DELETE FROM chunks_fts WHERE rowid = ?", (old_row["rowid"],)
                    )
                    conn.execute("DELETE FROM chunks WHERE id = ?", (c.id,))
                cur = conn.execute(
                    """
                    INSERT INTO chunks (id, namespace, source_title, section, text, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (c.id, c.namespace, c.source_title, c.section, c.text, c.url),
                )
                rowid = cur.lastrowid
                # FTS5 索引存预处理版（jieba 切词）
                conn.execute(
                    """
                    INSERT INTO chunks_fts (rowid, text, namespace, section, source_title, chunk_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rowid,
                        preprocess_text(c.text),
                        c.namespace,
                        c.section or "",
                        c.source_title,
                        c.id,
                    ),
                )
        # 向量索引：挂载了就自动 embed + upsert
        if self._embedder is not None and self._vector_store is not None:
            embeddings = self._embedder.embed_batch([c.text for c in chunks])
            self._vector_store.upsert_batch(
                [
                    (c.id, vec, {"namespace": c.namespace, "source_title": c.source_title})
                    for c, vec in zip(chunks, embeddings, strict=True)
                ],
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
            hits.append(
                SearchHit(chunk=chunk, score=score, matched_symbol=anchor, source="fts"),
            )
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

    def search_symbols_by_prefix(
        self,
        prefix: str,
        *,
        namespaces: list[Namespace] | None = None,
        kinds: list[str] | None = None,
        limit: int = 30,
    ) -> list[Symbol]:
        """前缀搜索 symbol——给 IDE 内联补全用。

        - 大小写不敏感（COLLATE NOCASE）
        - 结果按 name 字典序，相同 name 长度短的优先
        - prefix 为空字符串时返回空列表，避免误打全表
        """
        if not prefix:
            return []
        with self._connect() as conn:
            sql = "SELECT * FROM symbols WHERE name LIKE ? COLLATE NOCASE"
            params: list[Any] = [f"{prefix}%"]
            if namespaces:
                placeholders = ",".join("?" * len(namespaces))
                sql += f" AND namespace IN ({placeholders})"
                params.extend(namespaces)
            if kinds:
                placeholders = ",".join("?" * len(kinds))
                sql += f" AND kind IN ({placeholders})"
                params.extend(kinds)
            sql += " ORDER BY length(name) ASC, name ASC LIMIT ?"
            params.append(int(limit))
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

    def iter_chunks(self) -> Iterator[Chunk]:
        """流式遍历全部 chunks，用于 reindex / migration。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, namespace, source_title, section, text, url FROM chunks "
                "ORDER BY namespace, source_title, id"
            ).fetchall()
        for r in rows:
            yield Chunk(
                id=r["id"],
                namespace=r["namespace"],
                source_title=r["source_title"],
                section=r["section"],
                text=r["text"],
                url=r["url"],
            )

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
            # 先把 FTS5 行删了（拿 rowid）再删 chunks
            rows = conn.execute(
                "SELECT rowid FROM chunks WHERE namespace = ?", (namespace,)
            ).fetchall()
            row_ids = [r["rowid"] for r in rows]
            if row_ids:
                placeholders = ",".join("?" * len(row_ids))
                conn.execute(
                    f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders})",
                    row_ids,
                )
            cur = conn.execute("DELETE FROM chunks WHERE namespace = ?", (namespace,))
            n_chunks = cur.rowcount
            conn.execute("DELETE FROM symbols WHERE namespace = ?", (namespace,))
            conn.execute("DELETE FROM sources WHERE namespace = ?", (namespace,))
        # 向量索引同步清
        if self._vector_store is not None:
            self._vector_store.delete_namespace(namespace)
        return n_chunks

    # ---------------- 混合检索 ----------------

    def hybrid_search(
        self,
        query: str,
        *,
        namespaces: list[Namespace] | None = None,
        k: int = 8,
        fts_weight: float = 0.6,
    ) -> list[SearchHit]:
        """FTS5 关键词 + 向量语义 RRF 融合。

        - fts_weight ∈ [0, 1]：FTS5 在融合中的权重，向量占 1 - fts_weight
        - 没挂向量索引时退化为纯 FTS5 search
        - 用 Reciprocal Rank Fusion (RRF) 而不是分数加权——
          因为 bm25 与余弦相似度量纲不同，rank-based 融合更稳
        """
        fts_hits = self.search(query, namespaces=namespaces, k=k * 2)
        if self._embedder is None or self._vector_store is None:
            return fts_hits[:k]

        # 向量召回
        qvec = self._embedder.embed(query)
        ns_filter = namespaces[0] if namespaces and len(namespaces) == 1 else None
        vec_hits = self._vector_store.search(
            qvec, k=k * 2, filter_namespace=ns_filter,
        )

        # RRF：rank-based 融合
        rrf_k = 60
        scores: dict[str, float] = {}
        chunks_index: dict[str, Chunk] = {h.chunk.id: h.chunk for h in fts_hits}

        for rank, h in enumerate(fts_hits, start=1):
            scores[h.chunk.id] = scores.get(h.chunk.id, 0.0) + fts_weight / (rrf_k + rank)
        for rank, vh in enumerate(vec_hits, start=1):
            if namespaces and vh.metadata.get("namespace") not in namespaces:
                continue
            scores[vh.id] = scores.get(vh.id, 0.0) + (1 - fts_weight) / (rrf_k + rank)
            if vh.id not in chunks_index:
                chunks_index[vh.id] = self._fetch_chunk(vh.id)

        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        out: list[SearchHit] = []
        for cid, score in ordered[:k]:
            chunk = chunks_index.get(cid)
            if chunk is None:
                continue
            anchor = self._guess_anchor_symbol(query, chunk.namespace)
            out.append(
                SearchHit(chunk=chunk, score=score, matched_symbol=anchor, source="hybrid"),
            )
        return out

    def _fetch_chunk(self, chunk_id: str) -> Chunk:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"chunk 不存在：{chunk_id}")
        return Chunk(
            id=row["id"],
            namespace=row["namespace"],
            source_title=row["source_title"],
            section=row["section"],
            text=row["text"],
            url=row["url"],
        )

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
