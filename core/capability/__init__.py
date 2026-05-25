"""百工坊 · 工具/技能/能力包三层抽象。

M0 阶段先实装 Tool 与 ToolRegistry。Skill 与 Pack 留接口，M1+ 接入。
"""

from core.capability.registry import ToolRegistry
from core.capability.tool import (
    RiskTag,
    Tool,
    ToolCtx,
    ToolError,
    ToolResult,
    tool_to_anthropic_schema,
    tool_to_openai_schema,
)

__all__ = [
    "RiskTag",
    "Tool",
    "ToolCtx",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "tool_to_anthropic_schema",
    "tool_to_openai_schema",
]
