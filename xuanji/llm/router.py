"""ModelRouter：按任务特征选 profile + 模型。

5 维输入：
- 角色（researcher / coder / reviewer / supervisor / generic）
- task_kind（chat / dev / ops / review / summary / planning）
- complexity（low / medium / high）
- ctx_size（输入 token 估算）
- budget_tier（free / standard / premium）

输出：ModelChoice = (profile_name, model_id)

退化规则：用户只装了一个 profile 时，所有路由都返回那一个，仅在 model_id
上做区分。Audit 仍记录"原本想要的 profile"和"实际用的 profile"两份字段。

矩阵不写死在代码里——通过 RoutingMatrix dataclass 可在运行时被
ConfigStore 覆盖（0.7+ 让用户在 settings 里调）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from xuanji.config.profiles import Profile, ProfileKind

TaskKind = Literal[
    "chat", "dev", "ops", "review", "summary", "planning", "routing", "tool-loop",
]
"""任务种类。route 时按这个 + 复杂度决定档位。"""

Complexity = Literal["low", "medium", "high"]
BudgetTier = Literal["free", "standard", "premium"]
"""预算档：free=只用免费/便宜模型；standard=默认；premium=允许 Opus 1M 这类贵货。"""

RoleName = Literal["researcher", "coder", "reviewer", "supervisor", "generic"]


class TaskSpec(BaseModel):
    """路由请求。各字段都是软提示，最终由 ModelRouter 综合判断。"""

    role: RoleName = "generic"
    task_kind: TaskKind = "chat"
    complexity: Complexity = "medium"
    ctx_size_tokens: int = 0
    """估算输入 token，用于判断是否要切到 1M 上下文模型。"""
    budget_tier: BudgetTier = "standard"
    requires_tool_use: bool = False
    cn_heavy: bool = False
    """中文主导内容（污段子 / 文档总结），偏向 DeepSeek / Sonnet。"""


class ModelChoice(BaseModel):
    """路由结果。fallback 链按顺序尝试，全失败才报错。"""

    profile_name: str
    model: str
    reason: str = ""
    """为什么挑它——给 audit 看的人类可读理由。"""
    fallback_chain: list[tuple[str, str]] = Field(default_factory=list)
    """(profile_name, model) 列表。主选挂掉时按顺序退。"""


class RoutingPolicy(BaseModel):
    """单条路由规则——条件 → 偏好 profile + 模型。

    匹配按声明顺序，第一条满足全部 when_* 条件的胜出。
    """

    name: str
    when_role: list[RoleName] = Field(default_factory=list)
    """空 = 任意角色都匹配。"""
    when_task_kind: list[TaskKind] = Field(default_factory=list)
    when_complexity: list[Complexity] = Field(default_factory=list)
    when_min_ctx_tokens: int = 0
    """ctx_size_tokens 小于此值时不匹配。0 = 不限。"""
    when_cn_heavy: bool | None = None
    """None = 不关心；True / False = 必须等于此值才匹配。"""
    prefer_profile_kinds: list[ProfileKind] = Field(default_factory=list)
    """按顺序找第一个用户实际配了的 profile kind。空 = 用 active profile。"""
    prefer_model: str | None = None
    """指定具体 model id；为空时用所选 profile 的 default_model。"""
    reason: str = ""

    def matches(self, spec: TaskSpec) -> bool:
        if self.when_role and spec.role not in self.when_role:
            return False
        if self.when_task_kind and spec.task_kind not in self.when_task_kind:
            return False
        if self.when_complexity and spec.complexity not in self.when_complexity:
            return False
        if self.when_min_ctx_tokens and spec.ctx_size_tokens < self.when_min_ctx_tokens:
            return False
        return not (
            self.when_cn_heavy is not None and spec.cn_heavy != self.when_cn_heavy
        )


def default_policies() -> list[RoutingPolicy]:
    """玄玑默认路由表。从最具体到最泛化。

    设计原则：policy 只挑 profile **种类**（哪一家），不写死 model id——
    实际 model 由所选 profile 的 default_model 决定。这样小宝在任一
    profile 上换模型，全局立即生效，路由表保持稳定。
    """
    return [
        RoutingPolicy(
            name="long-context-architecture",
            when_complexity=["high"],
            when_min_ctx_tokens=200_000,
            prefer_profile_kinds=[ProfileKind.ANTHROPIC, ProfileKind.OPENAI],
            reason="长上下文 + 高复杂度：偏好 Anthropic 长 ctx",
        ),
        RoutingPolicy(
            name="reviewer-strict",
            when_role=["reviewer"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC, ProfileKind.OPENAI],
            reason="审查严格：偏好 Anthropic",
        ),
        RoutingPolicy(
            name="researcher-tool-loop",
            when_role=["researcher"],
            when_task_kind=["tool-loop"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC],
            reason="研究员紧 tool loop：偏好 Anthropic",
        ),
        RoutingPolicy(
            name="cn-heavy-content",
            when_cn_heavy=True,
            prefer_profile_kinds=[ProfileKind.DEEPSEEK, ProfileKind.ANTHROPIC],
            reason="中文主导：DeepSeek 母语顺",
        ),
        RoutingPolicy(
            name="summary-bulk",
            when_task_kind=["summary"],
            when_complexity=["low", "medium"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC, ProfileKind.DEEPSEEK],
            reason="文档摘要 / 批量分类：用 profile default 即可",
        ),
        RoutingPolicy(
            name="routing-decision",
            when_task_kind=["routing"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC, ProfileKind.DEEPSEEK],
            reason="路由判定本身：用 profile default",
        ),
        RoutingPolicy(
            name="dev-tool-heavy",
            when_task_kind=["dev", "tool-loop"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC, ProfileKind.OPENAI],
            reason="开发场景 tool loop：偏好 Anthropic",
        ),
        RoutingPolicy(
            name="planning-strategic",
            when_task_kind=["planning"],
            when_complexity=["medium", "high"],
            prefer_profile_kinds=[ProfileKind.ANTHROPIC],
            reason="规划要看远：偏好 Anthropic",
        ),
    ]


class ModelRouter:
    """决策器。无状态，按 profiles 字典查表。

    用法：
        router = ModelRouter(profiles, active_profile_name="my-anthropic")
        choice = router.route(TaskSpec(role="reviewer"))
        # → ModelChoice(profile_name="my-anthropic", model="claude-opus-4-7", ...)
    """

    def __init__(
        self,
        profiles: dict[str, Profile],
        *,
        active_profile_name: str | None = None,
        policies: list[RoutingPolicy] | None = None,
    ) -> None:
        self.profiles = profiles
        self.active_profile_name = active_profile_name
        self.policies = policies or default_policies()

    def route(self, spec: TaskSpec) -> ModelChoice:
        """挑出一个 profile + model。退化规则：单 profile 用户直接走 active。"""
        # 单 profile 用户：所有路由都回到 active；只在 prefer_model 命中时换 model
        if len(self.profiles) <= 1:
            return self._single_profile_route(spec)

        for policy in self.policies:
            if not policy.matches(spec):
                continue
            chosen = self._pick_profile_by_kinds(policy.prefer_profile_kinds)
            if chosen is None:
                continue
            profile_name, profile = chosen
            model = policy.prefer_model or profile.default_model
            fallback = self._build_fallback(profile_name, model)
            return ModelChoice(
                profile_name=profile_name,
                model=model,
                reason=f"[{policy.name}] {policy.reason}",
                fallback_chain=fallback,
            )

        # 没规则匹配 → 用 active profile 的 default_model
        return self._fallback_to_active(reason="无规则匹配，回退 active")

    def _single_profile_route(self, spec: TaskSpec) -> ModelChoice:
        """单 profile 用户：保留路由意图但实际只能用唯一这个 profile。"""
        if not self.profiles:
            raise ValueError("没有可用 profile，先 xuanji init 配一个")
        name, profile = next(iter(self.profiles.items()))
        # 即便单 profile，policy 里若声明了 prefer_model 且 profile kind 兼容，
        # 也尝试切 model。否则保留 default_model
        for policy in self.policies:
            if not policy.matches(spec):
                continue
            if policy.prefer_model and (
                not policy.prefer_profile_kinds or profile.kind in policy.prefer_profile_kinds
            ):
                return ModelChoice(
                    profile_name=name,
                    model=policy.prefer_model,
                    reason=f"[{policy.name}·single-profile] {policy.reason}",
                    fallback_chain=[(name, profile.default_model)],
                )
            break
        return ModelChoice(
            profile_name=name,
            model=profile.default_model,
            reason="单 profile 用户，使用默认模型",
            fallback_chain=[],
        )

    def _pick_profile_by_kinds(
        self, kinds: list[ProfileKind],
    ) -> tuple[str, Profile] | None:
        """按偏好 kind 顺序找第一个用户配了的 profile。空 kinds = 用 active。"""
        if not kinds:
            return self._active_pair()
        for kind in kinds:
            for name, p in self.profiles.items():
                if p.kind == kind:
                    return (name, p)
        return None

    def _active_pair(self) -> tuple[str, Profile] | None:
        if self.active_profile_name and self.active_profile_name in self.profiles:
            return (self.active_profile_name, self.profiles[self.active_profile_name])
        if self.profiles:
            name = next(iter(self.profiles))
            return (name, self.profiles[name])
        return None

    def _build_fallback(self, primary_name: str, primary_model: str) -> list[tuple[str, str]]:
        """构造退避链：剩余 profile 的 default_model 各占一档。"""
        chain: list[tuple[str, str]] = []
        for name, p in self.profiles.items():
            if name == primary_name:
                continue
            chain.append((name, p.default_model))
        return chain

    def _fallback_to_active(self, *, reason: str) -> ModelChoice:
        active = self._active_pair()
        if active is None:
            raise ValueError("没有可用 profile，先 xuanji init")
        name, p = active
        return ModelChoice(
            profile_name=name,
            model=p.default_model,
            reason=reason,
            fallback_chain=self._build_fallback(name, p.default_model),
        )


__all__ = [
    "BudgetTier",
    "Complexity",
    "ModelChoice",
    "ModelRouter",
    "RoleName",
    "RoutingPolicy",
    "TaskKind",
    "TaskSpec",
    "default_policies",
]
