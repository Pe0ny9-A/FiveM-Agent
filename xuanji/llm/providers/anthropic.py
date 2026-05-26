"""Anthropic Provider 实现。

将 Anthropic SDK 的事件流（content_block_start / content_block_delta /
content_block_stop / message_delta / message_stop）归一化为 core.llm 的
Delta 事件流。文本/工具/思维链三种块都覆盖。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic import types as anth

from xuanji.llm.providers.base import (
    AssistantMessage,
    ContentBlock,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)

_CAPABILITIES: dict[str, ModelCapabilities] = {
    "claude-opus-4-7": ModelCapabilities(
        name="claude-opus-4-7",
        provider="anthropic",
        context_window=200_000,
        max_output_tokens=32_000,
        supports_thinking=True,
        supports_prompt_cache=True,
        supports_vision=True,
        cn_quality="high",
        cost_input_per_mtok=15.0,
        cost_output_per_mtok=75.0,
    ),
    "claude-sonnet-4-6": ModelCapabilities(
        name="claude-sonnet-4-6",
        provider="anthropic",
        context_window=200_000,
        max_output_tokens=16_000,
        supports_thinking=True,
        supports_prompt_cache=True,
        supports_vision=True,
        cn_quality="high",
        cost_input_per_mtok=3.0,
        cost_output_per_mtok=15.0,
    ),
    "claude-haiku-4-5-20251001": ModelCapabilities(
        name="claude-haiku-4-5-20251001",
        provider="anthropic",
        context_window=200_000,
        max_output_tokens=8_192,
        supports_thinking=False,
        supports_prompt_cache=True,
        supports_vision=True,
        cn_quality="high",
        cost_input_per_mtok=1.0,
        cost_output_per_mtok=5.0,
    ),
}


def _to_anthropic_messages(messages: Sequence[Message]) -> list[anth.MessageParam]:
    """把统一 Message 转成 Anthropic SDK 入参格式。

    Anthropic 的 system 是独立参数，不能放在 messages 里，调用前应已剥离。
    role="tool" 的工具结果消息会被翻译成 role=user 的 tool_result 块——
    这是 Anthropic 官方约定的工具结果回传方式。
    """
    out: list[anth.MessageParam] = []
    for m in messages:
        if m.role == "system":
            raise ValueError("system 消息应通过 system 参数传入，不能放进 messages")
        if isinstance(m.content, str):
            out.append({"role": cast(Any, m.role), "content": m.content})
            continue

        # role="tool" → role=user 包 tool_result 块
        if m.role == "tool":
            tool_blocks: list[dict[str, Any]] = []
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    tool_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.tool_call_id,
                            "content": b.output,
                            "is_error": b.is_error,
                        },
                    )
            out.append({"role": "user", "content": cast(Any, tool_blocks)})
            continue

        anth_blocks: list[dict[str, Any]] = []
        for b in m.content:
            if isinstance(b, TextBlock):
                anth_blocks.append({"type": "text", "text": b.text})
            elif isinstance(b, ToolCallBlock):
                anth_blocks.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.args},
                )
            elif isinstance(b, ThinkingBlock):
                anth_blocks.append({"type": "thinking", "thinking": b.text})
        out.append({"role": cast(Any, m.role), "content": cast(Any, anth_blocks)})
    return out


def _from_anthropic_message(msg: anth.Message) -> AssistantMessage:
    blocks: list[ContentBlock] = []
    for b in msg.content:
        if isinstance(b, anth.TextBlock):
            blocks.append(TextBlock(text=b.text))
        elif isinstance(b, anth.ToolUseBlock):
            blocks.append(
                ToolCallBlock(id=b.id, name=b.name, args=cast(dict[str, Any], b.input)),
            )
        elif isinstance(b, anth.ThinkingBlock):
            blocks.append(ThinkingBlock(text=b.thinking))
    stop_reason_map = {
        "end_turn": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
    }
    stop_reason = stop_reason_map.get(msg.stop_reason or "", "end_turn")
    usage = Usage(
        input_tokens=msg.usage.input_tokens,
        output_tokens=msg.usage.output_tokens,
        cache_read_tokens=getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
    )
    return AssistantMessage(
        blocks=blocks,
        stop_reason=cast(Any, stop_reason),
        usage=usage,
        model=msg.model,
    )


class AnthropicProvider(LLMProvider):
    """Anthropic Claude Provider。"""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    def capabilities(self, model: str) -> ModelCapabilities:
        if model in _CAPABILITIES:
            return _CAPABILITIES[model]
        # 未登记的模型先按 Sonnet 默认值兜底，便于试用新模型时不报错
        return _CAPABILITIES["claude-sonnet-4-6"].model_copy(update={"name": model})

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: Sequence[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> AssistantMessage:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = list(tools)
        kwargs.update(extra)
        msg = await self._client.messages.create(**kwargs)
        return _from_anthropic_message(msg)

    async def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: Sequence[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> AsyncIterator[Delta]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = list(tools)
        kwargs.update(extra)

        # 块索引 → 累积的 args JSON 字符串（仅 tool_use 块用）
        tool_args_buf: dict[int, str] = {}
        # 块索引 → 块类型，用于在 stop 时分发正确的 *_end 事件
        block_kind: dict[int, str] = {}

        async with self._client.messages.stream(**kwargs) as stream:
            async for raw_event in stream:
                # SDK 的事件是大 union 类型，mypy strict 下访问字段会引发数十条
                # union-attr 误报。运行时我们用 etype 字符串守卫保证字段存在，
                # 因此在循环内整体 cast 为 Any 是最干净的处理。
                event: Any = raw_event
                etype = event.type
                if etype == "content_block_start":
                    cb = event.content_block
                    idx = event.index
                    if cb.type == "text":
                        block_kind[idx] = "text"
                        yield Delta(type="text_start", index=idx)
                    elif cb.type == "tool_use":
                        block_kind[idx] = "tool_use"
                        tool_args_buf[idx] = ""
                        yield Delta(
                            type="tool_call_start",
                            index=idx,
                            tool_call_id=cb.id,
                            tool_name=cb.name,
                        )
                    elif cb.type == "thinking":
                        block_kind[idx] = "thinking"
                        yield Delta(type="thinking_start", index=idx)
                elif etype == "content_block_delta":
                    idx = event.index
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield Delta(type="text_delta", index=idx, text=delta.text)
                    elif delta.type == "input_json_delta":
                        tool_args_buf[idx] = tool_args_buf.get(idx, "") + delta.partial_json
                        yield Delta(
                            type="tool_call_delta",
                            index=idx,
                            args_json_chunk=delta.partial_json,
                        )
                    elif delta.type == "thinking_delta":
                        yield Delta(type="thinking_delta", index=idx, text=delta.thinking)
                elif etype == "content_block_stop":
                    idx = event.index
                    kind = block_kind.get(idx)
                    if kind == "text":
                        yield Delta(type="text_end", index=idx)
                    elif kind == "tool_use":
                        raw = tool_args_buf.pop(idx, "") or "{}"
                        try:
                            args_final = json.loads(raw)
                        except json.JSONDecodeError:
                            args_final = {}
                        yield Delta(
                            type="tool_call_end",
                            index=idx,
                            args_final=args_final,
                        )
                    elif kind == "thinking":
                        yield Delta(type="thinking_end", index=idx)
                elif etype == "message_stop":
                    final = await stream.get_final_message()
                    usage = Usage(
                        input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens,
                        cache_read_tokens=getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                        cache_write_tokens=getattr(final.usage, "cache_creation_input_tokens", 0)
                        or 0,
                    )
                    yield Delta(
                        type="message_done",
                        stop_reason=final.stop_reason,
                        usage=usage,
                    )
