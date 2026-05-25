"""MemoryStore 协议。

设计原则：
- write/recall 是同步接口（SQLite 不需要 async；M3+ 接向量库再考虑 async）
- recall 返回按 score 倒序的 Memory 列表，调用方决定取多少
- forget 是显式清理；衰减只是排序权重，不会自动删除
- consolidate 把 episodic 摘要为 semantic（M2 用"按 namespace 取 top-N"的简单实现）
"""

from __future__ import annotations

from typing import Any, Protocol

from core.memory.models import Memory, MemoryKind, MemoryScope


class MemoryStore(Protocol):
    """记忆库协议。"""

    def write(self, memory: Memory) -> Memory: ...

    def recall(
        self,
        query: str,
        *,
        scopes: list[MemoryScope] | None = None,
        kinds: list[MemoryKind] | None = None,
        namespace: str | None = None,
        k: int = 8,
    ) -> list[Memory]: ...

    def get(self, id_: str) -> Memory | None: ...

    def list_by_namespace(
        self,
        namespace: str,
        *,
        scopes: list[MemoryScope] | None = None,
        kinds: list[MemoryKind] | None = None,
        limit: int = 50,
    ) -> list[Memory]: ...

    def forget(
        self,
        *,
        ids: list[str] | None = None,
        namespace: str | None = None,
        scope: MemoryScope | None = None,
    ) -> int: ...

    def consolidate(self, namespace: str, *, max_kept: int = 100) -> int:
        """把 namespace 里 episodic 累积过多时按 importance 截断。

        返回被删除的条数。M2 是简化实现；M3+ 加 LLM 摘要。
        """
        ...

    def stats(self) -> dict[str, Any]: ...
