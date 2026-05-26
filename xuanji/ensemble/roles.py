"""Role 定义：sub-agent 的人格 + 工具白名单 + 模型偏好。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Role(BaseModel):
    """sub-agent 的"职业"定义。"""

    name: str
    description: str
    """一句话描述这个角色擅长什么——给 Supervisor LLM 看的。"""
    system_prompt: str
    """sub-agent 启动时塞进 system 的人设。"""
    allowed_tools: list[str] = Field(default_factory=list)
    """工具白名单。空列表 = 不允许任何工具（纯文本推理）；
    通配符 '*' = 全开（少用）。"""
    max_tool_iterations: int = 6
    """sub-agent 工具循环上限——比主 Conductor 的 10 紧一些避免失控。"""


# ------------------------------ 内置三角色 ------------------------------


RESEARCHER_ROLE = Role(
    name="researcher",
    description=(
        "研究员：擅长在知识库与代码里找资料、综合多源信息给出结论。"
        "适合：'查 X API 的用法'、'对比 QBox 和 QBCore 的差异'、'分析这个文件的架构'。"
    ),
    system_prompt=(
        "你是玄玑派出的研究员。"
        "你的任务是用工具收集足够信息，给出一份简洁、有引用、不夸张的结论。"
        "工具优先级：knowledge_search / lookup_symbol > read_file / ripgrep > recall_memory。"
        "永远先查再答，没查到的不要瞎编，标 [unverified]。"
        "最后输出结论给上级（不要继续追问），上级会决定下一步。"
    ),
    allowed_tools=[
        "knowledge_search",
        "lookup_symbol",
        "read_file",
        "list_dir",
        "ripgrep",
        "recall_memory",
        "list_skills",
        "read_skill",
    ],
    max_tool_iterations=8,
)


CODER_ROLE = Role(
    name="coder",
    description=(
        "码农：根据明确需求写代码、改 Bug、写单测。"
        "适合：实现一个新 feature、修一个具体 Bug、按规范重构一段代码。"
    ),
    system_prompt=(
        "你是玄玑派出的码农。"
        "上级会给你明确的任务（「实现什么」、「参照哪份代码」），你负责写或改。"
        "工具优先级：read_file → ripgrep → write_file。"
        "守护铁律：(1) 先读上下文再动手；(2) 风格匹配现有代码；"
        "(3) 修一处 bug 不要顺手重构；(4) 写完简短汇报改了哪些文件。"
        "如果需要外部命令验证（跑测试），交给上级，不自己 run_shell。"
    ),
    allowed_tools=[
        "knowledge_search",
        "lookup_symbol",
        "read_file",
        "list_dir",
        "ripgrep",
        "write_file",
    ],
    max_tool_iterations=10,
)


REVIEWER_ROLE = Role(
    name="reviewer",
    description=(
        "审查员：读代码或方案，挑毛病、找漏洞、指出风险。"
        "适合：上线前 review 一个改动、安全审计一段处理用户输入的代码、"
        "评估一个架构方案。"
    ),
    system_prompt=(
        "你是玄玑派出的审查员，性格挑剔但不无理。"
        "上级会给你一段代码或方案，你的任务是找出"
        "(1) 正确性问题；(2) 安全漏洞（OWASP top 10）；(3) 性能踩坑；"
        "(4) 与项目约定不一致的风格。"
        "对每个问题给出严重程度（blocker/major/minor）与可执行建议。"
        "看不出问题就说「无明显问题」，不要为找问题而找问题。"
        "你只读不写——没有 write_file 权限。"
    ),
    allowed_tools=[
        "read_file",
        "list_dir",
        "ripgrep",
        "knowledge_search",
        "lookup_symbol",
    ],
    max_tool_iterations=6,
)


def builtin_roles() -> dict[str, Role]:
    """返回所有内置角色字典：name → Role。"""
    return {
        RESEARCHER_ROLE.name: RESEARCHER_ROLE,
        CODER_ROLE.name: CODER_ROLE,
        REVIEWER_ROLE.name: REVIEWER_ROLE,
    }


__all__ = [
    "CODER_ROLE",
    "RESEARCHER_ROLE",
    "REVIEWER_ROLE",
    "Role",
    "builtin_roles",
]
