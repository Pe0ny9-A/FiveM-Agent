"""KnowledgeStore 协议。

实现要点：
- search 跨命名空间或单命名空间的混合召回；M1 用 FTS5，M2+ 接 LanceDB
- lookup_symbol 精准匹配 Symbol 全限定名
- 返回 SearchHit（统一壳），调用方拿 chunk + score 即可

M3 增加：
- attach_vector_index：可选的向量索引侧挂载
- hybrid_search：FTS5 关键词 + 向量语义 RRF 融合
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from core.knowledge.models import Chunk, Namespace, Source, Symbol


class SearchHit(BaseModel):
    """检索命中的统一封装。"""

    chunk: Chunk
    score: float
    matched_symbol: Symbol | None = None
    source: str = "fts"  # 'fts' | 'vector' | 'hybrid'


class KnowledgeStore(Protocol):
    """知识库存储协议。"""

    def upsert_source(self, source: Source) -> None: ...

    def upsert_chunks(self, chunks: list[Chunk]) -> None: ...

    def upsert_symbols(self, symbols: list[Symbol]) -> None: ...

    def search(
        self,
        query: str,
        *,
        namespaces: list[Namespace] | None = None,
        k: int = 8,
    ) -> list[SearchHit]: ...

    def lookup_symbol(
        self,
        name: str,
        *,
        namespaces: list[Namespace] | None = None,
    ) -> list[Symbol]: ...

    def list_sources(self) -> list[Source]: ...

    def list_namespaces(self) -> list[Namespace]: ...

    def stats(self) -> dict[str, Any]: ...

    def clear_namespace(self, namespace: Namespace) -> int: ...
