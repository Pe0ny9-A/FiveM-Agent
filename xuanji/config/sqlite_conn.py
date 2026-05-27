"""跨进程友好的 SQLite 连接配置。

两个 VS Code / 一个 CLI / 一个桌面端同时跑时，多个 ServerRuntime 会共享
%LOCALAPPDATA%\\xuanji 下的 knowledge.db / memory.db / tool_factory.db。默认
journal_mode=DELETE 写时整库锁，握手期任何写都会让兄弟进程卡住直到超时。

`tune_for_multiprocess` 把连接调到 WAL（多读单写不互斥） + busy_timeout=30s
（短暂写竞争时阻塞等待而非立刻报 'database is locked'） + synchronous=NORMAL
（WAL 推荐档，不靠 fsync 保证耐久）。所有用 sqlite3.connect 的地方先调一下它。
"""

from __future__ import annotations

import sqlite3

_BUSY_TIMEOUT_MS = 30_000


def tune_for_multiprocess(conn: sqlite3.Connection) -> None:
    """开 WAL + busy_timeout + synchronous=NORMAL。失败不抛——
    某些只读卷或老内核可能拒绝 WAL，那就退回默认模式继续跑。"""
    try:
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass


__all__ = ["tune_for_multiprocess"]
