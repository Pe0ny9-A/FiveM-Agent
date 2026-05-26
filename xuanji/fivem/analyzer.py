"""Resource 分析器：从一个 FiveM resource 目录抽出"可教点"。

抽：
- exports（client/server 各自的 export 列表）
- RegisterNetEvent / TriggerEvent / TriggerServerEvent / TriggerClientEvent 名字
- AddEventHandler 名字
- lib.callback.register / lib.callback.await
- QBCore.Functions.X / exports.qbx_core:X / ESX.X 调用

不跑 Lua——纯正则扫文本。漏召回不是大问题，召回多了也无伤。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from core.fivem.detector import detect_fivem_context
from core.fivem.models import FiveMContext

# ============================================================
# 正则集
# ============================================================

# exports('name', fn) / exports['{{resource}}']:name
_EXPORT_DECL = re.compile(
    r"""(?<!\.)\bexports?\s*\(\s*['"](?P<name>[\w\-]+)['"]""",
    re.VERBOSE,
)

# RegisterNetEvent('foo:bar') / AddEventHandler('foo:bar', ...)
_EVENT_REGISTER = re.compile(
    r"""\b(?:RegisterNetEvent|AddEventHandler)\s*\(\s*['"](?P<name>[\w\-:.]+)['"]""",
    re.VERBOSE,
)

# TriggerServerEvent / TriggerClientEvent / TriggerEvent
_EVENT_TRIGGER = re.compile(
    r"""\b(?:TriggerServerEvent|TriggerClientEvent|TriggerEvent)\s*\(\s*['"](?P<name>[\w\-:.]+)['"]""",
    re.VERBOSE,
)

# lib.callback.register('name', ...) / lib.callback.await('name')
_LIB_CALLBACK = re.compile(
    r"""\blib\.callback(?:\.register|\.await)?\s*\(\s*['"](?P<name>[\w\-:.]+)['"]""",
    re.VERBOSE,
)

# QBCore.Functions.X / exports.qbx_core:X / ESX.X
_FRAMEWORK_API = re.compile(
    r"""\b(?P<call>
        QBCore\.[\w.]+ |
        exports\.qbx_core[:.][\w]+ |
        ESX\.[\w.]+ |
        exports\.ox_inventory[:.][\w]+ |
        exports\.ox_target[:.][\w]+ |
        lib\.[\w.]+
    )""",
    re.VERBOSE,
)


@dataclass
class ResourceAnalysis:
    """单个 resource 的分析结果。"""

    resource_path: Path
    context: FiveMContext

    exports: list[str] = field(default_factory=list)
    events_registered: list[str] = field(default_factory=list)
    events_triggered: list[str] = field(default_factory=list)
    callbacks: list[str] = field(default_factory=list)

    framework_api_calls: dict[str, int] = field(default_factory=dict)
    """API 名 → 出现次数。看哪些 API 用得最多。"""

    files_scanned: int = 0
    notes: list[str] = field(default_factory=list)


def analyze_resource(root: Path) -> ResourceAnalysis:
    """分析一个 resource 目录。

    入参可以是 resource 根目录，也可以是 server bundle 根（自动找子 resource）。
    """
    root = root.resolve()
    ctx = detect_fivem_context(root)

    if not ctx.is_fivem_resource:
        # 不是 resource，给空结果但带 context（让调用方知道为什么）
        analysis = ResourceAnalysis(resource_path=root, context=ctx)
        if ctx.detected_resources:
            analysis.notes.append(
                f"当前不是 resource 根，但发现 {len(ctx.detected_resources)} 个子 resource。"
                "请指定具体子目录再 analyze。"
            )
        else:
            analysis.notes.append("当前目录不是 FiveM resource")
        return analysis

    analysis = ResourceAnalysis(resource_path=root, context=ctx)

    exports_set: set[str] = set()
    registered_set: set[str] = set()
    triggered_set: set[str] = set()
    callbacks_set: set[str] = set()
    api_counter: dict[str, int] = defaultdict(int)

    for lua_file in _iter_lua_files(root):
        try:
            text = lua_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        analysis.files_scanned += 1

        for m in _EXPORT_DECL.finditer(text):
            exports_set.add(m.group("name"))
        for m in _EVENT_REGISTER.finditer(text):
            registered_set.add(m.group("name"))
        for m in _EVENT_TRIGGER.finditer(text):
            triggered_set.add(m.group("name"))
        for m in _LIB_CALLBACK.finditer(text):
            callbacks_set.add(m.group("name"))
        for m in _FRAMEWORK_API.finditer(text):
            api_counter[m.group("call")] += 1

    analysis.exports = sorted(exports_set)
    analysis.events_registered = sorted(registered_set)
    analysis.events_triggered = sorted(triggered_set)
    analysis.callbacks = sorted(callbacks_set)
    analysis.framework_api_calls = dict(
        sorted(api_counter.items(), key=lambda kv: -kv[1])[:30],  # 前 30 个最频繁
    )
    return analysis


_SKIP_DIRS = {".git", "node_modules", ".vscode", ".idea", "dist", "build"}


def _iter_lua_files(root: Path, max_files: int = 200) -> list[Path]:
    """按 .lua 找文件。会跳过几个常见垃圾目录，限总数防爆。"""
    out: list[Path] = []
    for path in root.rglob("*.lua"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
        if len(out) >= max_files:
            break
    return out


__all__ = ["ResourceAnalysis", "analyze_resource"]
