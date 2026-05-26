"""工具基础抽象。

- RiskTag：五档风险，决定司辰阁的拦截策略
- Tool：工具协议，所有工具实现都满足
- ToolResult：执行结果（ok/error 双态）
- ToolCtx：执行上下文（工程根目录、session_id 等）
- tool_to_*_schema：把 Tool 转成各 Provider 期望的 schema
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class RiskTag(StrEnum):
    """工具风险等级。司辰阁按此决定是否拦截 HITL。"""

    SAFE = "safe"  # 只读、无副作用：read_file / list_dir / ripgrep
    IO = "io"  # 工程内文件写：write_file 写工程内通过，写工程外拦截
    EXEC = "exec"  # 命令执行：run_shell 必拦
    NET = "net"  # 网络出站：fetch_url 必拦
    DESTRUCTIVE = "destructive"  # 不可逆：rm -rf、drop table 等，永远拦


class ToolError(Exception):
    """工具执行的业务异常。携带可读消息，会作为 ToolResult.error 返回给模型。"""


class ToolResult(BaseModel):
    """工具执行结果。"""

    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0
    # extra：留给工具放结构化元数据（如 stdout / stderr / files_changed）
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolCtx(BaseModel):
    """工具执行上下文。"""

    model_config = {"arbitrary_types_allowed": True}

    project_root: Path
    session_id: str
    trace_id: str

    def is_inside_project(self, path: Path) -> bool:
        """判断目标路径是否在工程目录内（用于 io 类工具的边界判定）。"""
        try:
            path.resolve().relative_to(self.project_root.resolve())
            return True
        except ValueError:
            return False


class Tool(ABC):
    """工具抽象基类。

    每个工具是一个无状态的可执行单元，由 Sandbox 调度执行，由 Gate 守门。
    name / version / risk / schema 是元数据，execute 是实际逻辑。
    """

    name: ClassVar[str]
    version: ClassVar[str] = "0.1.0"
    description: ClassVar[str] = ""
    risk: ClassVar[RiskTag] = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]]  # JSONSchema for arguments

    is_subprocess_safe: ClassVar[bool] = False
    """声明该工具能在 SubprocessSandbox 里跑。
    要求：(1) __init__ 无必填参数；(2) 不持有跨进程不能复活的状态
    （SQLite 连接 / 已开文件句柄 / 大对象）；(3) 不依赖父进程内存。
    Conductor 默认 InProc，仅在路由器挑到 Subprocess 时才校验这个标志。"""

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        """执行工具。失败时可抛 ToolError 或返回 ToolResult(ok=False)。"""


def tool_to_anthropic_schema(tool: Tool) -> dict[str, Any]:
    """转成 Anthropic Messages API 的 tools[] 元素格式。"""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.schema,
    }


def tool_to_openai_schema(tool: Tool) -> dict[str, Any]:
    """转成 OpenAI Chat Completions 的 tools[] 元素格式。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.schema,
        },
    }
