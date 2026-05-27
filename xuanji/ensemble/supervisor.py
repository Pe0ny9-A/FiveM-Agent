"""DispatchSubagentTool：让 Supervisor（主 Conductor）通过工具调用召唤 sub-agent。

这是关键设计——**不引入新的调度机制**：sub-agent 召唤本身就是一次工具调用,
落在 Conductor 既有的 tool loop 里。这样：
- audit 自动覆盖（dispatch_subagent 是普通 tool call）
- gate 自动守门（默认 SAFE 直接放行；可改 IO 走 HITL）
- 流式事件自动透传（tool_run_started / tool_run_done 包装一切）

0.6 起：sub-agent 可异构——按 role 偏好或显式 profile_override 路由到不同 profile。
1.2 起：sub-agent 可递归 dispatch——稷下生可在中途召唤百工匠落地代码。
深度由 max_depth 限制（默认 2 层），防失控；parent_role / depth 串到 transcript。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.config.profiles import Profile
from xuanji.ensemble.roles import Role, resolve_role_name
from xuanji.ensemble.subagent import SubAgent
from xuanji.gate.bridge import HITLBridge
from xuanji.llm.router import ModelRouter, TaskSpec


class DispatchSubagentTool(Tool):
    """召唤一个 sub-agent 跑指定任务。

    异构路由：
    - args.profile_override 命中 self._profiles 时直接用
    - 否则按 role.preferred_profile_kinds 让 ModelRouter 挑
    - 都没匹配时退到 self._default_profile（向后兼容单 profile 场景）

    递归深度：
    - depth=0 是主 Conductor 自己持有的实例
    - depth=N 是被某个 sub-agent 持有的"嵌套召唤"实例
    - depth >= max_depth 时拒绝召唤，避免无限递归
    """

    name = "dispatch_subagent"
    description = (
        "召唤一个专项 sub-agent（角色化、受限工具）独立完成一个子任务，返回它的最终输出。"
        "适合：(1) 任务可清晰拆分，子任务工具集与主 agent 不重叠（如司鉴只读不写）；"
        "(2) 想用最小上下文跑某专项推理，避免污染主对话。"
        "可用角色见 list_roles。中文正名或英文别名都可（researcher / 稷下生 等价）。"
        "可选 profile_override：跨家用模型（如司鉴强制 Anthropic，稷下生用 DeepSeek）。"
        "sub-agent 跑完会返回 final_text，由你（Supervisor）综合再回复用户。"
        "Sub-agent 拿到这个工具时也可继续调它召唤另一位（受深度限制）。"
    )
    risk = RiskTag.SAFE  # 子调用本身无副作用，工具白名单已限制了破坏面
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": (
                    "角色名（中文正名或英文别名）。内置：稷下生（researcher，查文档/代码）/ "
                    "百工匠（coder，写代码改 Bug）/ 司鉴（reviewer，审查代码方案）/ "
                    "天枢令（planner，规划运筹）"
                ),
            },
            "brief": {
                "type": "string",
                "description": (
                    "明确的任务说明。要包含目标、上下文、期望输出格式。"
                    "好 brief：'读 xuanji/cli.py 找出 chat 命令实现，总结其工具注入顺序'。"
                    "坏 brief：'帮我看看 cli'。"
                ),
            },
            "profile_override": {
                "type": "string",
                "description": (
                    "可选。指定用哪个 profile 跑这个 sub-agent，覆盖 role 的偏好。"
                    "用 list_profiles 看可用名。"
                ),
            },
            "model_override": {
                "type": "string",
                "description": (
                    "可选。指定具体 model id，覆盖 router 选的。"
                    "不传则用所选 profile 的 default_model。"
                ),
            },
        },
        "required": ["role", "brief"],
    }

    def __init__(
        self,
        *,
        roles: dict[str, Role],
        master_registry: ToolRegistry,
        project_root: Path,
        default_profile: Profile | None = None,
        profile: Profile | None = None,
        hitl_bridge: HITLBridge | None = None,
        model: str | None = None,
        profiles: dict[str, Profile] | None = None,
        active_profile_name: str | None = None,
        depth: int = 0,
        max_depth: int = 2,
        parent_role: str | None = None,
    ) -> None:
        # 兼容 0.5 调用（profile=）+ 0.6 命名（default_profile=）
        chosen_default = default_profile or profile
        if chosen_default is None:
            raise ValueError("DispatchSubagentTool 必须给 default_profile 或 profile")
        self._roles = roles
        self._default_profile = chosen_default
        self._master_registry = master_registry
        self._project_root = project_root
        self._hitl_bridge = hitl_bridge
        self._model = model
        # profiles 字典存在 = 启用异构路由；为空 = 退化为单 profile（旧行为）
        self._profiles: dict[str, Profile] = profiles or {}
        self._active_profile_name = active_profile_name
        self._router = (
            ModelRouter(self._profiles, active_profile_name=active_profile_name)
            if self._profiles
            else None
        )
        self._depth = depth
        self._max_depth = max_depth
        self._parent_role = parent_role

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        if self._depth >= self._max_depth:
            raise ToolError(
                f"sub-agent 递归深度已达上限 max_depth={self._max_depth}，"
                f"当前深度 {self._depth}（parent={self._parent_role!r}）。"
                "再嵌套一层会失控——请把任务平铺给一位 sub-agent 处理，"
                "或在主 Conductor 这层重新拆分。"
            )

        raw_role = (args.get("role") or "").strip()
        canonical = resolve_role_name(raw_role, self._roles)
        if canonical is None:
            raise ToolError(
                f"未知角色：{raw_role!r}。可用：{sorted(self._roles.keys())}"
            )
        brief = (args.get("brief") or "").strip()
        if not brief:
            raise ToolError("brief 不能为空")

        role = self._roles[canonical]
        chosen_profile, chosen_model, route_reason = self._select_profile(role, args)

        # 给 sub-agent 注入下一层 dispatch_subagent（depth+1）。
        # 当 sub-agent 的 allowed_tools 含 dispatch_subagent 或 "*" 时生效；
        # 否则下一层 SubAgent.__init__ 自然过滤掉，不会出现在它的工具集。
        nested_dispatch = DispatchSubagentTool(
            roles=self._roles,
            master_registry=self._master_registry,
            project_root=self._project_root,
            default_profile=self._default_profile,
            hitl_bridge=self._hitl_bridge,
            model=self._model,
            profiles=self._profiles,
            active_profile_name=self._active_profile_name,
            depth=self._depth + 1,
            max_depth=self._max_depth,
            parent_role=role.name,
        )
        sub_master_registry = ToolRegistry()
        for t in self._master_registry.all():
            if t.name != "dispatch_subagent":
                sub_master_registry.register(t)
        sub_master_registry.register(nested_dispatch)

        sub = SubAgent(
            role,
            profile=chosen_profile,
            master_registry=sub_master_registry,
            hitl_bridge=self._hitl_bridge,
            project_root=self._project_root,
            model=chosen_model,
        )
        result = await sub.run(brief)
        return ToolResult(
            ok=True,
            output={
                "role": result.role,
                "final_text": result.final_text,
                "tool_calls_made": result.tool_calls_made,
                "iterations": result.iterations,
                "truncated": result.truncated,
                "depth": self._depth + 1,
                "parent_role": self._parent_role,
                "routing": {
                    "profile_kind": chosen_profile.kind.value,
                    "model": chosen_model,
                    "reason": route_reason,
                },
            },
            extra={"transcript": json.dumps(result.transcript, ensure_ascii=False)},
        )

    def _select_profile(
        self, role: Role, args: dict[str, Any],
    ) -> tuple[Profile, str, str]:
        """决策：返回 (profile, model, reason)。

        优先级：
        1. args.profile_override 命中 → 用它
        2. router 存在 → 按 role.preferred_profile_kinds 挑 profile
        3. 单 profile 退化 → default_profile

        model 选择（独立于 profile 选择）：
        1. args.model_override 显式指定
        2. 所选 profile 的 default_model（小宝在 profile 上配的那个）
        """
        override_name = (args.get("profile_override") or "").strip()
        model_override = (args.get("model_override") or "").strip() or None

        if override_name and override_name in self._profiles:
            chosen = self._profiles[override_name]
            model = model_override or chosen.default_model
            return chosen, model, f"profile_override={override_name}"

        if override_name and override_name not in self._profiles:
            reason_prefix = f"profile_override={override_name!r} 找不到，降级；"
        else:
            reason_prefix = ""

        if self._router is not None and self._profiles:
            # role 自己声明的 preferred_profile_kinds 直接生效——把它当临时 policy
            for kind in role.preferred_profile_kinds:
                for name, p in self._profiles.items():
                    if p.kind == kind:
                        model = model_override or p.default_model
                        return p, model, (
                            f"{reason_prefix}role.preferred[{kind.value}]→{name}"
                        )
            # role 没声明就走 router 兜底
            spec = TaskSpec(
                role="generic",
                task_kind="tool-loop",
                complexity="medium",
                budget_tier=role.budget_hint,
            )
            choice = self._router.route(spec)
            chosen = self._profiles[choice.profile_name]
            model = model_override or chosen.default_model
            return chosen, model, f"{reason_prefix}{choice.reason}"

        # 单 profile 退化
        chosen = self._default_profile
        model = model_override or self._model or chosen.default_model
        return chosen, model, f"{reason_prefix}single-profile-fallback"


class ListRolesTool(Tool):
    """列出可用 sub-agent 角色。"""

    name = "list_roles"
    description = "列出 dispatch_subagent 可用的角色名 + 一句话描述。"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    def __init__(self, roles: dict[str, Role]) -> None:
        self._roles = roles

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        out = [
            {
                "name": r.name,
                "description": r.description,
                "tools": r.allowed_tools[:8],
                "max_tool_iterations": r.max_tool_iterations,
                "preferred_profile_kinds": [k.value for k in r.preferred_profile_kinds],
                "budget_hint": r.budget_hint,
                "aliases": r.aliases,
            }
            for r in self._roles.values()
        ]
        return ToolResult(ok=True, output=out)


class ListProfilesTool(Tool):
    """列出可用 profile（用于 dispatch_subagent 的 profile_override）。"""

    name = "list_profiles"
    description = (
        "列出当前用户配的全部 LLM profile（不含 api_key）。"
        "Supervisor 决定让 sub-agent 用哪个 profile 时先看一眼有哪些可选。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    def __init__(
        self,
        profiles: dict[str, Profile],
        active_name: str | None = None,
    ) -> None:
        self._profiles = profiles
        self._active = active_name

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        out = [
            {
                "name": name,
                "kind": p.kind.value,
                "default_model": p.default_model,
                "active": name == self._active,
            }
            for name, p in self._profiles.items()
        ]
        return ToolResult(ok=True, output=out)


def supervisor_tools(
    *,
    roles: dict[str, Role],
    profile: Profile,
    master_registry: ToolRegistry,
    project_root: Path,
    hitl_bridge: HITLBridge | None = None,
    model: str | None = None,
    profiles: dict[str, Profile] | None = None,
    active_profile_name: str | None = None,
    max_depth: int = 2,
) -> list[Tool]:
    """工厂：返回 dispatch_subagent + list_roles + list_profiles。

    - profile：默认 profile，单 profile 用户唯一可用项
    - profiles / active_profile_name：异构路由所需的全量 profile 字典；
      留空 = 0.5 行为，所有 sub-agent 都用 profile 这一家。
    - max_depth：sub-agent 递归召唤上限。默认 2 = 最多两层嵌套（Supervisor → A → B）。
    """
    return [
        DispatchSubagentTool(
            roles=roles,
            default_profile=profile,
            master_registry=master_registry,
            project_root=project_root,
            hitl_bridge=hitl_bridge,
            model=model,
            profiles=profiles,
            active_profile_name=active_profile_name,
            depth=0,
            max_depth=max_depth,
            parent_role=None,
        ),
        ListRolesTool(roles),
        ListProfilesTool(profiles or {profile.label: profile}, active_profile_name),
    ]


__all__ = [
    "DispatchSubagentTool",
    "ListProfilesTool",
    "ListRolesTool",
    "supervisor_tools",
]
