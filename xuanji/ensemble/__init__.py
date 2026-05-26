"""群英会 · 多 Agent 协作。

设计：
- Role：声明一个 sub-agent 的人格、可用工具白名单、推荐模型
- SubAgent：受限 tool registry 的轻量 Conductor 包装，单次任务 → 最终文本
- Supervisor：由主 Conductor 用 dispatch_subagent 工具召唤 sub-agent，
  把它的输出当成普通工具结果回传

M3 阶段先实装监督式（Supervisor + Sub-agent），合议式（Council + Judge）
留 stub。
"""

from core.ensemble.roles import (
    CODER_ROLE,
    RESEARCHER_ROLE,
    REVIEWER_ROLE,
    Role,
    builtin_roles,
)
from core.ensemble.subagent import SubAgent, SubAgentResult
from core.ensemble.supervisor import DispatchSubagentTool

__all__ = [
    "CODER_ROLE",
    "RESEARCHER_ROLE",
    "REVIEWER_ROLE",
    "DispatchSubagentTool",
    "Role",
    "SubAgent",
    "SubAgentResult",
    "builtin_roles",
]
