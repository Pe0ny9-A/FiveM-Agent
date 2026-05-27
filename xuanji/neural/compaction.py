"""上下文自动压缩。

当 history 估算 token 超阈值时，把"最早的若干轮 user/assistant 对话"折叠成一段
精简摘要，留住末尾的最近 N 轮原文。摘要写到第一条 user 消息之前的合成消息里，
压缩点之后的历史保持原样不动。

设计取舍：
- **规则启发式打分挑重点**（1.2.0）：每条消息按 (a) 工具调用次数 (b) 文本长度
  (c) 被后续 user/assistant 引用次数 三维加权，分高的消息保留原文摘要长度，
  分低的只留首段或干脆丢弃。**不调 LLM 做摘要**，零依赖、零额外 token。
  M5+ 想升级成"用 Haiku/Flash 做摘要"时只需替换 `_summarize_pair`。
- **保留尾部 keep_recent_turns 轮**：默认 4 轮，最近的对话原样保留，确保模型
  仍能看到最新意图与工具结果。
- **token 估算用 4 char ≈ 1 token**：足够用于触发判定，不引入 tokenizer 依赖。

阈值与开关由 [`CompactionConfig`](compaction.py) 描述，由调用方注入到
[`Conductor`](conductor.py)。
"""

from __future__ import annotations

import json
import re
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
    """单轮压缩后**最高**保留多少字符的文本预览。低分消息会被进一步压短。"""

    importance_high_threshold: float = 0.7
    """打分 ≥ 这个阈值算"高分"，原样保留 summary_per_turn_chars 字符。"""

    importance_low_threshold: float = 0.25
    """打分 ≤ 这个阈值算"低分"，只留 60 字摘要。低于这个但有工具调用仍会保留摘要。"""

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


def _msg_text(m: Message) -> str:
    """把消息所有可见文本拼成一串，给打分函数用。"""
    if isinstance(m.content, str):
        return m.content
    parts: list[str] = []
    for b in m.content:
        if isinstance(b, TextBlock):
            parts.append(b.text)
        elif isinstance(b, ToolResultBlock):
            parts.append(b.output)
    return " ".join(parts)


def _msg_tool_calls(m: Message) -> list[ToolCallBlock]:
    if isinstance(m.content, str):
        return []
    return [b for b in m.content if isinstance(b, ToolCallBlock)]


_KEYWORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_:.]{2,}|[一-鿿]{3,}")


def _keywords(text: str) -> set[str]:
    """从消息文本里抽出标识符 + 中文短语作为引用判据。"""
    return {m.group(0) for m in _KEYWORD_RE.finditer(text)}


def score_message(
    msg: Message,
    *,
    later_messages: list[Message],
    max_text_chars: int = 2000,
) -> float:
    """规则启发式打分：返回 0..1。越高越值得保留原文。

    维度（加权后归一到 0..1）：
    - tool_call_weight：消息含工具调用 → +0.35。tool result（角色 tool）也算
    - long_text_weight：文本长度 0..max_text_chars → 线性映射 0..0.30
    - reference_weight：消息里抽出的关键词被 later_messages 引用过 → +0.35

    Why: 工具调用通常是"事件性证据"，不能丢；长 prompt 往往含约束/规范；
    被后续轮引用的关键词意味着这条仍在话题里。
    """
    score = 0.0
    text = _msg_text(msg)

    if _msg_tool_calls(msg) or msg.role == "tool":
        score += 0.35

    text_len = min(len(text), max_text_chars)
    score += 0.30 * (text_len / max_text_chars) if max_text_chars else 0

    # 引用计数：关键词被后续消息提到的比例
    kws = _keywords(text)
    if kws and later_messages:
        later_blob = " ".join(_msg_text(m) for m in later_messages)
        hit = sum(1 for k in kws if k in later_blob)
        ratio = hit / max(1, len(kws))
        score += 0.35 * min(1.0, ratio * 2)  # 命中一半就拉满

    return min(1.0, score)


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
    - 达阈值：把切点之前的所有消息按规则启发式打分摘要、折叠成一条 user 消息
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

    summary_lines: list[str] = ["[历史摘要——按规则启发式打分挑选要点]"]
    high_limit = config.summary_per_turn_chars
    low_limit = max(40, high_limit // 4)
    for i, m in enumerate(head):
        # later_messages 包括 head 后续 + 整段 tail
        later = head[i + 1:] + tail
        s = score_message(m, later_messages=later)

        if s >= config.importance_high_threshold:
            limit = high_limit
            tag = "★"
        elif s <= config.importance_low_threshold and not _msg_tool_calls(m):
            # 低分且无工具调用——直接跳过
            continue
        else:
            limit = low_limit
            tag = "·"

        preview = _msg_preview(m, limit)
        if not preview:
            continue
        prefix = {"user": "小宝", "assistant": "姐姐", "tool": "工具"}.get(m.role, m.role)
        summary_lines.append(f"{tag} {prefix}：{preview}")
    summary = "\n".join(summary_lines)

    compacted: list[Message] = [Message(role="user", content=summary), *tail]
    after_tokens = estimate_tokens(compacted)
    savings = max(0, before_tokens - after_tokens)
    return compacted, savings


__all__ = [
    "CompactionConfig",
    "compact_history",
    "estimate_tokens",
    "score_message",
]
