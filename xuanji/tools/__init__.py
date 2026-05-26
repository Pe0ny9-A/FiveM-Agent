"""内置工具集合。

M0：5 个原子工具（read_file / write_file / list_dir / ripgrep / run_shell）
M1：2 个知识工具（knowledge_search / lookup_symbol）
M2.5（自演化）：
- 元工具：list_tools / describe_tool / list_skills / read_skill
- 记忆工具：recall_memory / write_memory
- 知识 ingestion：ingest_text / ingest_file / upsert_symbol / ingest_url
- 技能工具：save_skill / search_skill / run_skill
- 工厂工具：propose_tool（仅产草案到磁盘，不自动 publish）
"""

from core.tools.builtin import (
    ListDirTool,
    ReadFileTool,
    RipgrepTool,
    RunShellTool,
    WriteFileTool,
    builtin_tools,
)
from core.tools.factory import ProposeToolTool, tool_factory_tools
from core.tools.ingest import (
    IngestFileTool,
    IngestTextTool,
    UpsertSymbolTool,
    ingest_tools_offline,
)
from core.tools.ingest_url import IngestUrlTool
from core.tools.knowledge import (
    KnowledgeSearchTool,
    LookupSymbolTool,
    knowledge_tools,
)
from core.tools.memory import RecallMemoryTool, WriteMemoryTool, memory_tools
from core.tools.meta import (
    DescribeToolTool,
    ListSkillsTool,
    ListToolsTool,
    ReadSkillTool,
    meta_tools,
)
from core.tools.skills import (
    SKILLS_NAMESPACE,
    RunSkillTool,
    SaveSkillTool,
    SearchSkillTool,
    skill_tools,
)

__all__ = [
    "SKILLS_NAMESPACE",
    "DescribeToolTool",
    "IngestFileTool",
    "IngestTextTool",
    "IngestUrlTool",
    "KnowledgeSearchTool",
    "ListDirTool",
    "ListSkillsTool",
    "ListToolsTool",
    "LookupSymbolTool",
    "ProposeToolTool",
    "ReadFileTool",
    "ReadSkillTool",
    "RecallMemoryTool",
    "RipgrepTool",
    "RunShellTool",
    "RunSkillTool",
    "SaveSkillTool",
    "SearchSkillTool",
    "UpsertSymbolTool",
    "WriteFileTool",
    "WriteMemoryTool",
    "builtin_tools",
    "ingest_tools_offline",
    "knowledge_tools",
    "memory_tools",
    "meta_tools",
    "skill_tools",
    "tool_factory_tools",
]
