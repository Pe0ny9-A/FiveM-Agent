"""议会式群英会（Council） · 异构 + 并行 sub-agent + Judge 裁决。

只在三种场景用：架构选型、跨多文件审计、跨家模型一致性校验。日常用监督式。

设计：
- 多个 Councilor（= SubAgent）并行独立跑，互相不知道对方存在
- 输出汇总给 Judge 出 Verdict（结构化裁决书）
- Verdict 自动写到 project scope 的 episodic 记忆，命名空间 council_decisions

关键约束：
- asyncio.gather 并行
- deadline_seconds 总超时（默认 120s）——避免某个 Councilor 卡死整个议会
- 单个 Councilor 失败（异常 / 超时）记成 truncated，议会继续
- Judge 默认走 active profile 的 default_model；anthropic profile 强制 Opus
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from xuanji.capability.registry import ToolRegistry
from xuanji.config.profiles import Profile, ProfileKind
from xuanji.ensemble.judge import Judge, Verdict
from xuanji.ensemble.roles import Role, builtin_roles, resolve_role_name
from xuanji.ensemble.subagent import SubAgent, SubAgentResult
from xuanji.gate.bridge import HITLBridge
from xuanji.memory.models import Memory, MemoryKind, MemoryScope
from xuanji.memory.store.base import MemoryStore


class CouncilorSpec(BaseModel):
    """单个议员的入会参数。"""

    role: str
    """中文正名或英文别名（researcher / 稷下生 等价）"""

    profile_override: str | None = None
    """跨家拉异构。指向 council 上下文里的 profiles 字典 key"""

    model_override: str | None = None
    """同 profile 内换 model（很少用）"""

    brief_extra: str = ""
    """除议题外，给该 councilor 的额外侧重提示，例如「重点看安全风险」"""


class JudgeSpec(BaseModel):
    """裁决器配置。空字段走默认。"""

    profile_override: str | None = None
    model_override: str | None = None


class CouncilSpec(BaseModel):
    """一次议会的全部参数。"""

    question: str = Field(min_length=1)
    """议题，所有 Councilor 共享"""

    councilors: list[CouncilorSpec] = Field(min_length=2)
    """至少 2 名，建议奇数"""

    judge: JudgeSpec = Field(default_factory=JudgeSpec)

    deadline_seconds: float = 120.0
    """单个 Councilor 的超时；Judge 另算"""


class CouncilorOutcome(BaseModel):
    """单个 Councilor 跑完的产物。"""

    role: str
    profile_name: str
    model: str
    final_text: str
    iterations: int
    tool_calls_made: int
    truncated: bool
    error: str | None = None


class CouncilOutcome(BaseModel):
    """整次议会的最终汇总。"""

    question: str
    councilors: list[CouncilorOutcome]
    verdict: Verdict
    elapsed_seconds: float
    memory_id: str | None = None


# 进度事件——给 IPC notifier / CLI 跑进度条用
ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class CouncilEngine:
    """议会运行时。

    每次 convene 创建一个新实例，跑完一次会议就抛掉。
    """

    def __init__(
        self,
        *,
        roles: dict[str, Role] | None = None,
        profiles: dict[str, Profile],
        default_profile: Profile,
        active_profile_name: str | None = None,
        master_registry: ToolRegistry,
        project_root: Path,
        memory: MemoryStore | None = None,
        memory_namespace: str = "council_decisions",
        hitl_bridge: HITLBridge | None = None,
    ) -> None:
        self._roles = roles or builtin_roles()
        self._profiles = profiles
        self._default_profile = default_profile
        self._active_name = active_profile_name
        self._master_registry = master_registry
        self._project_root = project_root
        self._memory = memory
        self._memory_namespace = memory_namespace
        self._hitl_bridge = hitl_bridge

    async def convene(
        self,
        spec: CouncilSpec,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> CouncilOutcome:
        """跑一次议会。"""
        started = time.time()

        async def emit(event: str, payload: dict[str, Any]) -> None:
            if on_progress is not None:
                await on_progress(event, payload)

        await emit(
            "council_started",
            {
                "question": spec.question,
                "councilors": len(spec.councilors),
                "deadline_seconds": spec.deadline_seconds,
            },
        )

        # 并行跑所有 Councilor
        tasks = [
            self._run_councilor(spec.question, c, spec.deadline_seconds, emit, idx)
            for idx, c in enumerate(spec.councilors)
        ]
        outcomes = await asyncio.gather(*tasks)

        await emit(
            "council_judging",
            {
                "councilors_done": sum(1 for o in outcomes if o.error is None),
                "councilors_failed": sum(1 for o in outcomes if o.error is not None),
            },
        )

        # 召唤 Judge
        judge_profile, judge_model = self._select_judge_profile(spec.judge)
        judge = Judge(profile=judge_profile, model=judge_model)
        verdict = await judge.judge(
            question=spec.question,
            outcomes=outcomes,
        )

        # 写记忆
        memory_id: str | None = None
        if self._memory is not None:
            try:
                m = self._verdict_to_memory(spec.question, verdict)
                saved = self._memory.write(m)
                memory_id = saved.id
            except Exception:
                memory_id = None

        elapsed = time.time() - started
        await emit(
            "council_done",
            {
                "elapsed_seconds": elapsed,
                "verdict_summary": verdict.summary,
                "memory_id": memory_id,
            },
        )

        return CouncilOutcome(
            question=spec.question,
            councilors=outcomes,
            verdict=verdict,
            elapsed_seconds=elapsed,
            memory_id=memory_id,
        )

    async def _run_councilor(
        self,
        question: str,
        cspec: CouncilorSpec,
        timeout: float,
        emit: ProgressCallback,
        idx: int,
    ) -> CouncilorOutcome:
        canonical = resolve_role_name(cspec.role, self._roles)
        if canonical is None:
            return CouncilorOutcome(
                role=cspec.role,
                profile_name="",
                model="",
                final_text="",
                iterations=0,
                tool_calls_made=0,
                truncated=True,
                error=f"未知角色：{cspec.role!r}",
            )
        role = self._roles[canonical]

        profile, profile_name, model = self._select_councilor_profile(
            role, cspec,
        )

        await emit(
            "councilor_started",
            {
                "index": idx,
                "role": canonical,
                "profile": profile_name,
                "model": model,
            },
        )

        brief = question.strip()
        if cspec.brief_extra:
            brief = f"{brief}\n\n[侧重提示]\n{cspec.brief_extra}"

        sub = SubAgent(
            role,
            profile=profile,
            master_registry=self._master_registry,
            hitl_bridge=self._hitl_bridge,
            project_root=self._project_root,
            model=model,
        )

        try:
            result: SubAgentResult = await asyncio.wait_for(
                sub.run(brief), timeout=timeout,
            )
        except TimeoutError:
            await emit(
                "councilor_done",
                {"index": idx, "role": canonical, "ok": False, "error": "timeout"},
            )
            return CouncilorOutcome(
                role=canonical,
                profile_name=profile_name,
                model=model,
                final_text="",
                iterations=0,
                tool_calls_made=0,
                truncated=True,
                error=f"超时（{timeout}s）",
            )
        except Exception as e:
            await emit(
                "councilor_done",
                {
                    "index": idx, "role": canonical, "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                },
            )
            return CouncilorOutcome(
                role=canonical,
                profile_name=profile_name,
                model=model,
                final_text="",
                iterations=0,
                tool_calls_made=0,
                truncated=True,
                error=f"{type(e).__name__}: {e}",
            )

        await emit(
            "councilor_done",
            {
                "index": idx, "role": canonical, "ok": True,
                "iterations": result.iterations,
                "tool_calls": result.tool_calls_made,
            },
        )
        return CouncilorOutcome(
            role=canonical,
            profile_name=profile_name,
            model=model,
            final_text=result.final_text,
            iterations=result.iterations,
            tool_calls_made=result.tool_calls_made,
            truncated=result.truncated,
        )

    def _select_councilor_profile(
        self,
        role: Role,
        cspec: CouncilorSpec,
    ) -> tuple[Profile, str, str]:
        """挑 (profile, profile_name, model)。"""
        if cspec.profile_override and cspec.profile_override in self._profiles:
            name = cspec.profile_override
            p = self._profiles[name]
            return p, name, cspec.model_override or p.default_model

        # 按 role.preferred_profile_kinds 找匹配
        for kind in role.preferred_profile_kinds:
            for name, p in self._profiles.items():
                if p.kind == kind:
                    return p, name, cspec.model_override or p.default_model

        # 退到默认
        default_name = self._active_name or next(
            (n for n, p in self._profiles.items() if p is self._default_profile),
            "default",
        )
        return (
            self._default_profile,
            default_name,
            cspec.model_override or self._default_profile.default_model,
        )

    def _select_judge_profile(self, jspec: JudgeSpec) -> tuple[Profile, str]:
        """Judge 的 profile：优先指定 → anthropic 强制 Opus → active profile。"""
        if jspec.profile_override and jspec.profile_override in self._profiles:
            p = self._profiles[jspec.profile_override]
            return p, jspec.model_override or p.default_model

        # 偏好：anthropic profile 的话强制 Opus（旗舰 Judge）
        for p in self._profiles.values():
            if p.kind == ProfileKind.ANTHROPIC:
                model = jspec.model_override or "claude-opus-4-7"
                return p, model

        return self._default_profile, (
            jspec.model_override or self._default_profile.default_model
        )

    def _verdict_to_memory(self, question: str, verdict: Verdict) -> Memory:
        """裁决书 → episodic memory，重要性按分歧数加权。"""
        importance = min(0.95, 0.5 + 0.1 * len(verdict.divergence_points))
        text_lines = [
            f"议题：{question}",
            f"结论：{verdict.summary}",
        ]
        if verdict.chosen_path:
            text_lines.append(f"选择：{verdict.chosen_path}")
        if verdict.consensus_points:
            text_lines.append("共识：")
            text_lines.extend(f"  - {p}" for p in verdict.consensus_points)
        if verdict.divergence_points:
            text_lines.append("分歧：")
            text_lines.extend(f"  - {p}" for p in verdict.divergence_points)
        if verdict.risks:
            text_lines.append("风险：")
            text_lines.extend(f"  - {r}" for r in verdict.risks)
        return Memory(
            scope=MemoryScope.PROJECT,
            kind=MemoryKind.EPISODIC,
            namespace=self._memory_namespace,
            text="\n".join(text_lines),
            summary=f"议会裁决：{verdict.summary[:80]}",
            importance=importance,
            tags=["council", "decision", *([verdict.chosen_path] if verdict.chosen_path else [])],
            metadata={
                "decided_by": verdict.decided_by,
                "councilors": verdict.councilors,
            },
        )


__all__ = [
    "AsyncIterator",
    "CouncilEngine",
    "CouncilOutcome",
    "CouncilSpec",
    "CouncilorOutcome",
    "CouncilorSpec",
    "JudgeSpec",
]
