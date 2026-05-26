"""上下文自动压缩。

当 history 估算 token 超阈值时，把"最早的若干轮 user/assistant 对话"折叠成一段
精简摘要，留住末尾的最近 N 轮原文。摘要写到第一条 user 消息之前的合成消息里，
压缩点之后的历史保持原样不动。

设计取舍：
- **不调 LLM 做摘要**：第一版用规则提取（保留每轮文本前 240 字 + 工具调用名清单），
  零依赖、不引入额外 token 成本，且在 reasoning 模型链上不会触发新一轮思考。
  M5+ 想升级成"用 Haiku/Flash 做摘要"时只需替换 `_summarize_pair`。
- **保留尾部 keep_recent_turns 轮**：默认 4 轮，最近的对话原样保留，确保模型
  仍能看到最新意图与工具结果。
- **token 估算用 4 char ≈ 1 token**：足够用于触发判定，不引入 tokenizer 依赖。

阈值与开关由 [`CompactionConfig`](compaction.py) 描述，由调用方注入到
[`Conductor`](conductor.py)。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from xuanji.llm.providers.base import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)


class CompactionConfig(BaseModel):
    """上下文自动压缩配置。"""

    enabled: bool = True
    """是否启用自动压缩。关掉等同于 0.5 之前的行为。"""

    max_context_tokens: int = 80_000
    """触发压缩的 token 阈值。估算值，按 4 字符 1 token 折算。
    Claude/GPT-5/DeepSeek 大都 ≥128k，留 30%+ 给当前轮 + system + tools。"""

    keep_recent_turns: int = 4
    """从末尾保留多少轮原文不压缩。一轮 = 一条 user + 后续 assistant/tool 序列。"""

    summary_per_turn_chars: int = 240
    """单轮压缩后保留多少字符的文本预览。"""

    @property
    def max_context_chars(self) -> int:
        return self.max_context_tokens * 4


def estimate_tokens(messages: list[Message]) -> int:
    """估算消息列表的 token 数。粗略 4 char ≈ 1 token。"""
    chars = 0
    for m in messages:
        if isinstance(m.content, str):
            chars += len(m.content)
            continue
        for b in m.content:
            if isinstance(b, TextBlock | ThinkingBlock):
                chars += len(b.text)
            elif isinstance(b, ToolCallBlock):
                chars += len(b.name) + len(json.dumps(b.args, ensure_ascii=False))
            elif isinstance(b, ToolResultBlock):
                chars += len(b.output)
    return chars // 4


def _block_text_preview(b: Any, limit: int) -> str:
    if isinstance(b, TextBlock):
        return b.text[:limit]
    if isinstance(b, ThinkingBlock):
        return ""  # 思维链不进摘要——下一轮 reasoning 模型会重新生成
    if isinstance(b, ToolCallBlock):
        return f"[调用工具 {b.name}]"
    if isinstance(b, ToolResultBlock):
        out = b.output if not b.is_error else f"ERROR: {b.output}"
        return f"[结果] {out[:limit]}"
    return ""


def _msg_preview(m: Message, limit: int) -> str:
    if isinstance(m.content, str):
        return m.content[:limit]
    parts: list[str] = []
    for b in m.content:
        piece = _block_text_preview(b, limit)
        if piece:
            parts.append(piece)
    return " ".join(parts)[: limit * 2]


def _find_safe_split(history: list[Message], keep_recent_turns: int) -> int:
    """从末尾倒数 keep_recent_turns 个 user 消息处切。返回切点 index。

    切点必须落在 user 消息上——避免把 assistant 的 tool_call 与 tool 结果劈成两半。
    """
    user_indices = [i for i, m in enumerate(history) if m.role == "user"]
    if len(user_indices) <= keep_recent_turns:
        return 0
    return user_indices[-keep_recent_turns]


def compact_history(
    history: list[Message],
    config: CompactionConfig,
) -> tuple[list[Message], int]:
    """对 history 做自动压缩。返回 (新历史, 估算节省的 token 数)。

    - 不达阈值：原样返回，savings=0
    - 达阈值：把切点之前的所有消息折叠成一条 user 消息（带"以下是历史摘要"标记）
    """
    if not config.enabled:
        return history, 0
    before_tokens = estimate_tokens(history)
    if before_tokens <= config.max_context_tokens:
        return history, 0

    split_at = _find_safe_split(history, config.keep_recent_turns)
    if split_at <= 0:
        return history, 0

    head = history[:split_at]
    tail = history[split_at:]

    summary_lines: list[str] = ["[历史摘要——之前的对话已折叠以节省 token]"]
    for m in head:
        preview = _msg_preview(m, config.summary_per_turn_chars)
        if not preview:
            continue
        prefix = {"user": "小宝", "assistant": "姐姐", "tool": "工具"}.get(m.role, m.role)
        summary_lines.append(f"- {prefix}：{preview}")
    summary = "\n".join(summary_lines)

    compacted: list[Message] = [Message(role="user", content=summary), *tail]
    after_tokens = estimate_tokens(compacted)
    savings = max(0, before_tokens - after_tokens)
    return compacted, savings


__all__ = [
    "CompactionConfig",
    "compact_history",
    "estimate_tokens",
]
