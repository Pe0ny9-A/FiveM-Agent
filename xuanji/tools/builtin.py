"""内置原子工具：read_file / write_file / list_dir / ripgrep / run_shell。

工具风险等级：
- read_file / list_dir / ripgrep → SAFE
- write_file → IO（工程外触发 HITL）
- run_shell → EXEC（必走 HITL）

所有路径参数都允许相对路径（基于 ctx.project_root）与绝对路径。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, ClassVar

from core.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult


def _resolve(path: str, ctx: ToolCtx) -> Path:
    """把相对路径解析到工程根。"""
    p = Path(path)
    if not p.is_absolute():
        p = ctx.project_root / p
    return p


# ------------------------- read_file -------------------------


class ReadFileTool(Tool):
    name = "read_file"
    description = "读取文件内容并返回字符串。支持相对路径（基于工程根）和绝对路径。"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_bytes": {
                "type": "integer",
                "description": "最大读取字节数，避免读巨大文件。默认 200000",
                "default": 200_000,
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        path = _resolve(args["path"], ctx)
        max_bytes = int(args.get("max_bytes", 200_000))
        if not path.exists():
            raise ToolError(f"文件不存在：{path}")
        if not path.is_file():
            raise ToolError(f"不是文件：{path}")
        data = path.read_bytes()[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return ToolResult(
            ok=True,
            output=text,
            extra={
                "path": str(path),
                "bytes_read": len(data),
                "truncated": path.stat().st_size > max_bytes,
            },
        )


# ------------------------- write_file -------------------------


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "把字符串写入文件。如目录不存在会自动创建。写入工程外路径会触发 HITL 确认。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "要写入的字符串内容"},
            "create_dirs": {
                "type": "boolean",
                "description": "是否自动创建父目录，默认 true",
                "default": True,
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        path = _resolve(args["path"], ctx)
        content: str = args["content"]
        if args.get("create_dirs", True):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"已写入 {len(content)} 字符到 {path}",
            extra={"path": str(path), "bytes_written": len(content.encode("utf-8"))},
        )


# ------------------------- list_dir -------------------------


class ListDirTool(Tool):
    name = "list_dir"
    description = "列出目录内容。返回 entries 列表，每项含 name / type(file|dir) / size。"
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径，默认工程根", "default": "."},
            "max_entries": {
                "type": "integer",
                "description": "最大返回条目数，避免巨大目录撑爆上下文。默认 200",
                "default": 200,
            },
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        path = _resolve(args.get("path", "."), ctx)
        max_entries = int(args.get("max_entries", 200))
        if not path.exists():
            raise ToolError(f"目录不存在：{path}")
        if not path.is_dir():
            raise ToolError(f"不是目录：{path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(path.iterdir()):
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": stat.st_size if child.is_file() else None,
                },
            )
            if len(entries) >= max_entries:
                break
        return ToolResult(
            ok=True,
            output=entries,
            extra={"path": str(path), "count": len(entries)},
        )


# ------------------------- ripgrep -------------------------


class RipgrepTool(Tool):
    """纯 Python 实现的简易正则搜索。

    名字叫 ripgrep 是为了让模型用熟悉的语义触发；底层用 re + 文件遍历。
    M1+ 可换成实际调用 rg 二进制。
    """

    name = "ripgrep"
    description = (
        "在工程目录内按正则搜索文件内容。返回 matches 列表，每项含 path / line / text。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python 正则模式"},
            "path": {
                "type": "string",
                "description": "搜索根目录（相对工程根），默认 '.'",
                "default": ".",
            },
            "glob": {
                "type": "string",
                "description": "文件名 glob 过滤（如 *.lua），不填则全文件",
            },
            "max_matches": {
                "type": "integer",
                "description": "最大返回匹配数，默认 100",
                "default": 100,
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        pattern = args["pattern"]
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"正则编译失败：{e}") from e
        root = _resolve(args.get("path", "."), ctx)
        if not root.exists():
            raise ToolError(f"路径不存在：{root}")
        glob = args.get("glob")
        max_matches = int(args.get("max_matches", 100))

        matches: list[dict[str, Any]] = []
        files: list[Path] = []
        if root.is_file():
            files = [root]
        else:
            files = list(root.rglob(glob)) if glob else list(root.rglob("*"))

        skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
        for f in files:
            if not f.is_file():
                continue
            if any(part in skip_dirs for part in f.parts):
                continue
            try:
                with f.open("r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "path": str(f.relative_to(ctx.project_root))
                                    if f.is_relative_to(ctx.project_root)
                                    else str(f),
                                    "line": lineno,
                                    "text": line.rstrip("\n"),
                                },
                            )
                            if len(matches) >= max_matches:
                                break
            except OSError:
                continue
            if len(matches) >= max_matches:
                break

        return ToolResult(
            ok=True,
            output=matches,
            extra={"count": len(matches), "truncated": len(matches) >= max_matches},
        )


# ------------------------- run_shell -------------------------


class RunShellTool(Tool):
    name = "run_shell"
    description = (
        "在工程根目录执行 shell 命令并返回 stdout/stderr/exit_code。"
        "高风险，必经用户确认。"
    )
    risk = RiskTag.EXEC
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "完整 shell 命令"},
            "timeout_sec": {
                "type": "number",
                "description": "超时秒数，默认 30",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        command: str = args["command"]
        timeout_sec = float(args.get("timeout_sec", 30))
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(ctx.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ToolError(f"命令执行超时（{timeout_sec}s）") from None

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0
        return ToolResult(
            ok=exit_code == 0,
            output={"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
            error=None if exit_code == 0 else f"exit_code={exit_code}",
            extra={"command": command},
        )


def builtin_tools() -> list[Tool]:
    """返回所有内置工具的实例列表。"""
    return [
        ReadFileTool(),
        WriteFileTool(),
        ListDirTool(),
        RipgrepTool(),
        RunShellTool(),
    ]
