"""天枢台 · Conductor。

M0 阶段职责：
- 会话上下文 + persona mode/temperature/alias
- send() 接受用户输入，串起一个完整的"模型 ⇄ 工具"循环：
    1. 流式调用模型，累积 text 与 tool_calls
    2. 没有工具调用 → 收尾返回
    3. 有工具调用 → 经司辰阁 Gate 守门 → 工造司 Sandbox 执行 → 结果回传
    4. 把 assistant 消息（含 tool_call）与 tool 结果消息加入 history，进入下一轮
- 全程把模型 Delta 与工具运行事件混合 yield 出去，调用方按 type 分发渲染

M1+ 演进点：
- 中间件链（除 Gate 外的预算/速率/缓存等）
- PlanGraph 非线性 DAG 编排
- 群英会子 Agent dispatch
- 基于 Audit 的 rollback
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from xuanji.body.sandbox import InProcSandbox, Sandbox
from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import (
    Tool,
    ToolCtx,
    ToolResult,
    tool_to_anthropic_schema,
    tool_to_openai_schema,
)
from xuanji.config.profiles import Profile
from xuanji.gate.bridge import HITLBridge, NoOpHITLBridge
from xuanji.gate.interceptor import GateInterceptor, GateRefusal
from xuanji.gate.policy import Policy
from xuanji.hooks import HookEvent, HooksRegistry, run_matching_hooks
from xuanji.llm.providers.base import (
    Delta,
    LLMProvider,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from xuanji.llm.providers.factory import build_provider
from xuanji.memory.reflux import refluxed_fragment
from xuanji.memory.store.base import MemoryStore
from xuanji.neural.audit import AuditEvent, AuditLog
from xuanji.neural.compaction import CompactionConfig, compact_history
from xuanji.persona.code_strength import code_strength_fragment
from xuanji.persona.modes import (
    DEFAULT_ASSISTANT_ALIAS,
    DEFAULT_USER_ALIAS,
    PersonaMode,
    PersonaTemperature,
    build_system_prompt,
)


def _tools_for_provider(provider_name: str, tools: list[Tool]) -> list[dict[str, Any]] | None:
    """按 Provider 方言转换工具 schema。"""
    if not tools:
        return None
    if provider_name == "anthropic":
        return [tool_to_anthropic_schema(t) for t in tools]
    return [tool_to_openai_schema(t) for t in tools]


def _stringify_output(output: object) -> str:
    """把 ToolResult.output 序列化为字符串塞回 history。

    模型只看字符串，所以 dict/list 走 json.dumps（中文不转义）。
    """
    if isinstance(output, str):
        return output
    if output is None:
        return ""
    try:
        return json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(output)


class _PrefixDedup:
    """流式前缀去重——多轮 tool loop 模型偶尔把上一轮的开场白整段复读。

    工作原理：
    - 上一轮 assistant 完整 text 留作 ref。
    - 下一轮 text_delta 累积到 buf；只要 buf 是 ref 的（真）前缀，就吞掉不发。
    - 一旦 buf 长度超过 ref 或字符开始不匹配，认为本轮和上轮独立——
      flush 出 buf 中超出 ref 的尾段，之后所有 chunk 直接透传。
    - 没有上一轮（ref=""）时直接透传。

    保留这一层是 system prompt 复读约束的兜底；对正常不复读的轮次零开销。
    """

    def __init__(self, ref: str) -> None:
        self._ref = ref
        self._buf = ""
        self._passthrough = ref == ""

    def feed(self, chunk: str) -> str:
        """喂进一段新增 chunk，返回应当向外吐出的字符串（可能为空）。"""
        if self._passthrough:
            return chunk
        self._buf += chunk
        # buf 仍是 ref 的前缀 → 全部吞掉，等更多
        if self._ref.startswith(self._buf):
            return ""
        # 找出 buf 与 ref 共同前缀长度
        common = 0
        for a, b in zip(self._buf, self._ref, strict=False):
            if a != b:
                break
            common += 1
        # 切到独立轨：之后透传，先把已经超出 ref 的尾段吐出来
        self._passthrough = True
        tail = self._buf[common:]
        self._buf = ""
        return tail


class SessionCtx:
    """单次会话的上下文。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        mode: PersonaMode = PersonaMode.CHAT,
        temperature: PersonaTemperature = PersonaTemperature.BALANCED,
        assistant_alias: str = DEFAULT_ASSISTANT_ALIAS,
        user_alias: str = DEFAULT_USER_ALIAS,
    ) -> None:
        self.session_id = uuid.uuid4().hex
        self.provider = provider
        self.model = model
        self.mode = mode
        self.temperature = temperature
        self.assistant_alias = assistant_alias
        self.user_alias = user_alias
        self.history: list[Message] = []

    @property
    def system_prompt(self) -> str:
        return build_system_prompt(
            mode=self.mode,
            temperature=self.temperature,
            assistant_alias=self.assistant_alias,
            user_alias=self.user_alias,
        )


