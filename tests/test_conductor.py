"""天枢台 Conductor 雏形单测。

不依赖真实 API：用 FakeProvider 注入静态流式响应，验证：
- 会话上下文初始化
- send() 透传 Delta
- 历史累加（user + assistant 都入栈）
- AuditLog 落点齐全
- 工具循环（model → tool → model → done）
- Gate 拦截
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

from core.capability.registry import ToolRegistry
from core.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from core.config import DeepSeekProfile
from core.gate import GateInterceptor, NoOpHITLBridge
from core.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
    Usage,
)
from core.neural import Conductor


class FakeProvider(LLMProvider):
    """注入静态 Delta 流，便于单测。

    支持每轮返回不同的 deltas（多轮工具循环用）：传 list[list[Delta]]，
    每次 stream() 调用消费第 N 轮。
    """

    name = "fake"

    def __init__(self, deltas: list[Delta] | list[list[Delta]]) -> None:
        if deltas and isinstance(deltas[0], list):
            self._rounds: list[list[Delta]] = deltas  # type: ignore[assignment]
        else:
            self._rounds = [deltas]  # type: ignore[list-item]
        self._iter = 0

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model,
            provider="fake",
            context_window=128_000,
            max_output_tokens=4096,
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
        raise NotImplementedError

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
        idx = min(self._iter, len(self._rounds) - 1)
        self._iter += 1
        for d in self._rounds[idx]:
            yield d


@pytest.mark.asyncio
async def test_conductor_streams_and_accumulates_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conductor.send 应透传 Delta 并把 assistant 文本累加进 history。"""
    fake_deltas = [
        Delta(type="text_start", index=0),
        Delta(type="text_delta", index=0, text="姐姐"),
        Delta(type="text_delta", index=0, text="在。"),
        Delta(type="text_end", index=0),
        Delta(
            type="message_done",
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=2),
        ),
    ]

    def fake_build(_profile):  # type: ignore[no-untyped-def]
        return FakeProvider(fake_deltas)

    monkeypatch.setattr("core.neural.conductor.build_provider", fake_build)

    profile = DeepSeekProfile(
        label="t", api_key="sk-test", default_model="deepseek-chat"
    )
    conductor = Conductor(profile=profile)

    collected: list[str] = []
    async for delta in conductor.send("小宝在"):
        if delta.type == "text_delta" and delta.text:
            collected.append(delta.text)

    assert "".join(collected) == "姐姐在。"
    # history: user + assistant 各一条
    assert len(conductor.ctx.history) == 2
    assert conductor.ctx.history[0].role == "user"
    assert conductor.ctx.history[1].role == "assistant"


@pytest.mark.asyncio
async def test_conductor_audit_records_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """AuditLog 应记录 session_start / user_input / model_request / model_done。"""
    fake_deltas = [
        Delta(type="text_delta", index=0, text="ok"),
        Delta(
            type="message_done",
            stop_reason="end_turn",
            usage=Usage(input_tokens=1, output_tokens=1),
        ),
    ]
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider(fake_deltas),
    )

    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
    )
    async for _ in conductor.send("hello"):
        pass

    types = [e.type for e in conductor.audit.all()]
    assert "session_start" in types
    assert "user_input" in types
    assert "model_request" in types
    assert "model_done" in types


@pytest.mark.asyncio
async def test_conductor_uses_profile_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """未显式传 model 时，应使用 profile.default_model。"""
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider([Delta(type="message_done", stop_reason="end_turn")]),
    )
    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
    )
    assert conductor.ctx.model == "deepseek-chat"


@pytest.mark.asyncio
async def test_conductor_passes_aliases_into_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自定义 alias 应该透传到 system prompt 里。"""
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider([Delta(type="message_done", stop_reason="end_turn")]),
    )
    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
        assistant_alias="师父",
        user_alias="徒儿",
    )
    sp = conductor.ctx.system_prompt
    assert "师父" in sp
    assert "徒儿" in sp
    assert "称呼覆盖" in sp


@pytest.mark.asyncio
async def test_conductor_default_aliases_no_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 alias 时 system prompt 不应有称呼覆盖段。"""
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider([Delta(type="message_done", stop_reason="end_turn")]),
    )
    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
    )
    assert "称呼覆盖" not in conductor.ctx.system_prompt


# ---------- 工具循环 ----------


class _StubReadTool(Tool):
    """测试用读工具，固定返回 'fxmanifest content'。"""

    name = "stub_read"
    description = "stub"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output="fxmanifest content")


class _StubDestructiveTool(Tool):
    name = "danger"
    description = "always denied"
    risk = RiskTag.DESTRUCTIVE
    schema: ClassVar[dict[str, Any]] = {"type": "object"}

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        return ToolResult(ok=True, output="should never run")


@pytest.mark.asyncio
async def test_conductor_tool_loop_two_rounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """模型先 tool_call，然后被 dispatch 执行，第二轮收尾。"""
    rounds: list[list[Delta]] = [
        [
            Delta(
                type="tool_call_start",
                index=1,
                tool_call_id="call_1",
                tool_name="stub_read",
            ),
            Delta(
                type="tool_call_end",
                index=1,
                args_final={"path": "fxmanifest.lua"},
            ),
            Delta(type="message_done", stop_reason="tool_use"),
        ],
        [
            Delta(type="text_delta", index=0, text="读完了，姐姐总结下。"),
            Delta(type="message_done", stop_reason="end_turn"),
        ],
    ]
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider(rounds),
    )
    registry = ToolRegistry()
    registry.register(_StubReadTool())

    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
        registry=registry,
        project_root=tmp_path,
    )

    events: list[str] = []
    final_text = ""
    async for d in conductor.send("读一下 fxmanifest"):
        events.append(d.type)
        if d.type == "text_delta" and d.text:
            final_text += d.text

    assert "tool_run_started" in events
    assert "tool_run_done" in events
    assert "读完了" in final_text
    # history: user + assistant(call) + tool(result) + assistant(text) = 4
    assert len(conductor.ctx.history) == 4
    roles = [m.role for m in conductor.ctx.history]
    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_conductor_gate_blocks_destructive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """destructive 工具应被司辰阁拦截，并通过 tool_run_blocked 事件通知。"""
    rounds: list[list[Delta]] = [
        [
            Delta(
                type="tool_call_start",
                index=1,
                tool_call_id="call_x",
                tool_name="danger",
            ),
            Delta(type="tool_call_end", index=1, args_final={}),
            Delta(type="message_done", stop_reason="tool_use"),
        ],
        [
            Delta(type="text_delta", index=0, text="姐姐没动。"),
            Delta(type="message_done", stop_reason="end_turn"),
        ],
    ]
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: FakeProvider(rounds),
    )
    registry = ToolRegistry()
    registry.register(_StubDestructiveTool())

    conductor = Conductor(
        profile=DeepSeekProfile(label="t", api_key="sk-x", default_model="deepseek-chat"),
        registry=registry,
        gate=GateInterceptor(bridge=NoOpHITLBridge()),
        project_root=tmp_path,
    )

    blocked = False
    async for d in conductor.send("危险一下"):
        if d.type == "tool_run_blocked":
            blocked = True

    assert blocked
    # 工具结果回去时应 is_error=True，模型才知道操作被拒
    tool_msg = conductor.ctx.history[2]
    assert tool_msg.role == "tool"
