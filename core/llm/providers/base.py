"""LLM Provider 抽象。

定义跨厂商统一的消息、内容块、流式 Delta 与 Provider 协议。
不同厂商（Anthropic / OpenAI / DeepSeek）的 SDK 在
text/tool_use/thinking 块结构与流式事件命名上各异，本模块提供归一化抽象，
下游（神经系统、能力系统、人设层）只面向这套抽象编程。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant", "tool"]


class TextBlock(BaseModel):
    """纯文本内容块。"""

    type: Literal["text"] = "text"
    text: str


class ToolCallBlock(BaseModel):
    """工具调用块。args 在流式过程中可能逐步累积，结束时为完整 JSON 对象。"""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ThinkingBlock(BaseModel):
    """思维链块（仅部分模型支持，如 Claude Extended Thinking）。"""

    type: Literal["thinking"] = "thinking"
    text: str


class ToolResultBlock(BaseModel):
    """工具执行结果块。

    Conductor 在 tool loop 里把工具结果包装成 role="tool" 的 Message，
    内含一或多个 ToolResultBlock，由 Provider 适配层翻译成各家 SDK 期望的格式：
    - Anthropic: 转成 role=user 消息的 tool_result content 块
    - OpenAI: 转成 role=tool 的独立消息
    """

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    output: str  # 序列化后的字符串内容（dict/list 自行 json.dumps）
    is_error: bool = False


ContentBlock = TextBlock | ToolCallBlock | ThinkingBlock | ToolResultBlock


class Message(BaseModel):
    """对话消息。content 既支持纯字符串（便利写法），也支持结构化块列表。"""

    role: Role
    content: str | list[ContentBlock]


class Usage(BaseModel):
    """调用计费与缓存统计。各 Provider 字段对齐到这里。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class AssistantMessage(BaseModel):
    """非流式调用的最终响应。"""

    blocks: list[ContentBlock]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"]
    usage: Usage = Field(default_factory=Usage)
    model: str

    @property
    def text(self) -> str:
        """便利属性：拼接所有 TextBlock 内容。"""
        return "".join(b.text for b in self.blocks if isinstance(b, TextBlock))


class Delta(BaseModel):
    """流式响应增量事件。

    模型生成事件（来自 Provider）：
    - text_start / text_delta / text_end：文本块生命周期
    - tool_call_start / tool_call_delta / tool_call_end：工具调用块生命周期
    - thinking_start / thinking_delta / thinking_end：思维链生命周期
    - message_done：整条消息结束，携带最终 stop_reason 与 usage

    Conductor 工具运行事件（来自天枢台执行循环）：
    - tool_run_started：开始执行某工具
    - tool_run_blocked：被司辰阁拦截
    - tool_run_done：工具执行完成（不论成败）
    """

    type: Literal[
        "text_start",
        "text_delta",
        "text_end",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "message_done",
        "tool_run_started",
        "tool_run_blocked",
        "tool_run_done",
    ]
    index: int = 0
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    args_json_chunk: str | None = None
    args_final: dict[str, Any] | None = None
    stop_reason: str | None = None
    usage: Usage | None = None
    # 工具运行事件附加字段
    tool_run_ok: bool | None = None
    tool_run_output: Any = None
    tool_run_error: str | None = None
    tool_run_reason: str | None = None
    tool_run_duration_ms: int | None = None


class ModelCapabilities(BaseModel):
    """模型能力指纹。供 ModelRouter 与 CapabilityAdapter 决策。"""

    model_config = ConfigDict(frozen=True)

    name: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_tool_use: bool = True
    supports_parallel_tool_calls: bool = True
    supports_streaming: bool = True
    supports_thinking: bool = False
    supports_prompt_cache: bool = False
    supports_vision: bool = False
    cn_quality: Literal["high", "medium", "low"] = "high"
    cost_input_per_mtok: float = 0.0
    cost_output_per_mtok: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    """LLM Provider 协议。所有厂商实现必须满足。

    - chat: 一次性请求-响应。
    - stream: 流式响应，逐个 yield Delta 事件。
    - capabilities: 返回模型能力指纹（用于路由与适配）。
    """

    name: str

    def capabilities(self, model: str) -> ModelCapabilities: ...

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
    ) -> AssistantMessage: ...

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: Sequence[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> AsyncIterator[Delta]: ...
