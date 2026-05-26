"""上下文自动压缩单测。"""

from __future__ import annotations

from xuanji.llm.providers.base import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from xuanji.neural.compaction import (
    CompactionConfig,
    compact_history,
    estimate_tokens,
)


def test_estimate_tokens_string_content() -> None:
    msgs = [Message(role="user", content="a" * 400)]
    assert estimate_tokens(msgs) == 100


def test_estimate_tokens_blocks() -> None:
    msgs = [
        Message(
            role="assistant",
            content=[
                TextBlock(text="a" * 400),
                ThinkingBlock(text="b" * 400),
            ],
        ),
    ]
    # 800 chars / 4 = 200
    assert estimate_tokens(msgs) == 200


def test_compact_disabled_returns_history_as_is() -> None:
    cfg = CompactionConfig(enabled=False, max_context_tokens=10)
    msgs = [Message(role="user", content="x" * 1000)]
    out, savings = compact_history(msgs, cfg)
    assert out is msgs
    assert savings == 0


def test_compact_under_threshold_no_change() -> None:
    cfg = CompactionConfig(max_context_tokens=10_000)
    msgs = [Message(role="user", content="hello")]
    out, savings = compact_history(msgs, cfg)
    assert out == msgs
    assert savings == 0


def test_compact_keeps_recent_turns() -> None:
    """超阈值时，应只保留末尾 keep_recent_turns 轮 user 之后的消息。"""
    cfg = CompactionConfig(
        max_context_tokens=100,  # 故意很低，强制触发
        keep_recent_turns=2,
    )
    # 6 轮 user 对话，每条 800 字符（200 token）
    msgs: list[Message] = []
    for i in range(6):
        msgs.append(Message(role="user", content=f"q{i} " + "x" * 800))
        msgs.append(Message(role="assistant", content=f"a{i} " + "y" * 800))
    out, savings = compact_history(msgs, cfg)
    # 切点在第 5 轮（倒数第 2 个 user）= index 8
    # 保留第 5、6 两轮原文，前面折叠成一条 user 摘要
    assert savings > 0
    assert out[0].role == "user"
    assert isinstance(out[0].content, str)
    assert "[历史摘要" in out[0].content
    # 末尾两轮应原样
    assert out[-1].role == "assistant"
    assert isinstance(out[-1].content, str) and out[-1].content.startswith("a5 ")


def test_compact_summary_drops_thinking_blocks() -> None:
    """ThinkingBlock 不进摘要——下一轮 reasoning 模型会重新生成。"""
    cfg = CompactionConfig(max_context_tokens=50, keep_recent_turns=1)
    msgs = [
        Message(role="user", content="q1 " + "x" * 400),
        Message(
            role="assistant",
            content=[
                ThinkingBlock(text="不该出现的思维链"),
                TextBlock(text="a1 normal"),
            ],
        ),
        Message(role="user", content="q2 latest"),
    ]
    out, _ = compact_history(msgs, cfg)
    summary = out[0].content
    assert isinstance(summary, str)
    assert "不该出现的思维链" not in summary
    assert "a1 normal" in summary


def test_compact_summary_marks_tool_calls() -> None:
    cfg = CompactionConfig(max_context_tokens=50, keep_recent_turns=1)
    msgs = [
        Message(role="user", content="q1 " + "x" * 400),
        Message(
            role="assistant",
            content=[
                TextBlock(text="读一下"),
                ToolCallBlock(id="t1", name="read_file", args={"path": "a.lua"}),
            ],
        ),
        Message(
            role="tool",
            content=[ToolResultBlock(tool_call_id="t1", output="file content")],
        ),
        Message(role="user", content="q2 latest"),
    ]
    out, _ = compact_history(msgs, cfg)
    summary = out[0].content
    assert isinstance(summary, str)
    assert "read_file" in summary
    assert "file content" in summary


def test_compact_no_split_when_too_few_turns() -> None:
    """user 消息少于 keep_recent_turns + 1 时即使超阈值也不应折叠。"""
    cfg = CompactionConfig(
        max_context_tokens=10,  # 极低
        keep_recent_turns=4,
    )
    msgs = [
        Message(role="user", content="q1 " + "x" * 800),
        Message(role="assistant", content="a1 " + "y" * 800),
    ]
    out, savings = compact_history(msgs, cfg)
    assert out == msgs
    assert savings == 0
