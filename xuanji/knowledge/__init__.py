"""稷下学宫 · 知识系统。

M1 阶段先用 SQLite FTS5 全文检索打通采集 → 索引 → 工具调用全链路。
向量检索（LanceDB）通过 KnowledgeStore 协议留接口，M2+ 切换不影响调用方。

数据模型：
- Source：一个知识来源，带版本号（如 fivem.qbcore@1.x）
- Chunk：源文档切分后的文本片段，是检索的最小单位
- Symbol：API/事件/native 的结构化卡片（QBCore.Functions.X / lib.callback.register）
- KnowledgeStore：检索协议，FTS5 实现 / 未来 LanceDB 实现各自满足
"""

from xuanji.knowledge.models import Chunk, Source, Symbol
from xuanji.knowledge.store.base import KnowledgeStore, SearchHit
from xuanji.knowledge.store.sqlite_fts import SqliteKnowledgeStore
from xuanji.knowledge.vector import (
    Embedder,
    HashingEmbedder,
    InMemoryVectorStore,
    LanceDBVectorStore,
    VectorHit,
    VectorStore,
)

__all__ = [
    "Chunk",
    "Embedder",
    "HashingEmbedder",
    "InMemoryVectorStore",
    "KnowledgeStore",
    "LanceDBVectorStore",
    "SearchHit",
    "Source",
    "SqliteKnowledgeStore",
    "Symbol",
    "VectorHit",
    "VectorStore",
]