class Conductor:
    """唯一执行调度中枢。"""

    def __init__(
        self,
        *,
        profile: Profile,
        model: str | None = None,
        mode: PersonaMode = PersonaMode.CHAT,
        temperature: PersonaTemperature = PersonaTemperature.BALANCED,
        assistant_alias: str = DEFAULT_ASSISTANT_ALIAS,
        user_alias: str = DEFAULT_USER_ALIAS,
        registry: ToolRegistry | None = None,
        sandbox: Sandbox | None = None,
        gate: GateInterceptor | None = None,
        hitl_bridge: HITLBridge | None = None,
        policy: Policy | None = None,
        project_root: Path | None = None,
        audit: AuditLog | None = None,
        memory: MemoryStore | None = None,
        memory_namespace: str | None = None,
        reflux_top_k: int = 5,
        max_tool_iterations: int = 10,
        static_extra: str | None = None,
        hooks: HooksRegistry | None = None,
        compaction: CompactionConfig | None = None,
    ) -> None:
        provider = build_provider(profile)
        self.ctx = SessionCtx(
            provider=provider,
            model=model or profile.default_model,
            mode=mode,
            temperature=temperature,
            assistant_alias=assistant_alias,
            user_alias=user_alias,
        )
        self.registry = registry or ToolRegistry()
        self.sandbox = sandbox or InProcSandbox()
        self.gate = gate or GateInterceptor(
            policy=policy,
            bridge=hitl_bridge or NoOpHITLBridge(),
        )
        self.project_root = (project_root or Path.cwd()).resolve()
        self.audit = audit or AuditLog()
        self.max_tool_iterations = max_tool_iterations
        # 工具执行结果暂存：tool_call_id → ToolResultBlock
        # _dispatch 是 async generator，需要 yield 进度事件，
        # 又要让 send 拿到结果块塞回 history，这个 dict 是两者之间的桥
        self._last_results: dict[str, ToolResultBlock] = {}
        # 怀玉阁
        self.memory = memory
        # 默认用 project_root 名称作为项目命名空间，避免不同项目互窜
        self.memory_namespace = memory_namespace or self.project_root.name
        self.reflux_top_k = reflux_top_k
        # 启动期固定注入到 system prompt 的额外片段（如 FiveM 项目身份卡）
        self.static_extra = static_extra
        # Hooks：可选，None 时全程绕过 hook 路径
        self.hooks = hooks
        # 自动上下文压缩：默认开启，超 max_context_tokens 折叠头部
        self.compaction = compaction or CompactionConfig()
        # 项目级 + 用户级 XUANJI.md 片段，启动期采集一次缓存进 SessionCtx
        # （在每条消息前都拼到 system prompt 里，权重高于 reflux）
        # 延迟 import 打破 conductor → persona → config → store → neural 的循环。
        from xuanji.persona.project_memory import collect_xuanji_fragments

        self._xuanji_md_fragments: list[str] = collect_xuanji_fragments(self.project_root)

        self.audit.emit(
            AuditEvent(
                trace_id=self.ctx.session_id,
                type="session_start",
                payload={
                    "provider": provider.name,
                    "model": self.ctx.model,
                    "mode": self.ctx.mode.value,
                    "temperature": self.ctx.temperature.value,
                    "assistant_alias": assistant_alias,
                    "user_alias": user_alias,
                    "tools": self.registry.names(),
                    "xuanji_md_fragments": len(self._xuanji_md_fragments),
                },
            ),
        )

    async def send(self, user_text: str) -> AsyncIterator[Delta]:
        """提交用户输入，跑完整的 model ⇄ tool 循环并 yield Delta。"""
        trace_id = uuid.uuid4().hex
        self.audit.emit(
            AuditEvent(
                trace_id=trace_id,
                type="user_input",
                payload={"text": user_text, "session": self.ctx.session_id},
            ),
        )
        self.ctx.history.append(Message(role="user", content=user_text))

        tool_schemas = _tools_for_provider(
            self.ctx.provider.name, self.registry.all()
        )

        # 怀玉阁回流：用本轮用户输入做查询，把命中的记忆当 extra fragment 注入
        reflux_text: str | None = None
        if self.memory is not None:
            try:
                hits = self.memory.recall(
                    user_text,
                    namespace=self.memory_namespace,
                    k=self.reflux_top_k,
                )
                reflux_text = refluxed_fragment(hits)
            except Exception as e:
                self.audit.emit(
                    AuditEvent(
                        trace_id=trace_id,
                        type="error",
                        payload={"reflux_error": str(e)},
                    ),
                )

        def _system_prompt() -> str:
            extras: list[str] = []
            if self.static_extra:
                extras.append(self.static_extra)
            # XUANJI.md 项目宪法 — 用户级 + 项目级，项目级靠后权重更高
            extras.extend(self._xuanji_md_fragments)
            # 模型代码能力强化段（DeepSeek V4 Pro 等会拼上 Opus 风格的工程素养）
            cs = code_strength_fragment(
                self.ctx.provider.name,
                self.ctx.model,
            )
            if cs:
                extras.append(cs)
            if reflux_text:
                extras.append(reflux_text)
            return build_system_prompt(
                mode=self.ctx.mode,
                temperature=self.ctx.temperature,
                assistant_alias=self.ctx.assistant_alias,
                user_alias=self.ctx.user_alias,
                extra_fragments=extras or None,
            )

        last_assistant_text = ""

        for iteration in range(self.max_tool_iterations):
            # 压缩上下文：超过阈值时折叠 history 头部
            new_history, savings = compact_history(self.ctx.history, self.compaction)
            if savings > 0:
                self.ctx.history = new_history
                self.audit.emit(
                    AuditEvent(
                        trace_id=trace_id,
                        type="context_compacted",
                        payload={
                            "saved_tokens": savings,
                            "history_len": len(new_history),
                            "max_context_tokens": self.compaction.max_context_tokens,
                        },
                    ),
                )

            self.audit.emit(
                AuditEvent(
                    trace_id=trace_id,
                    type="model_request",
                    payload={
                        "model": self.ctx.model,
                        "history_len": len(self.ctx.history),
                        "iteration": iteration,
                        "reflux_count": (reflux_text or "").count("\n"),
                    },
                ),
            )

            text_buf = ""
            thinking_buf = ""
            tool_calls: dict[int, dict[str, Any]] = {}  # index → {id, name, args}
            # 仅在第二轮起启用：把上一轮的整段 assistant text 当作复读检测基准
            dedup = _PrefixDedup(last_assistant_text if iteration > 0 else "")

            # 模型支持 prompt cache 时自动给 system 加缓存（Anthropic 走 cache_system，
            # OpenAI / DeepSeek 是自动 prefix cache 不需要参数）
            stream_extra: dict[str, Any] = {}
            caps = self.ctx.provider.capabilities(self.ctx.model)
            if caps.supports_prompt_cache and self.ctx.provider.name == "anthropic":
                stream_extra["cache_system"] = True

            try:
                async for delta in self.ctx.provider.stream(
                    model=self.ctx.model,
                    messages=self.ctx.history,
                    system=_system_prompt(),
                    tools=tool_schemas,
                    **stream_extra,
                ):
                    if delta.type == "text_delta" and delta.text:
                        text_buf += delta.text
                        self.audit.emit(
                            AuditEvent(
                                trace_id=trace_id,
                                type="delta_text",
                                payload={"chunk": delta.text},
                            ),
                        )
                        # 流式去重：如果模型复读上一轮 text 开头，吞掉重复段
                        # history 仍存原文，model 自己看到自己说过什么；
                        # 只是 CLI / Web 不把重复的话再朗读一遍给小宝
                        emit = dedup.feed(delta.text)
                        if not emit:
                            continue
                        if emit != delta.text:
                            delta = Delta(type="text_delta", text=emit)
                    elif delta.type == "thinking_delta" and delta.text:
                        thinking_buf += delta.text
                    elif delta.type == "tool_call_start":
                        tool_calls[delta.index] = {
                            "id": delta.tool_call_id or "",
                            "name": delta.tool_name or "",
                            "args": {},
                        }
                    elif delta.type == "tool_call_end":
                        if delta.index in tool_calls:
                            tool_calls[delta.index]["args"] = delta.args_final or {}
                            self.audit.emit(
                                AuditEvent(
                                    trace_id=trace_id,
                                    type="delta_tool_call",
                                    payload={
                                        "id": tool_calls[delta.index]["id"],
                                        "name": tool_calls[delta.index]["name"],
                                        "args": tool_calls[delta.index]["args"],
                                    },
                                ),
                            )
                    elif delta.type == "message_done":
                        self.audit.emit(
                            AuditEvent(
                                trace_id=trace_id,
                                type="model_done",
                                payload={
                                    "stop_reason": delta.stop_reason,
                                    "usage": delta.usage.model_dump()
                                    if delta.usage
                                    else None,
                                    "iteration": iteration,
                                },
                            ),
                        )
                    yield delta
            except Exception as e:
                self.audit.emit(
                    AuditEvent(
                        trace_id=trace_id,
                        type="error",
                        payload={"message": str(e), "type": type(e).__name__},
                    ),
                )
                raise

            # 把 assistant 这一轮的产出落入 history
            asst_blocks: list[TextBlock | ThinkingBlock | ToolCallBlock] = []
            # ThinkingBlock 必须放在最前——DeepSeek thinking 模式要求 reasoning_content
            # 与 content 同一条 assistant 消息回传；位置靠前不影响 Anthropic 行为
            if thinking_buf:
                asst_blocks.append(ThinkingBlock(text=thinking_buf))
            if text_buf:
                asst_blocks.append(TextBlock(text=text_buf))
            for tc in tool_calls.values():
                if tc["id"] and tc["name"]:
                    asst_blocks.append(
                        ToolCallBlock(id=tc["id"], name=tc["name"], args=tc["args"]),
                    )
            if asst_blocks:
                self.ctx.history.append(Message(role="assistant", content=asst_blocks))

            # 记下本轮整段 text 给下一轮做复读检测基准
            last_assistant_text = text_buf

            if not tool_calls:
                # 模型没要工具，本轮结束
                return

            # 跑工具，收集结果
            result_blocks: list[ToolResultBlock] = []
            ctx_for_tool = ToolCtx(
                project_root=self.project_root,
                session_id=self.ctx.session_id,
                trace_id=trace_id,
            )
            for tc in tool_calls.values():
                async for rd in self._dispatch(tc, ctx_for_tool, trace_id):
                    yield rd
                blk = self._last_results.pop(tc["id"], None)
                if blk is not None:
                    result_blocks.append(blk)

            if result_blocks:
                self.ctx.history.append(
                    Message(role="tool", content=list(result_blocks)),
                )

        # 触顶警告：模型反复要工具但没收敛
        self.audit.emit(
            AuditEvent(
                trace_id=trace_id,
                type="error",
                payload={"message": f"达到 max_tool_iterations={self.max_tool_iterations}"},
            ),
        )

    async def _dispatch(
        self,
        tool_call: dict[str, Any],
        ctx_for_tool: ToolCtx,
        trace_id: str,
    ) -> AsyncIterator[Delta]:
        """单个工具调用的执行链：Gate → Sandbox → 把结果存到 _last_results。"""
        tool_id = tool_call["id"]
        tool_name = tool_call["name"]
        args = tool_call["args"]
        tool = self.registry.get(tool_name)

        if tool is None:
            err = f"未注册的工具：{tool_name}"
            self._last_results[tool_id] = ToolResultBlock(
                tool_call_id=tool_id, output=err, is_error=True,
            )
            yield Delta(
                type="tool_run_done",
                tool_call_id=tool_id,
                tool_name=tool_name,
                tool_run_ok=False,
                tool_run_error=err,
            )
            return

        yield Delta(
            type="tool_run_started",
            tool_call_id=tool_id,
            tool_name=tool_name,
            args_final=args,
        )

        # PreToolUse hooks：可拒绝调用
        if self.hooks is not None:
            pre_results = await run_matching_hooks(
                self.hooks,
                HookEvent.PRE_TOOL_USE,
                {"tool": tool_name, "args": args, "trace_id": trace_id},
                cwd=self.project_root,
                tool_name=tool_name,
            )
            for r in pre_results:
                if r.denied:
                    err = f"PreToolUse hook 拒绝：{r.reason or r.spec.command}"
                    self._last_results[tool_id] = ToolResultBlock(
                        tool_call_id=tool_id, output=err, is_error=True,
                    )
                    self.audit.emit(
                        AuditEvent(
                            trace_id=trace_id,
                            type="error",
                            payload={"hook_deny": r.reason, "tool": tool_name},
                        ),
                    )
                    yield Delta(
                        type="tool_run_blocked",
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        tool_run_reason=err,
                    )
                    return

        # 司辰阁守门
        try:
            await self.gate.check(tool, args, ctx_for_tool)
        except GateRefusal as e:
            err = f"司辰阁拦截：{e.verdict.reason}"
            self._last_results[tool_id] = ToolResultBlock(
                tool_call_id=tool_id, output=err, is_error=True,
            )
            self.audit.emit(
                AuditEvent(
                    trace_id=trace_id,
                    type="error",
                    payload={"gate_refusal": e.verdict.reason, "tool": tool_name},
                ),
            )
            yield Delta(
                type="tool_run_blocked",
                tool_call_id=tool_id,
                tool_name=tool_name,
                tool_run_reason=e.verdict.reason,
            )
            return

        # 工造司执行
        result: ToolResult = await self.sandbox.run(tool, args, ctx_for_tool)
        self._last_results[tool_id] = ToolResultBlock(
            tool_call_id=tool_id,
            output=_stringify_output(result.output if result.ok else result.error),
            is_error=not result.ok,
        )
        self.audit.emit(
            AuditEvent(
                trace_id=trace_id,
                type="delta_tool_call",
                payload={
                    "tool": tool_name,
                    "ok": result.ok,
                    "duration_ms": result.duration_ms,
                    "error": result.error,
                },
            ),
        )

        # PostToolUse hooks：纯观察，不改变 result（异常也只是 audit）
        if self.hooks is not None:
            try:
                await run_matching_hooks(
                    self.hooks,
                    HookEvent.POST_TOOL_USE,
                    {
                        "tool": tool_name,
                        "args": args,
                        "ok": result.ok,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                        "trace_id": trace_id,
                    },
                    cwd=self.project_root,
                    tool_name=tool_name,
                )
            except Exception as e:
                self.audit.emit(
                    AuditEvent(
                        trace_id=trace_id,
                        type="error",
                        payload={"post_hook_error": str(e), "tool": tool_name},
                    ),
                )

        yield Delta(
            type="tool_run_done",
            tool_call_id=tool_id,
            tool_name=tool_name,
            tool_run_ok=result.ok,
            tool_run_output=result.output,
            tool_run_error=result.error,
            tool_run_duration_ms=result.duration_ms,
        )
