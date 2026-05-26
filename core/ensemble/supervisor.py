"""DispatchSubagentTool：让 Supervisor（主 Conductor）通过工具调用召唤 sub-agent。

这是关键设计——**不引入新的调度机制**：sub-agent 召唤本身就是一次工具调用，
落在 Conductor 既有的 tool loop 里。这样：
- audit 自动覆盖（dispatch_subagent 是普通 tool call）
- gate 自动守门（默认 SAFE 直接放行；可改 IO 走 HITL）
- 流式事件自动透传（tool_run_started / tool_run_done 包装一切）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from core.capability.registry import ToolRegistry
from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from core.config.profiles import Profile
from core.ensemble.roles import Role
from core.ensemble.subagent import SubAgent
from core.gate.bridge import HITLBridge


class DispatchSubagentTool(Tool):
    """召唤一个 sub-agent 跑指定任务。"""

    name = "dispatch_subagent"
    description = (
        "召唤一个专项 sub-agent（角色化、受限工具）独立完成一个子任务，返回它的最终输出。"
        "适合：(1) 任务可清晰拆分，子任务工具集与主 agent 不重叠（如 reviewer 只读不写）；"
        "(2) 想用最小上下文跑某专项推理，避免污染主对话。"
        "可用角色见 list_roles 或下面 schema 的 enum。"
        "sub-agent 跑完会返回 final_text，由你（Supervisor）综合再回复用户。"
    )
    risk = RiskTag.SAFE  # 子调用本身无副作用，工具白名单已限制了破坏面
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": (
                    "角色名。内置：researcher（查文档/代码） / "
                    "coder（写代码改 Bug）/ reviewer（审查代码方案）"
                ),
            },
            "brief": {
                "type": "string",
                "description": (
                    "明确的任务说明。要包含目标、上下文、期望输出格式。"
                    "好 brief：'读 core/cli.py 找出 chat 命令实现，总结其工具注入顺序'。"
                    "坏 brief：'帮我看看 cli'。"
                ),
            },
        },
        "required": ["role", "brief"],
    }

    def __init__(
        self,
        *,
        roles: dict[str, Role],
        profile: Profile,
        master_registry: ToolRegistry,
        project_root: Path,
        hitl_bridge: HITLBridge | None = None,
        model: str | None = None,
    ) -> None:
        self._roles = roles
        self._profile = profile
        self._master_registry = master_registry
        self._project_root = project_root
        self._hitl_bridge = hitl_bridge
        self._model = model

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        role_name = (args.get("role") or "").strip()
        if role_name not in self._roles:
            raise ToolError(
                f"未知角色：{role_name!r}。可用：{sorted(self._roles.keys())}"
            )
        brief = (args.get("brief") or "").strip()
        if not brief:
            raise ToolError("brief 不能为空")

        role = self._roles[role_name]
        sub = SubAgent(
            role,
            profile=self._profile,
            master_registry=self._master_registry,
            hitl_bridge=self._hitl_bridge,
            project_root=self._project_root,
            model=self._model,
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
            },
            extra={"transcript": json.dumps(result.transcript, ensure_ascii=False)},
        )


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
            }
            for r in self._roles.values()
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
) -> list[Tool]:
    """工厂：返回 dispatch_subagent + list_roles。"""
    return [
        DispatchSubagentTool(
            roles=roles,
            profile=profile,
            master_registry=master_registry,
            project_root=project_root,
            hitl_bridge=hitl_bridge,
            model=model,
        ),
        ListRolesTool(roles),
    ]


__all__ = ["DispatchSubagentTool", "ListRolesTool", "supervisor_tools"]
