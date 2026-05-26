"""数据源采集器。M1 阶段只有 seeds，M2+ 加 crawler / git ingest。"""

from xuanji.knowledge.sources.seeds import seed_chunks, seed_sources, seed_symbols

__all__ = ["seed_chunks", "seed_sources", "seed_symbols"]
