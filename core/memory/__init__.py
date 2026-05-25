"""怀玉阁 · 记忆系统。

M2 阶段：
- 三层 scope：working（进程内）/ session（SQLite，TTL）/ project（持久）
  user 层 M3+ 再加（跨项目偏好）
- 三类 kind：episodic（事件流）/ semantic（事实卡片）/ procedural（解题套路）
- 衰减打分：score = importance × decay(recency) × log(1 + hits)
- 回流 Reflux：每轮对话开始前 top-k 注入 system prompt 段

存储抽象：MemoryStore 协议 + SqliteMemoryStore 实现，未来 LanceDB 向量召回
切换不影响调用方。
"""

from core.memory.models import Memory, MemoryKind, MemoryScope
from core.memory.reflux import refluxed_fragment
from core.memory.store.base import MemoryStore
from core.memory.store.sqlite import SqliteMemoryStore

__all__ = [
    "Memory",
    "MemoryKind",
    "MemoryScope",
    "MemoryStore",
    "SqliteMemoryStore",
    "refluxed_fragment",
]
