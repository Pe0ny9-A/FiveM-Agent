"""SubAgent：受限工具 + 自定义人格的轻量 Conductor 包装。

为什么不直接用 Conductor 实例？
- SubAgent 是一次性的：Supervisor 给个任务 → SubAgent 跑完 → 返回最终文本
- 工具白名单：从主 registry 过滤出 role.allowed_tools
- system prompt 是 role.system_prompt（不沾主体玄玑的人设）
- 不接 reflux：sub-agent 不污染项目记忆
- 不接 audit：作为子调用记录在主 audit 里就够了
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from xuanji.body.sandbox import InProcSandbox, Sandbox
from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import ToolCtx
from xuanji.config.profiles import Profile
from xuanji.ensemble.roles import Role
from xuanji.gate.bridge import HITLBridge, NoOpHITLBridge
from xuanji.gate.interceptor import GateInterceptor, GateRefusal
from xuanji.gate.policy import Policy
from xuanji.llm.providers.base import (
    Delta,
    LLMProvider,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from xuanji.llm.providers.factory import build_provider
from xuanji.tools.meta import ListToolsTool


class SubAgentResult(BaseModel):
    """sub-agent 跑完后的最终结果。"""

    role: str
    final_text: str
    tool_calls_made: int = 0
    iterations: int = 0
    truncated: bool = False
    """达到 max_tool_iterations 仍没收敛时为 True。"""
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    """简短轨迹，给主 audit 用。"""


class SubAgent:
    """一次性受限 agent。

    用法：
        result = await SubAgent(role, ...).run("帮我查 ox_lib 的 callback 注册示例")
    """

    def __init__(
        self,
        role: Role,
        *,
        profile: Profile,
        master_registry: ToolRegistry,
        sandbox: Sandbox | None = None,
        gate: GateInterceptor | None = None,
        hitl_bridge: HITLBridge | None = None,
        policy: Policy | None = None,
        project_root: Path | None = None,
        model: str | None = None,
    ) -> None:
        self.role = role
        self.provider: LLMProvider = build_provider(profile)
        self.model = model or profile.default_model
        self.project_root = (project_root or Path.cwd()).resolve()
        self.sandbox = sandbox or InProcSandbox()
        self.gate = gate or GateInterceptor(
            policy=policy, bridge=hitl_bridge or NoOpHITLBridge(),
        )

        # 受限 tool registry
        self.registry = ToolRegistry()
        if "*" in role.allowed_tools:
            for t in master_registry.all():
                self.registry.register(t)
        else:
            for name in role.allowed_tools:
                tool = master_registry.get(name)
                if tool is not None:
                    self.registry.register(tool)
        # 总是给 sub-agent 装一个 list_tools 让它先看清自己有什么
        if "list_tools" not in self.registry:
            self.registry.register(ListToolsTool(self.registry))

    async def run(self, brief: str) -> SubAgentResult:
        """执行一次性任务，返回最终结果。"""
        from xuanji.capability.tool import (
            tool_to_anthropic_schema,
            tool_to_openai_schema,
        )

        history: list[Message] = [Message(role="user", content=brief)]
        ctx = ToolCtx(
            project_root=self.project_root,
            session_id=f"subagent-{self.role.name}",
            trace_id=f"subagent-{self.role.name}",
        )

        if self.provider.name == "anthropic":
            tool_schemas = [tool_to_anthropic_schema(t) for t in self.registry.all()]
        else:
            tool_schemas = [tool_to_openai_schema(t) for t in self.registry.all()]

        final_text = ""
        tool_calls_made = 0
        transcript: list[dict[str, Any]] = []
        truncated = True

        for iteration in range(self.role.max_tool_iterations):
            text_buf = ""
            tool_calls: dict[int, dict[str, Any]] = {}

            async for delta in self.provider.stream(
                model=self.model,
                messages=history,
                system=self.role.system_prompt,
                tools=tool_schemas if tool_schemas else None,
            ):
                if delta.type == "text_delta" and delta.text:
                    text_buf += delta.text
                elif delta.type == "tool_call_start":
                    tool_calls[delta.index] = {
                        "id": delta.tool_call_id or "",
                        "name": delta.tool_name or "",
                        "args": {},
                    }
                elif delta.type == "tool_call_end" and delta.index in tool_calls:
                    tool_calls[delta.index]["args"] = delta.args_final or {}

            asst_blocks: list[TextBlock | ToolCallBlock] = []
            if text_buf:
                asst_blocks.append(TextBlock(text=text_buf))
            for tc in tool_calls.values():
                if tc["id"] and tc["name"]:
                    asst_blocks.append(
                        ToolCallBlock(id=tc["id"], name=tc["name"], args=tc["args"]),
                    )
            if asst_blocks:
                history.append(Message(role="assistant", content=asst_blocks))

            if not tool_calls:
                final_text = text_buf
                truncated = False
                break

            # 执行工具
            result_blocks: list[ToolResultBlock] = []
            for tc in tool_calls.values():
                tool = self.registry.get(tc["name"])
                if tool is None:
                    result_blocks.append(
                        ToolResultBlock(
                            tool_call_id=tc["id"],
                            output=f"sub-agent 无权调用工具：{tc['name']}",
                            is_error=True,
                        ),
                    )
                    transcript.append(
                        {"step": iteration, "tool": tc["name"], "blocked": True},
                    )
                    continue
                try:
                    await self.gate.check(tool, tc["args"], ctx)
                except GateRefusal as e:
                    result_blocks.append(
                        ToolResultBlock(
                            tool_call_id=tc["id"],
                            output=f"司辰阁拦截：{e.verdict.reason}",
                            is_error=True,
                        ),
                    )
                    continue
                result = await self.sandbox.run(tool, tc["args"], ctx)
                tool_calls_made += 1
                from xuanji.neural.conductor import _stringify_output

                result_blocks.append(
                    ToolResultBlock(
                        tool_call_id=tc["id"],
                        output=_stringify_output(
                            result.output if result.ok else result.error
                        ),
                        is_error=not result.ok,
                    ),
                )
                transcript.append(
                    {
                        "step": iteration,
                        "tool": tc["name"],
                        "ok": result.ok,
                        "duration_ms": result.duration_ms,
                    },
                )
            history.append(Message(role="tool", content=list(result_blocks)))

        return SubAgentResult(
            role=self.role.name,
            final_text=final_text or "[sub-agent 触顶未收敛]",
            tool_calls_made=tool_calls_made,
            iterations=iteration + 1,
            truncated=truncated,
            transcript=transcript,
        )

    async def stream(self, brief: str) -> AsyncIterator[Delta]:
        """流式版（M3+ 服务层用）。M3 先不实装——返回 final 当一次 text_delta。"""
        result = await self.run(brief)
        yield Delta(type="text_delta", index=0, text=result.final_text)
        yield Delta(type="message_done", stop_reason="end_turn")


__all__ = ["SubAgent", "SubAgentResult"]
