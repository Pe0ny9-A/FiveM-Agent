"""OpenAI Provider 实现。

兼顾三种 profile：
- openai：官方端点（base_url 默认 https://api.openai.com/v1）
- deepseek：DeepSeek 官方（base_url=https://api.deepseek.com，完全兼容 OpenAI Chat Completions）
- openai-compatible：用户自填 base_url（OneAPI / Ollama / Kimi / 智谱 / 火山方舟……）

将 OpenAI SDK 的流式 ChatCompletionChunk（choices[0].delta 内含 content / tool_calls）
归一化为 core.llm 的 Delta 事件流。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from openai import AsyncOpenAI

from core.llm.providers.base import (
    AssistantMessage,
    ContentBlock,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)

# 默认能力指纹。未登记的模型按这里兜底，保留 cn_quality=high 便于中文场景默认通过。
_DEFAULT_CAPS = ModelCapabilities(
    name="generic",
    provider="openai",
    context_window=128_000,
    max_output_tokens=4096,
    supports_thinking=False,
    supports_prompt_cache=False,
    cn_quality="high",
)

_KNOWN_CAPS: dict[str, ModelCapabilities] = {
    # OpenAI 官方
    "gpt-5.5": _DEFAULT_CAPS.model_copy(
        update={"name": "gpt-5.5", "context_window": 400_000, "max_output_tokens": 128_000},
    ),
    "gpt-5.4": _DEFAULT_CAPS.model_copy(
        update={"name": "gpt-5.4", "context_window": 200_000, "max_output_tokens": 64_000},
    ),
    # DeepSeek V4 系列（当前主推）
    "deepseek-v4-pro": _DEFAULT_CAPS.model_copy(
        update={
            "name": "deepseek-v4-pro",
            "provider": "deepseek",
            "context_window": 128_000,
            "max_output_tokens": 16_000,
            "supports_thinking": True,
        },
    ),
    "deepseek-v4-flash": _DEFAULT_CAPS.model_copy(
        update={
            "name": "deepseek-v4-flash",
            "provider": "deepseek",
            "context_window": 128_000,
            "max_output_tokens": 8192,
            "supports_thinking": True,
        },
    ),
    # DeepSeek 旧名（2026/07/24 弃用，分别对应 v4-flash 的非思考与思考模式）
    "deepseek-chat": _DEFAULT_CAPS.model_copy(
        update={
            "name": "deepseek-chat",
            "provider": "deepseek",
            "context_window": 128_000,
            "max_output_tokens": 8192,
        },
    ),
    "deepseek-reasoner": _DEFAULT_CAPS.model_copy(
        update={
            "name": "deepseek-reasoner",
            "provider": "deepseek",
            "context_window": 128_000,
            "max_output_tokens": 8192,
            "supports_thinking": True,
        },
    ),
}


def _to_openai_messages(
    messages: Sequence[Message],
    system: str | None,
) -> list[dict[str, Any]]:
    """统一 Message → OpenAI 入参。

    - system 在 OpenAI 中是 messages[0]，role='system'
    - role="tool" 消息：每个 ToolResultBlock 拆成一条独立的 OpenAI tool message
    - thinking 块 OpenAI 端不支持，丢弃
    """
    out: list[dict[str, Any]] = []
    if system is not None:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "system":
            raise ValueError("system 应通过 system 参数传入，不能放进 messages")

        # role="tool"：每个块独立成一条 OpenAI tool message
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
        tool_calls: list[dict[str, Any]] = []
        for b in m.content:
            if isinstance(b, TextBlock):
                text_parts.append(b.text)
            elif isinstance(b, ToolCallBlock):
                tool_calls.append(
                    {
                        "id": b.id,
                        "type": "function",
                        "function": {"name": b.name, "arguments": json.dumps(b.args)},
                    },
                )
        msg: dict[str, Any] = {"role": m.role, "content": "".join(text_parts) or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        out.append(msg)
    return out


class OpenAIProvider(LLMProvider):
    """OpenAI / DeepSeek / openai-compatible 三合一 Provider。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        self.name = provider_name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def capabilities(self, model: str) -> ModelCapabilities:
        if model in _KNOWN_CAPS:
            return _KNOWN_CAPS[model]
        return _DEFAULT_CAPS.model_copy(update={"name": model, "provider": self.name})

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
            "messages": _to_openai_messages(messages, system),
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

        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

        return AssistantMessage(
            blocks=blocks,
            stop_reason=cast(Any, stop_reason),
            usage=usage,
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
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = list(tools)
        kwargs.update(extra)

        # OpenAI 流式特性：text 是单一隐式块（index=0）；tool_calls 通过
        # delta.tool_calls[*].index 区分，相同 index 的 args 增量在多个 chunk 里累积。
        text_started = False
        # tc_index → (id, name, args_buf)
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
                final_usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                if not text_started:
                    text_started = True
                    yield Delta(type="text_start", index=0)
                yield Delta(type="text_delta", index=0, text=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_state:
                        tool_state[idx] = {"id": "", "name": "", "args": ""}
                        yield Delta(
                            type="tool_call_start",
                            index=idx + 1,  # +1 避免与 text 块的 index=0 撞车
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
                            index=idx + 1,
                            args_json_chunk=tc.function.arguments,
                        )

            if choice.finish_reason:
                final_stop_reason = stop_map.get(choice.finish_reason, "end_turn")

        # 收尾：先关 text 块，再关所有 tool 块
        if text_started:
            yield Delta(type="text_end", index=0)
        for idx, state in tool_state.items():
            try:
                args_final = json.loads(state["args"] or "{}")
            except json.JSONDecodeError:
                args_final = {}
            yield Delta(
                type="tool_call_end",
                index=idx + 1,
                args_final=args_final,
            )

        yield Delta(
            type="message_done",
            stop_reason=final_stop_reason or "end_turn",
            usage=final_usage,
        )
