"""FiveM 专项工具：让玄玑直接读插件、学习、添加预设。

三件套：
- detect_project：扫当前目录给出 FiveMContext 摘要
- analyze_resource：深度分析一个 resource，抽出 exports/events/API 调用频率
- propose_preset：玄玑学完一个/一类 resource 后，提交"预设草案"
  → 草案落 `<data_dir>/scaffold_drafts/<key>.json`
  → 不自动激活，需小宝跑 `xuanji preset accept <key>`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolError, ToolResult
from xuanji.fivem.analyzer import analyze_resource
from xuanji.fivem.detector import detect_fivem_context, summarize_for_prompt
from xuanji.fivem.models import Framework, InventoryKind, TargetKind
from xuanji.fivem.presets import ScaffoldFile, ScaffoldPreset
from xuanji.fivem.scaffold import ScaffoldEngine

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


# ============================================================
# detect_project
# ============================================================


class DetectProjectTool(Tool):
    """识别当前目录是否 FiveM 项目，并推断 framework / inventory / target。"""

    name = "detect_project"
    description = (
        "扫当前 cwd（或指定路径），给出 FiveM 项目身份卡："
        "framework（QBCore/QBox/ESX/standalone）、inventory、target 系统、依赖列表。"
        "玄玑应在回答 FiveM 相关问题前先调它确定上下文，避免给出错误框架的答案。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目标路径，相对工程根或绝对；不传则用工程根",
            },
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        raw = args.get("path") or "."
        p = Path(raw)
        if not p.is_absolute():
            p = ctx.project_root / p
        if not p.exists():
            raise ToolError(f"路径不存在：{p}")
        if not p.is_dir():
            raise ToolError(f"不是目录：{p}")

        fc = detect_fivem_context(p)
        out: dict[str, Any] = {
            "is_fivem_resource": fc.is_fivem_resource,
            "framework": fc.framework.value,
            "framework_confidence": round(fc.framework_confidence, 2),
            "inventory": fc.inventory.value,
            "target": fc.target.value,
            "notes": fc.notes,
        }
        if fc.manifest:
            m = fc.manifest
            out["manifest"] = {
                "name": m.name,
                "version": m.version,
                "author": m.author,
                "lua54": m.lua54,
                "dependencies": m.dependencies,
                "client_scripts": m.client_scripts[:10],
                "server_scripts": m.server_scripts[:10],
                "shared_scripts": m.shared_scripts[:10],
            }
        if fc.detected_resources:
            out["sub_resources"] = [str(p) for p in fc.detected_resources[:30]]

        summary = summarize_for_prompt(fc)
        if summary:
            out["prompt_summary"] = summary

        return ToolResult(ok=True, output=out)


# ============================================================
# analyze_resource
# ============================================================


class AnalyzeResourceTool(Tool):
    """深度分析一个 resource：抽出 exports / events / API 调用频率。"""

    name = "analyze_resource"
    description = (
        "对一个 FiveM resource 做静态分析，返回："
        "(1) 它声明了哪些 exports；(2) 监听的 events；(3) 触发的 events；"
        "(4) lib.callback 名字；(5) 调用频率最高的框架 API。"
        "用于：玄玑学习一个现有 resource 的实现模式，或调试时快速看清它的接入点。"
        "不跑 Lua，纯正则扫文本，速度快但漏召回不影响结论。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "resource 目录的相对/绝对路径",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        raw = args.get("path")
        if not raw:
            raise ToolError("path 不能为空")
        p = Path(raw)
        if not p.is_absolute():
            p = ctx.project_root / p
        if not p.exists():
            raise ToolError(f"路径不存在：{p}")
        if not p.is_dir():
            raise ToolError(f"不是目录：{p}")

        analysis = analyze_resource(p)
        return ToolResult(
            ok=True,
            output={
                "resource_path": str(analysis.resource_path),
                "is_fivem_resource": analysis.context.is_fivem_resource,
                "framework": analysis.context.framework.value,
                "inventory": analysis.context.inventory.value,
                "target": analysis.context.target.value,
                "files_scanned": analysis.files_scanned,
                "exports": analysis.exports,
                "events_registered": analysis.events_registered[:50],
                "events_triggered": analysis.events_triggered[:50],
                "callbacks": analysis.callbacks[:30],
                "top_api_calls": analysis.framework_api_calls,
                "notes": analysis.notes,
            },
        )


# ============================================================
# propose_preset
# ============================================================


class ProposePresetTool(Tool):
    """玄玑学完后提交一个 scaffold 预设草案。"""

    name = "propose_preset"
    description = (
        "玄玑分析完一个/一类 resource 后，把「做这类 resource 的标准骨架」凝成预设草案。"
        "草案落 `<data_dir>/scaffold_drafts/<key>.json`，**不会自动激活**——"
        "需小宝跑 `xuanji preset accept <key>` 才纳入到 `xuanji new` 可用列表。"
        "调用前先用 detect_project / analyze_resource 看清楚才提案，"
        "避免凭空捏造或错误模板污染知识库。"
    )
    # IO 风险：写文件到用户数据目录。司辰阁会按工程外路径策略走 HITL，
    # 但 data_dir 在用户配置目录而非工程内——姐姐故意保留 IO 让 Gate 弹一次确认
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": (
                    "预设唯一 key，小写字母数字与连字符，2-40 字符。"
                    "例如 'qbcore-banking' / 'esx-vehicleshop'"
                ),
            },
            "label": {"type": "string", "description": "人类可读名"},
            "description": {"type": "string"},
            "framework": {
                "type": "string",
                "enum": [f.value for f in Framework],
            },
            "inventory": {
                "type": "string",
                "enum": [i.value for i in InventoryKind],
            },
            "target": {
                "type": "string",
                "enum": [t.value for t in TargetKind],
            },
            "files": {
                "type": "array",
                "description": (
                    "文件列表，每项 {path, content}。content 可用 {{name}} / "
                    "{{author}} / {{description}} / {{version}} 占位符。"
                    "至少要有 fxmanifest.lua + 一个 client/server 入口。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            "metadata": {
                "type": "object",
                "description": "学习来源等附加信息（自由 key/value）",
            },
        },
        "required": ["key", "label", "description", "framework", "files"],
    }

    def __init__(self, engine: ScaffoldEngine) -> None:
        self._engine = engine

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        key = (args.get("key") or "").strip().lower()
        if not _SLUG_RE.match(key):
            raise ToolError(
                f"key 必须是小写字母开头，含字母/数字/连字符，2-40 字符：{key!r}"
            )
        label = (args.get("label") or "").strip()
        description = (args.get("description") or "").strip()
        if not label or not description:
            raise ToolError("label 与 description 不能为空")

        framework = Framework(args.get("framework") or Framework.UNKNOWN.value)
        inventory = InventoryKind(args.get("inventory") or InventoryKind.UNKNOWN.value)
        target = TargetKind(args.get("target") or TargetKind.UNKNOWN.value)

        files_in = args.get("files") or []
        if not isinstance(files_in, list) or not files_in:
            raise ToolError("files 必须是非空数组")
        files: list[ScaffoldFile] = []
        has_manifest = False
        for f in files_in:
            if not isinstance(f, dict) or "path" not in f or "content" not in f:
                raise ToolError("每项 file 必须含 path / content")
            path = str(f["path"]).strip()
            content = str(f["content"])
            # 安全：禁绝对路径（含 Windows 盘符）与父目录穿越
            if (
                not path
                or path.startswith(("/", "\\"))
                or ".." in path
                or (len(path) >= 2 and path[1] == ":")  # Windows 'C:\...'
            ):
                raise ToolError(f"非法 path：{path!r}（不允许绝对路径或 ..）")
            if path.endswith("fxmanifest.lua"):
                has_manifest = True
            files.append(ScaffoldFile(path=path, content=content))
        if not has_manifest:
            raise ToolError("预设必须含 fxmanifest.lua 文件")

        metadata: dict[str, str] = {}
        for k, v in (args.get("metadata") or {}).items():
            metadata[str(k)] = str(v)

        preset = ScaffoldPreset(
            key=key,
            label=label,
            description=description,
            framework=framework,
            inventory=inventory,
            target=target,
            source="user",
            files=files,
            metadata=metadata,
        )

        try:
            saved_path = self._engine.save_draft(preset)
        except RuntimeError as e:
            raise ToolError(str(e)) from e

        return ToolResult(
            ok=True,
            output={
                "key": key,
                "draft_path": str(saved_path),
                "files_count": len(files),
                "framework": framework.value,
                "next_step": (
                    f"小宝跑 `xuanji preset show {key}` review，"
                    f"再 `xuanji preset accept {key}` 激活。"
                ),
            },
        )


def fivem_tools(engine: ScaffoldEngine) -> list[Tool]:
    """工厂：返回 FiveM 三件套工具。"""
    return [
        DetectProjectTool(),
        AnalyzeResourceTool(),
        ProposePresetTool(engine),
    ]


__all__ = [
    "AnalyzeResourceTool",
    "DetectProjectTool",
    "ProposePresetTool",
    "fivem_tools",
]
