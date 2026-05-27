"""多进程 SQLite 调优单测。

验证 `tune_for_multiprocess` 对 knowledge / memory / tool_factory 三个 store 的
连接都开了 WAL + busy_timeout，并且即使 PRAGMA 失败也不会让 store 起不来。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from xuanji.config.sqlite_conn import tune_for_multiprocess
from xuanji.knowledge import SqliteKnowledgeStore
from xuanji.memory import SqliteMemoryStore
from xuanji.tools.tool_factory import FactoryRegistry


def _journal_mode(path: Path) -> str:
    with sqlite3.connect(path) as c:
        return str(c.execute("PRAGMA journal_mode").fetchone()[0]).lower()


def test_tune_sets_wal_busy_timeout_synchronous(tmp_path: Path) -> None:
    db = tmp_path / "tune.db"
    conn = sqlite3.connect(db)
    tune_for_multiprocess(conn)
    assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 30_000
    assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 1  # NORMAL
    conn.close()


def test_tune_swallows_operational_error() -> None:
    """老内核 / 只读卷拒绝 WAL 时不应抛——store 仍要能起来。"""

    class FakeConn:
        def execute(self, sql: str) -> object:
            if "journal_mode" in sql:
                raise sqlite3.OperationalError("disk is read-only")
            return None

    tune_for_multiprocess(FakeConn())  # type: ignore[arg-type]  不抛即通过


def test_knowledge_store_opens_in_wal(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    SqliteKnowledgeStore(db)  # init writes schema → 触发 WAL
    assert _journal_mode(db) == "wal"


def test_memory_store_opens_in_wal(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    SqliteMemoryStore(db)
    assert _journal_mode(db) == "wal"


def test_tool_factory_store_opens_in_wal(tmp_path: Path) -> None:
    db = tmp_path / "tf.db"
    FactoryRegistry(db)
    assert _journal_mode(db) == "wal"


def test_concurrent_readers_do_not_block_writer(tmp_path: Path) -> None:
    """WAL 的核心承诺：一个读者持着事务时，写者也能继续——
    在 DELETE 模式下这步会卡住等 busy_timeout。"""
    db = tmp_path / "concurrent.db"
    SqliteMemoryStore(db)  # init schema

    reader = sqlite3.connect(db)
    tune_for_multiprocess(reader)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM memories").fetchall()

    writer = sqlite3.connect(db)
    tune_for_multiprocess(writer)
    # WAL 下这条 INSERT 应该立刻成功，不会被 reader 的事务挡住
    writer.execute(
        "INSERT INTO memories "
        "(id, scope, namespace, kind, text, importance, created_at, last_accessed) "
        "VALUES ('x', 'session', 'ns', 'episodic', 't', 0.5, 0, 0)"
    )
    writer.commit()

    reader.commit()
    reader.close()
    writer.close()


# ---------------- LanceDB 降级 ----------------


def test_make_vector_store_falls_back_when_lancedb_locked(tmp_path: Path) -> None:
    """LanceDB 实例化成功但 connect 抛 OSError（兄弟进程占着 manifest）→ 降级到 InMemory。"""
    from xuanji.knowledge import InMemoryVectorStore
    from xuanji.server.runtime import ServerRuntime

    class _LockedFakeStore:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def _connect(self) -> None:
            raise OSError("manifest held by sibling process")

    with patch("xuanji.server.runtime.LanceDBVectorStore", _LockedFakeStore):
        store = ServerRuntime._make_vector_store("lancedb", dim=8)
    assert isinstance(store, InMemoryVectorStore)


def test_make_vector_store_falls_back_when_lancedb_missing(tmp_path: Path) -> None:
    """没装 lancedb extra 时（ImportError）也得降级。"""
    from xuanji.knowledge import InMemoryVectorStore
    from xuanji.server.runtime import ServerRuntime

    with patch(
        "xuanji.server.runtime.LanceDBVectorStore",
        side_effect=ImportError("No module named 'lancedb'"),
    ):
        store = ServerRuntime._make_vector_store("lancedb", dim=8)
    assert isinstance(store, InMemoryVectorStore)


def test_make_vector_store_inmemory_is_default(tmp_path: Path) -> None:
    from xuanji.knowledge import InMemoryVectorStore
    from xuanji.server.runtime import ServerRuntime

    store = ServerRuntime._make_vector_store("inmemory", dim=8)
    assert isinstance(store, InMemoryVectorStore)
