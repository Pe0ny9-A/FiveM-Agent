"""DeepSeek Provider 实现。

DeepSeek 用 OpenAI Chat Completions 协议，但有三个独门特性必须单独适配，
不能像 0.9 之前那样共用 OpenAIProvider：

1. **thinking 模式必须往返 reasoning_content**：v4-pro / v4-flash / reasoner
   响应里 message.reasoning_content 是独立字段，下一轮回传时也必须把它原样
   写回 assistant message 的 reasoning_content 字段，否则 API 会返回
   `BadRequestError 400 — The reasoning_content in the thinking mode must
   be passed back to the API`。
2. **prompt cache 计量**：usage 里有 prompt_cache_hit_tokens /
   prompt_cache_miss_tokens，对应 Usage.cache_read_tokens（命中部分实际
   只按 0.1 倍计费）。
3. **流式 reasoning_content 单独成段**：delta.reasoning_content 与
   delta.content 是两条独立流，前者在前后者在后，归一化为 thinking_*
   事件。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from openai import AsyncOpenAI

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

_KNOWN_CAPS: dict[str, ModelCapabilities] = {
    "deepseek-v4-pro": ModelCapabilities(
        name="deepseek-v4-pro",
        provider="deepseek",
        context_window=128_000,
        max_output_tokens=16_000,
        supports_thinking=True,
        supports_prompt_cache=True,
        cn_quality="high",
        cost_input_per_mtok=0.27,
        cost_output_per_mtok=1.10,
    ),
    "deepseek-v4-flash": ModelCapabilities(
        name="deepseek-v4-flash",
        provider="deepseek",
        context_window=128_000,
        max_output_tokens=8192,
        supports_thinking=True,
        supports_prompt_cache=True,
        cn_quality="high",
        cost_input_per_mtok=0.07,
        cost_output_per_mtok=0.28,
    ),
    # 旧名兼容（2026/07/24 弃用）
    "deepseek-chat": ModelCapabilities(
        name="deepseek-chat",
        provider="deepseek",
        context_window=128_000,
        max_output_tokens=8192,
        supports_thinking=False,
        supports_prompt_cache=True,
        cn_quality="high",
    ),
    "deepseek-reasoner": ModelCapabilities(
        name="deepseek-reasoner",
        provider="deepseek",
        context_window=128_000,
        max_output_tokens=8192,
        supports_thinking=True,
        supports_prompt_cache=True,
        cn_quality="high",
    ),
}


def _to_deepseek_messages(
    messages: Sequence[Message],
    system: str | None,
) -> list[dict[str, Any]]:
    """统一 Message → DeepSeek 入参。

    关键点：assistant 消息若含 ThinkingBlock，必须把其文本写到 reasoning_content
    字段一起回传，缺了就 400。
    """
    out: list[dict[str, Any]] = []
    if system is not None:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "system":
            raise ValueError("system 应通过 system 参数传入，不能放进 messages")

        if m.role == "tool":
            if isinstance(m.content, str):
                continue
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.tool_call_id,
                            "content": b.output,
                        },
                    )
            continue

        if isinstance(m.content, str):
            out.append({"role": m.role, "content": m.content})
            continue

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for b in m.content:
            if isinstance(b, TextBlock):
                text_parts.append(b.text)
            elif isinstance(b, ThinkingBlock):
                thinking_parts.append(b.text)
            elif isinstance(b, ToolCallBlock):
                tool_calls.append(
                    {
                        "id": b.id,
                        "type": "function",
                        "function": {"name": b.name, "arguments": json.dumps(b.args)},
                    },
                )
        msg: dict[str, Any] = {"role": m.role, "content": "".join(text_parts) or None}
        # 仅 assistant 消息可携带 reasoning_content
        if thinking_parts and m.role == "assistant":
            msg["reasoning_content"] = "".join(thinking_parts)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        out.append(msg)
    return out


def _parse_usage(u: Any) -> Usage:
    """解析 DeepSeek usage，含 prompt_cache_hit/miss 字段。"""
    if u is None:
        return Usage()
    cache_hit = getattr(u, "prompt_cache_hit_tokens", 0) or 0
    return Usage(
        input_tokens=u.prompt_tokens or 0,
        output_tokens=u.completion_tokens or 0,
        cache_read_tokens=cache_hit,
    )


class DeepSeekProvider(LLMProvider):
    """DeepSeek 专用 Provider。"""

    name = "deepseek"

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.deepseek.com",
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        if model in _KNOWN_CAPS:
            return _KNOWN_CAPS[model]
        return ModelCapabilities(
            name=model,
            provider="deepseek",
            context_window=128_000,
            max_output_tokens=8192,
            supports_thinking=False,
            supports_prompt_cache=True,
            cn_quality="high",
        )

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
            "messages": _to_deepseek_messages(messages, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = list(tools)
        kwargs.update(extra)

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        blocks: list[ContentBlock] = []
        # 思维链放在最前，与 Anthropic 行为一致
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            blocks.append(ThinkingBlock(text=reasoning))
        if msg.content:
            blocks.append(TextBlock(text=msg.content))
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.type != "function":
                    continue
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append(ToolCallBlock(id=tc.id, name=tc.function.name, args=args))

        stop_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "error",
            "function_call": "tool_use",
        }
        stop_reason = stop_map.get(choice.finish_reason or "stop", "end_turn")

        return AssistantMessage(
            blocks=blocks,
            stop_reason=cast(Any, stop_reason),
            usage=_parse_usage(resp.usage),
            model=resp.model,
        )

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
            "messages": _to_deepseek_messages(messages, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = list(tools)
        kwargs.update(extra)

        text_started = False
        thinking_started = False
        thinking_closed = False
        tool_state: dict[int, dict[str, str]] = {}
        final_usage: Usage | None = None
        final_stop_reason: str | None = None

        stop_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "error",
        }

        stream = await self._client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if chunk.usage:
                final_usage = _parse_usage(chunk.usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # thinking 段先来后走
            reasoning_chunk = getattr(delta, "reasoning_content", None)
            if reasoning_chunk:
                if not thinking_started:
                    thinking_started = True
                    yield Delta(type="thinking_start", index=0)
                yield Delta(type="thinking_delta", index=0, text=reasoning_chunk)

            if delta.content:
                # 进入正文前先收尾思维链
                if thinking_started and not thinking_closed:
                    yield Delta(type="thinking_end", index=0)
                    thinking_closed = True
                if not text_started:
                    text_started = True
                    yield Delta(type="text_start", index=1)
                yield Delta(type="text_delta", index=1, text=delta.content)

            if delta.tool_calls:
                # 工具调用前同样先收尾思维链
                if thinking_started and not thinking_closed:
                    yield Delta(type="thinking_end", index=0)
                    thinking_closed = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_state:
                        tool_state[idx] = {"id": "", "name": "", "args": ""}
                        yield Delta(
                            type="tool_call_start",
                            index=idx + 2,  # 0=thinking 1=text 2+=tools
                            tool_call_id=tc.id or "",
                            tool_name=tc.function.name if tc.function else "",
                        )
                    if tc.id:
                        tool_state[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_state[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_state[idx]["args"] += tc.function.arguments
                        yield Delta(
                            type="tool_call_delta",
                            index=idx + 2,
                            args_json_chunk=tc.function.arguments,
                        )

            if choice.finish_reason:
                final_stop_reason = stop_map.get(choice.finish_reason, "end_turn")

        # 收尾：思维链 → 文本 → 工具
        if thinking_started and not thinking_closed:
            yield Delta(type="thinking_end", index=0)
        if text_started:
            yield Delta(type="text_end", index=1)
        for idx, state in tool_state.items():
            try:
                args_final = json.loads(state["args"] or "{}")
            except json.JSONDecodeError:
                args_final = {}
            yield Delta(
                type="tool_call_end",
                index=idx + 2,
                args_final=args_final,
            )

        yield Delta(
            type="message_done",
            stop_reason=final_stop_reason or "end_turn",
            usage=final_usage,
        )
