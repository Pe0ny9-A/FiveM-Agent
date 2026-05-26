"""知识库存储实现。"""

from xuanji.knowledge.store.base import KnowledgeStore, SearchHit
from xuanji.knowledge.store.sqlite_fts import SqliteKnowledgeStore

__all__ = ["KnowledgeStore", "SearchHit", "SqliteKnowledgeStore"]
