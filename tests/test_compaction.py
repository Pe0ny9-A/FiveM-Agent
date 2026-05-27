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
    score_message,
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
    cfg = CompactionConfig(
        max_context_tokens=50,
        keep_recent_turns=1,
        importance_low_threshold=0.0,  # 关掉低分丢弃，专测 thinking 不进摘要
    )
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


# ============================ 1.2.0 规则启发式打分 ============================


def test_score_message_tool_call_boosts_score() -> None:
    """含工具调用的 assistant 消息应该拿到 +0.35 加成。"""
    plain = Message(role="assistant", content=[TextBlock(text="hello")])
    with_tool = Message(
        role="assistant",
        content=[
            TextBlock(text="hello"),
            ToolCallBlock(id="t1", name="read_file", args={"path": "x"}),
        ],
    )
    s_plain = score_message(plain, later_messages=[])
    s_tool = score_message(with_tool, later_messages=[])
    assert s_tool > s_plain
    assert s_tool >= 0.35


def test_score_message_tool_result_role_also_counts() -> None:
    """tool 角色（即工具结果消息）应等价为含工具调用，拿 +0.35。"""
    msg = Message(
        role="tool",
        content=[ToolResultBlock(tool_call_id="t1", output="a" * 200)],
    )
    s = score_message(msg, later_messages=[])
    assert s >= 0.35


def test_score_message_long_text_increases_score() -> None:
    """长文本应该按线性映射给到 +0.30 上限。"""
    short = Message(role="user", content="hi")
    long = Message(role="user", content="x" * 2000)
    s_short = score_message(short, later_messages=[])
    s_long = score_message(long, later_messages=[])
    assert s_long > s_short
    assert s_long >= 0.30


def test_score_message_reference_by_later_messages() -> None:
    """关键词被后续消息引用应拉高分数。"""
    early = Message(
        role="user",
        content="QBCore.Functions.CreateUseableItem 这个怎么用",
    )
    later_referencing = [
        Message(role="assistant", content="QBCore.Functions.CreateUseableItem 用法是…"),
        Message(role="user", content="QBCore.Functions.CreateUseableItem 还能传第三参数吗"),
    ]
    later_unrelated = [
        Message(role="assistant", content="今天天气真好"),
        Message(role="user", content="再来一个段子"),
    ]
    s_ref = score_message(early, later_messages=later_referencing)
    s_un = score_message(early, later_messages=later_unrelated)
    assert s_ref > s_un


def test_score_message_normalized_under_one() -> None:
    """全维度顶满后归一不应 > 1。"""
    msg = Message(
        role="assistant",
        content=[
            TextBlock(text="QBCore.Functions.CreateUseableItem " * 200),
            ToolCallBlock(id="t1", name="lookup_symbol", args={}),
        ],
    )
    later = [
        Message(role="user", content="QBCore.Functions.CreateUseableItem 再问一次"),
    ] * 5
    s = score_message(msg, later_messages=later)
    assert 0.0 <= s <= 1.0


def test_compact_drops_low_score_messages_without_tool_calls() -> None:
    """低分（短 + 无工具 + 不被引用）的消息应在压缩后被丢弃。"""
    cfg = CompactionConfig(
        max_context_tokens=50,
        keep_recent_turns=1,
        importance_low_threshold=0.5,  # 拉高阈值，强制更多消息算低分
    )
    msgs = [
        Message(role="user", content="q1 " + "x" * 400),
        Message(role="assistant", content="ok"),  # 短 + 无工具 → 低分
        Message(role="user", content="q2 " + "y" * 400),
        Message(role="assistant", content="嗯嗯"),  # 短 + 无工具 → 低分
        Message(role="user", content="q3 latest"),  # 保留尾部
    ]
    out, savings = compact_history(msgs, cfg)
    summary = out[0].content
    assert isinstance(summary, str)
    assert "ok" not in summary
    assert "嗯嗯" not in summary
    assert savings >= 0


def test_compact_keeps_tool_call_messages_even_if_short() -> None:
    """短文本但含工具调用 → 仍应保留摘要。"""
    cfg = CompactionConfig(
        max_context_tokens=50,
        keep_recent_turns=1,
        importance_low_threshold=0.99,  # 几乎所有消息都算低分
    )
    msgs = [
        Message(role="user", content="q1 " + "x" * 400),
        Message(
            role="assistant",
            content=[
                TextBlock(text="读"),
                ToolCallBlock(
                    id="t1", name="critical_tool", args={},
                ),
            ],
        ),
        Message(role="user", content="q2 latest"),
    ]
    out, _ = compact_history(msgs, cfg)
    summary = out[0].content
    assert isinstance(summary, str)
    assert "critical_tool" in summary


def test_compact_high_score_full_preview_marked_with_star() -> None:
    """高分消息应该用 ★ 标记，普通分用 · 标记。"""
    cfg = CompactionConfig(
        max_context_tokens=50,
        keep_recent_turns=1,
        importance_high_threshold=0.3,
        importance_low_threshold=0.0,
    )
    msgs = [
        Message(role="user", content="q1 早期问题"),
        # 长文 + 含工具调用 → 高分
        Message(
            role="assistant",
            content=[
                TextBlock(text="读 fxmanifest.lua " * 200),
                ToolCallBlock(id="t1", name="read_file", args={"path": "x"}),
            ],
        ),
        Message(
            role="tool",
            content=[ToolResultBlock(tool_call_id="t1", output="content " * 200)],
        ),
        Message(role="user", content="latest"),
    ]
    out, _ = compact_history(msgs, cfg)
    summary = out[0].content
    assert isinstance(summary, str)
    assert "★" in summary
