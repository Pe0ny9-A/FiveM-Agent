"""中文分词预处理，给 SQLite FTS5 检索喂"按词切的 token"。

设计：
- jieba 是可选依赖，找不到就直接 passthrough（兼容性）
- preprocess_text 在写入与查询时都过一遍：把连续的中文字串用空格切成词
- 英文 / 数字 / 标点保持不变（jieba 默认会自动跳过）
- 单例 jieba.Tokenizer 共享，避免每次 import 时反复加载词典
"""

from __future__ import annotations

import re
import threading
from typing import Any

# CJK 字符（含全角符号一起匹配上避免边界不齐）
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]+")

_jieba_lock = threading.Lock()
_jieba_tokenizer: Any = None
_jieba_loaded = False
_jieba_available = True


def _ensure_jieba() -> Any:
    """懒加载 jieba。失败时返回 None 永久标记不可用。"""
    global _jieba_tokenizer, _jieba_loaded, _jieba_available
    if _jieba_loaded:
        return _jieba_tokenizer
    with _jieba_lock:
        if _jieba_loaded:
            return _jieba_tokenizer
        try:
            import jieba

            tokenizer = jieba.Tokenizer()
            tokenizer.initialize()
            _jieba_tokenizer = tokenizer
        except (ImportError, OSError):
            _jieba_available = False
        _jieba_loaded = True
    return _jieba_tokenizer


def is_jieba_available() -> bool:
    """供测试与诊断查询。第一次调用会触发懒加载。"""
    _ensure_jieba()
    return _jieba_available


def preprocess_text(text: str) -> str:
    """把中文连续段切成空格分隔的词。

    例：'在 QBCore 项目里加可使用物品' →
        '在 QBCore 项目 里 加 可使用 物品'

    jieba 不可用时退化为按字切。
    """
    if not text:
        return text

    tokenizer = _ensure_jieba()

    def _replace(match: re.Match[str]) -> str:
        chunk = match.group(0)
        if tokenizer is not None:
            words = list(tokenizer.cut(chunk, HMM=True))
            return " ".join(w for w in words if w.strip())
        return " ".join(chunk)

    return _CJK_RE.sub(_replace, text)


__all__ = ["is_jieba_available", "preprocess_text"]
