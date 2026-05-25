"""LLM 抽象层单测。验证 Pydantic 模型与 Anthropic 转换器。

不依赖真实 API key，只测纯结构与转换逻辑。
"""

from __future__ import annotations

import pytest

from core.llm import AssistantMessage, Delta, Message, TextBlock, ToolCallBlock, Usage
from core.llm.providers.anthropic import _to_anthropic_messages


def test_message_str_content() -> None:
    """字符串 content 是便利写法，应正常构造。"""
    m = Message(role="user", content="QBCore 怎么加物品")
    assert m.role == "user"
    assert m.content == "QBCore 怎么加物品"


def test_message_block_content() -> None:
    """结构化 content 应支持 TextBlock + ToolCallBlock 混合。"""
    m = Message(
        role="assistant",
        content=[
            TextBlock(text="姐姐先看看仓库结构"),
            ToolCallBlock(id="t1", name="list_dir", args={"path": "."}),
        ],
    )
    assert isinstance(m.content, list)
    assert len(m.content) == 2


def test_assistant_message_text_property() -> None:
    """text 属性应只拼接 TextBlock，忽略 ToolCallBlock。"""
    am = AssistantMessage(
        blocks=[
            TextBlock(text="先读 fxmanifest。"),
            ToolCallBlock(id="t1", name="read_file", args={"path": "fxmanifest.lua"}),
            TextBlock(text="再看一下 server 端。"),
        ],
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=20),
        model="claude-sonnet-4-6",
    )
    assert am.text == "先读 fxmanifest。再看一下 server 端。"


def test_delta_event_types() -> None:
    """Delta 应支持文本、工具、思维链三类的 start/delta/end + message_done。"""
    valid_types = [
        "text_start", "text_delta", "text_end",
        "tool_call_start", "tool_call_delta", "tool_call_end",
        "thinking_start", "thinking_delta", "thinking_end",
        "message_done",
    ]
    for t in valid_types:
        d = Delta(type=t)  # type: ignore[arg-type]
        assert d.type == t


def test_to_anthropic_rejects_system_in_messages() -> None:
    """system 必须通过独立参数传，不能混在 messages 里。"""
    msgs = [Message(role="system", content="你是玄玑")]
    with pytest.raises(ValueError, match="system 消息"):
        _to_anthropic_messages(msgs)


def test_to_anthropic_string_content() -> None:
    """字符串 content 应原样透传。"""
    msgs = [Message(role="user", content="hello")]
    out = _to_anthropic_messages(msgs)
    assert out == [{"role": "user", "content": "hello"}]


def test_to_anthropic_block_content() -> None:
    """块列表应转成 anthropic 期望的 dict 列表。"""
    msgs = [
        Message(
            role="assistant",
            content=[
                TextBlock(text="读一下"),
                ToolCallBlock(id="t1", name="read_file", args={"path": "a.lua"}),
            ],
        ),
    ]
    out = _to_anthropic_messages(msgs)
    assert len(out) == 1
    assert out[0]["role"] == "assistant"
    blocks = out[0]["content"]
    assert isinstance(blocks, list)
    assert blocks[0] == {"type": "text", "text": "读一下"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "read_file",
        "input": {"path": "a.lua"},
    }
