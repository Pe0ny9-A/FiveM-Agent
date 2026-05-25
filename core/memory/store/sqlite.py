"""SQLite + FTS5 的记忆库实现。

- memories 表：存全字段
- memories_fts：text + summary 的 FTS5 倒排
- recall：FTS5 命中后用 importance × decay × log(1+hits) 排序
- forget：按 ids / namespace / scope 任意组合删除
- consolidate：按 importance 倒序保留 max_kept，超出的丢弃
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.memory.models import Memory, MemoryKind, MemoryScope

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    scope         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    namespace     TEXT NOT NULL,
    text          TEXT NOT NULL,
    summary       TEXT,
    importance    REAL NOT NULL DEFAULT 0.5,
    tags          TEXT,
    metadata      TEXT,
    created_at    REAL NOT NULL,
    last_accessed REAL NOT NULL,
    hits          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mem_namespace ON memories(namespace);
CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope);
CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text,
    summary,
    namespace UNINDEXED,
    content=memories,
    content_rowid=rowid,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, summary, namespace)
    VALUES (new.rowid, new.text, COALESCE(new.summary, ''), new.namespace);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, summary, namespace)
    VALUES ('delete', old.rowid, old.text, COALESCE(old.summary, ''), old.namespace);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, summary, namespace)
    VALUES ('delete', old.rowid, old.text, COALESCE(old.summary, ''), old.namespace);
    INSERT INTO memories_fts(rowid, text, summary, namespace)
    VALUES (new.rowid, new.text, COALESCE(new.summary, ''), new.namespace);
END;
"""


_FTS_DANGEROUS = set('"\'()*:^-')


def _sanitize_query(q: str) -> str:
    cleaned = "".join(c if c not in _FTS_DANGEROUS else " " for c in q)
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def _decay(now: float, last_accessed: float, half_life_days: float = 14.0) -> float:
    """指数衰减：half_life_days 后权重减半。"""
    elapsed_days = max(0.0, (now - last_accessed) / 86400.0)
    return float(0.5 ** (elapsed_days / half_life_days))


