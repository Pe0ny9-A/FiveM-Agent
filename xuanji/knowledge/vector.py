"""向量检索抽象层 + 内存版实现。

设计：
- EmbedderProtocol：把字符串映射成定长向量。M3 先做 HashingEmbedder
  （局部敏感哈希式）保证零依赖；M4+ 接 sentence-transformers / Voyage / 远程 API
- VectorStore 协议：upsert / search / delete / size
- InMemoryVectorStore：Python list 实现 + 余弦相似度，单测可用
- LanceDBVectorStore：M4+ 接真实 LanceDB（仅留 stub class 与文档说明）
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Protocol

VECTOR_DIM = 256
"""默认向量维度。HashingEmbedder 用，真实嵌入模型替换时按其 dim 配。"""


class Embedder(Protocol):
    """字符串 → 向量。"""

    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class VectorHit:
    """检索命中项。

    用普通类而非 pydantic：向量库返回大量候选，pydantic 校验开销不必要。
    """

    __slots__ = ("id", "metadata", "score")

    def __init__(self, id_: str, score: float, metadata: dict[str, Any]) -> None:
        self.id = id_
        self.score = score
        self.metadata = metadata


class VectorStore(Protocol):
    """向量存储协议。"""

    name: str
    dim: int

    def upsert(
        self, id_: str, vector: list[float], metadata: dict[str, Any] | None = None
    ) -> None: ...

    def upsert_batch(self, items: list[tuple[str, list[float], dict[str, Any]]]) -> None: ...

    def search(
        self, vector: list[float], *, k: int = 8, filter_namespace: str | None = None
    ) -> list[VectorHit]: ...

    def delete(self, id_: str) -> bool: ...

    def delete_namespace(self, namespace: str) -> int: ...

    def size(self) -> int: ...


# ============================================================
# HashingEmbedder：零依赖、确定性、跨进程一致的"近似嵌入"
# ============================================================


class HashingEmbedder:
    """用多个 SHA-1 hash 函数把 token 哈希到 dim 维向量，模拟 LSH。

    显然不如真实语义嵌入——但保证：
    - 单测/开发时无需装 sentence-transformers / 不需要联网
    - 同样的输入永远给同样的向量
    - 不同 token 落到不同 bucket，能区分
    - 召回质量明显比 FTS5 关键词差，但这是骨架阶段的占位

    M4+ 用 sentence-transformers 或 Voyage 替换此实现。
    """

    name = "hashing"
    dim = VECTOR_DIM

    def __init__(self, dim: int = VECTOR_DIM) -> None:
        self.dim = dim

    def _tokenize(self, text: str) -> list[str]:
        # 先借 jieba 把中文切词，再按空格 + 单字母 token
        from xuanji.knowledge.tokenize import preprocess_text

        return [t for t in preprocess_text(text.lower()).split() if t]

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in self._tokenize(text):
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            for i in range(self.dim):
                bit = digest[i % len(digest)] >> (i % 8) & 1
                # 用 ±1 分布，模拟 random projection
                vec[i] += 1.0 if bit else -1.0
        # L2 归一化
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ============================================================
# InMemoryVectorStore：纯 Python 实现，开发与单测用
# ============================================================


def _cosine(a: list[float], b: list[float]) -> float:
    """已归一化向量的余弦相似度 = 点积。但保险起见仍除以模。"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """内存版向量存储。线性扫描，不适合 >10万 条目，足够开发用。"""

    name = "inmemory"

    def __init__(self, dim: int = VECTOR_DIM) -> None:
        self.dim = dim
        self._records: dict[str, tuple[list[float], dict[str, Any]]] = {}

    def upsert(
        self, id_: str, vector: list[float], metadata: dict[str, Any] | None = None
    ) -> None:
        if len(vector) != self.dim:
            raise ValueError(f"向量维度不匹配：{len(vector)} != {self.dim}")
        self._records[id_] = (list(vector), dict(metadata or {}))

    def upsert_batch(
        self, items: list[tuple[str, list[float], dict[str, Any]]]
    ) -> None:
        for id_, vec, meta in items:
            self.upsert(id_, vec, meta)

    def search(
        self,
        vector: list[float],
        *,
        k: int = 8,
        filter_namespace: str | None = None,
    ) -> list[VectorHit]:
        if len(vector) != self.dim:
            raise ValueError(f"查询向量维度不匹配：{len(vector)} != {self.dim}")
        scored: list[VectorHit] = []
        for id_, (vec, meta) in self._records.items():
            if filter_namespace is not None and meta.get("namespace") != filter_namespace:
                continue
            score = _cosine(vector, vec)
            scored.append(VectorHit(id_=id_, score=score, metadata=meta))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def delete(self, id_: str) -> bool:
        return self._records.pop(id_, None) is not None

    def delete_namespace(self, namespace: str) -> int:
        doomed = [
            i for i, (_, m) in self._records.items() if m.get("namespace") == namespace
        ]
        for i in doomed:
            del self._records[i]
        return len(doomed)

    def size(self) -> int:
        return len(self._records)


# ============================================================
# LanceDB 实装：本地嵌入式向量库，零运维
# ============================================================


class LanceDBVectorStore:
    """LanceDB 实装。

    使用嵌入式模式（无服务端进程），数据落盘到 `db_path` 目录。
    schema: (id TEXT, vector FixedSizeList<float32, dim>, namespace TEXT, metadata JSON_TEXT)

    设计要点：
    - 表延迟创建：第一次 upsert 才建表，避免空库就占用句柄
    - upsert 语义：用 merge_insert 按 id 主键 upsert
    - search 默认按 L2 距离，转 score = 1 / (1 + dist) 让"越大越相关"
    - delete_namespace 走 SQL DELETE，O(命中行数)
    - lancedb / pyarrow 是 optional 依赖（vector extra），import 延迟到首次实例化
    """

    name = "lancedb"

    def __init__(
        self,
        db_path: str,
        table: str = "knowledge",
        dim: int = VECTOR_DIM,
    ) -> None:
        try:
            import lancedb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "LanceDBVectorStore 需要 vector extra：uv sync --extra vector",
            ) from e

        self.dim = dim
        self._db_path = db_path
        self._table_name = table
        self._db: Any = None
        self._table: Any = None

    def _connect(self) -> Any:
        if self._db is None:
            import lancedb
            self._db = lancedb.connect(self._db_path)
        return self._db

    def _schema(self) -> Any:
        import pyarrow as pa
        return pa.schema([
            ("id", pa.string()),
            ("vector", pa.list_(pa.float32(), self.dim)),
            ("namespace", pa.string()),
            ("metadata", pa.string()),
        ])

    def _ensure_table(self) -> Any:
        if self._table is not None:
            return self._table
        db = self._connect()
        try:
            self._table = db.open_table(self._table_name)
        except (FileNotFoundError, ValueError):
            self._table = db.create_table(self._table_name, schema=self._schema())
        return self._table

    @staticmethod
    def _meta_dump(metadata: dict[str, Any]) -> str:
        import json
        return json.dumps(metadata or {}, ensure_ascii=False)

    @staticmethod
    def _meta_load(text: str) -> dict[str, Any]:
        import json
        if not text:
            return {}
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return obj if isinstance(obj, dict) else {}

    def upsert(
        self, id_: str, vector: list[float], metadata: dict[str, Any] | None = None
    ) -> None:
        if len(vector) != self.dim:
            raise ValueError(f"向量维度不匹配：{len(vector)} != {self.dim}")
        self.upsert_batch([(id_, vector, dict(metadata or {}))])

    def upsert_batch(
        self, items: list[tuple[str, list[float], dict[str, Any]]]
    ) -> None:
        if not items:
            return
        for _, vec, _meta in items:
            if len(vec) != self.dim:
                raise ValueError(f"向量维度不匹配：{len(vec)} != {self.dim}")
        table = self._ensure_table()
        rows = [
            {
                "id": id_,
                "vector": list(vec),
                "namespace": str(meta.get("namespace") or ""),
                "metadata": self._meta_dump(meta),
            }
            for id_, vec, meta in items
        ]
        table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)

    def search(
        self,
        vector: list[float],
        *,
        k: int = 8,
        filter_namespace: str | None = None,
    ) -> list[VectorHit]:
        if len(vector) != self.dim:
            raise ValueError(f"查询向量维度不匹配：{len(vector)} != {self.dim}")
        table = self._ensure_table()
        q = table.search(list(vector)).limit(k)
        if filter_namespace is not None:
            esc = filter_namespace.replace("'", "''")
            q = q.where(f"namespace = '{esc}'")
        rows = q.to_list()
        hits: list[VectorHit] = []
        for r in rows:
            dist = float(r.get("_distance", 0.0))
            score = 1.0 / (1.0 + dist)
            meta = self._meta_load(r.get("metadata") or "")
            hits.append(VectorHit(id_=r["id"], score=score, metadata=meta))
        return hits

    def delete(self, id_: str) -> bool:
        table = self._ensure_table()
        before = int(table.count_rows())
        esc = id_.replace("'", "''")
        table.delete(f"id = '{esc}'")
        return int(table.count_rows()) < before

    def delete_namespace(self, namespace: str) -> int:
        table = self._ensure_table()
        before = table.count_rows()
        esc = namespace.replace("'", "''")
        table.delete(f"namespace = '{esc}'")
        return int(before - table.count_rows())

    def size(self) -> int:
        table = self._ensure_table()
        return int(table.count_rows())


__all__ = [
    "VECTOR_DIM",
    "Embedder",
    "HashingEmbedder",
    "InMemoryVectorStore",
    "LanceDBVectorStore",
    "VectorHit",
    "VectorStore",
]