class SqliteMemoryStore:
    """SQLite + FTS5 实现的 MemoryStore。"""

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

    def write(self, memory: Memory) -> Memory:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    id, scope, kind, namespace, text, summary,
                    importance, tags, metadata,
                    created_at, last_accessed, hits
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    scope=excluded.scope,
                    kind=excluded.kind,
                    namespace=excluded.namespace,
                    text=excluded.text,
                    summary=excluded.summary,
                    importance=excluded.importance,
                    tags=excluded.tags,
                    metadata=excluded.metadata,
                    last_accessed=excluded.last_accessed
                """,
                (
                    memory.id,
                    memory.scope.value,
                    memory.kind.value,
                    memory.namespace,
                    memory.text,
                    memory.summary,
                    memory.importance,
                    json.dumps(memory.tags, ensure_ascii=False),
                    json.dumps(memory.metadata, ensure_ascii=False),
                    memory.created_at,
                    memory.last_accessed,
                    memory.hits,
                ),
            )
        return memory

    # ---------------- 读 ----------------

    def recall(
        self,
        query: str,
        *,
        scopes: list[MemoryScope] | None = None,
        kinds: list[MemoryKind] | None = None,
        namespace: str | None = None,
        k: int = 8,
    ) -> list[Memory]:
        fts_q = _sanitize_query(query)
        with self._connect() as conn:
            params: list[Any] = []
            if fts_q:
                # FTS5 命中
                sql = (
                    "SELECT m.* FROM memories_fts "
                    "JOIN memories m ON m.rowid = memories_fts.rowid "
                    "WHERE memories_fts MATCH ?"
                )
                params.append(fts_q)
            else:
                sql = "SELECT * FROM memories WHERE 1=1"

            if scopes:
                placeholders = ",".join("?" * len(scopes))
                sql += f" AND m.scope IN ({placeholders})" if fts_q else (
                    f" AND scope IN ({placeholders})"
                )
                params.extend([s.value for s in scopes])
            if kinds:
                placeholders = ",".join("?" * len(kinds))
                sql += f" AND m.kind IN ({placeholders})" if fts_q else (
                    f" AND kind IN ({placeholders})"
                )
                params.extend([s.value for s in kinds])
            if namespace is not None:
                sql += " AND m.namespace = ?" if fts_q else " AND namespace = ?"
                params.append(namespace)

            # 多取一倍候选交给 Python 端按衰减分排序
            sql += " LIMIT ?"
            params.append(k * 4)
            rows = conn.execute(sql, params).fetchall()

        now = time.time()
        scored: list[tuple[float, Memory]] = []
        for r in rows:
            m = self._row_to_memory(r)
            score = m.importance * _decay(now, m.last_accessed) * math.log1p(m.hits + 1)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [m for _, m in scored[:k]]

        # 命中即更新 hits 与 last_accessed
        if top:
            with self._connect() as conn:
                conn.executemany(
                    "UPDATE memories SET hits = hits + 1, last_accessed = ? WHERE id = ?",
                    [(now, m.id) for m in top],
                )
            for m in top:
                m.hits += 1
                m.last_accessed = now
        return top

    def get(self, id_: str) -> Memory | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (id_,)).fetchone()
        return self._row_to_memory(row) if row else None

    def list_by_namespace(
        self,
        namespace: str,
        *,
        scopes: list[MemoryScope] | None = None,
        kinds: list[MemoryKind] | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        with self._connect() as conn:
            sql = "SELECT * FROM memories WHERE namespace = ?"
            params: list[Any] = [namespace]
            if scopes:
                placeholders = ",".join("?" * len(scopes))
                sql += f" AND scope IN ({placeholders})"
                params.extend([s.value for s in scopes])
            if kinds:
                placeholders = ",".join("?" * len(kinds))
                sql += f" AND kind IN ({placeholders})"
                params.extend([s.value for s in kinds])
            sql += " ORDER BY last_accessed DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def forget(
        self,
        *,
        ids: list[str] | None = None,
        namespace: str | None = None,
        scope: MemoryScope | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if ids:
            clauses.append(f"id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        if namespace is not None:
            clauses.append("namespace = ?")
            params.append(namespace)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope.value)
        if not clauses:
            return 0
        sql = "DELETE FROM memories WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount

    def consolidate(self, namespace: str, *, max_kept: int = 100) -> int:
        """超出 max_kept 时按 importance × log(1+hits) 倒序保留前 N。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, importance, hits FROM memories
                WHERE namespace = ? AND kind = 'episodic'
                """,
                (namespace,),
            ).fetchall()
            if len(rows) <= max_kept:
                return 0
            scored = sorted(
                rows,
                key=lambda r: r["importance"] * math.log1p(r["hits"] + 1),
                reverse=True,
            )
            doomed_ids = [r["id"] for r in scored[max_kept:]]
            if not doomed_ids:
                return 0
            placeholders = ",".join("?" * len(doomed_ids))
            cur = conn.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders})",
                doomed_ids,
            )
            return cur.rowcount or 0

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_scope = {
                r["scope"]: r["c"]
                for r in conn.execute(
                    "SELECT scope, COUNT(*) AS c FROM memories GROUP BY scope"
                ).fetchall()
            }
            by_kind = {
                r["kind"]: r["c"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM memories GROUP BY kind"
                ).fetchall()
            }
            namespaces = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT namespace FROM memories ORDER BY namespace"
                ).fetchall()
            ]
        return {
            "path": str(self._path),
            "total": n,
            "by_scope": by_scope,
            "by_kind": by_kind,
            "namespaces": namespaces,
        }

    @staticmethod
    def _row_to_memory(r: sqlite3.Row) -> Memory:
        return Memory(
            id=r["id"],
            scope=MemoryScope(r["scope"]),
            kind=MemoryKind(r["kind"]),
            namespace=r["namespace"],
            text=r["text"],
            summary=r["summary"],
            importance=float(r["importance"]),
            tags=json.loads(r["tags"]) if r["tags"] else [],
            metadata=json.loads(r["metadata"]) if r["metadata"] else {},
            created_at=float(r["created_at"]),
            last_accessed=float(r["last_accessed"]),
            hits=int(r["hits"]),
        )
