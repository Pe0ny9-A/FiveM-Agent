"""项目识别器。

进任意目录就跑一遍 detect_fivem_context()，判断：
- 是否 FiveM resource（含 fxmanifest.lua）
- framework（QBCore / QBox / ESX / standalone）
- inventory（ox_inventory / qb-inventory / esx_inventory / qs-inventory）
- target（ox_target / qb-target）

判断证据来源（按权重）：
1. 当前 resource 自己的 fxmanifest dependencies（最强信号）
2. 如果 cwd 是 server bundle 根目录，扫 resources/[xxx]/ 下的子 resources
3. 项目根的 server.cfg / config.cfg 引用的 ensure 列表
4. 没线索 → UNKNOWN，玄玑会主动询问
"""

from __future__ import annotations

import re
from pathlib import Path

from core.fivem.manifest import parse_fxmanifest_file
from core.fivem.models import (
    FiveMContext,
    Framework,
    InventoryKind,
    TargetKind,
)

# server.cfg / config.cfg 的 ensure 行
_ENSURE_LINE = re.compile(
    r"""^\s*ensure\s+['"]?(?P<name>[\w\-]+)['"]?\s*$""",
    re.MULTILINE,
)


# ============================================================
# 推断规则
# ============================================================


def _framework_from_deps(deps: list[str]) -> tuple[Framework, float]:
    """从 dependencies 列表推断 framework + 置信度。"""
    s = {d.lower() for d in deps}
    # QBox 与 QBCore 在依赖名上几乎一样（都用 qb-core）；
    # 优先看是否引了 qbx_core / qbx_xx 这种 qbx_ 前缀
    if any(d.startswith("qbx_") or d == "qbx_core" for d in s):
        return Framework.QBOX, 0.95
    if "qb-core" in s or "qbcore" in s:
        return Framework.QBCORE, 0.85
    if "es_extended" in s or "esx" in s:
        return Framework.ESX, 0.9
    if "ox_lib" in s and not any(d.startswith(("qb", "es")) for d in s):
        return Framework.STANDALONE, 0.6
    return Framework.UNKNOWN, 0.0


def _inventory_from_deps(deps: list[str]) -> InventoryKind:
    s = {d.lower() for d in deps}
    if "ox_inventory" in s:
        return InventoryKind.OX_INVENTORY
    if "qb-inventory" in s:
        return InventoryKind.QB_INVENTORY
    if "qs-inventory" in s:
        return InventoryKind.QS_INVENTORY
    if "esx_inventory" in s or "esx_inventoryhud" in s:
        return InventoryKind.ESX_INVENTORY
    return InventoryKind.UNKNOWN


def _target_from_deps(deps: list[str]) -> TargetKind:
    s = {d.lower() for d in deps}
    if "ox_target" in s:
        return TargetKind.OX_TARGET
    if "qb-target" in s:
        return TargetKind.QB_TARGET
    if "interact" in s:
        return TargetKind.INTERACT
    return TargetKind.UNKNOWN


# ============================================================
# 主 detect 函数
# ============================================================


def detect_fivem_context(root: Path) -> FiveMContext:
    """从一个目录检测 FiveM 上下文。

    支持三种入口：
    - resource 根：含 fxmanifest.lua
    - server bundle 根：含 resources/ + server.cfg
    - 都不是：返回 is_fivem_resource=False，但仍尝试找子 resources
    """
    root = root.resolve()
    ctx = FiveMContext(project_root=root)

    fxmanifest = root / "fxmanifest.lua"
    if not fxmanifest.exists():
        # 旧版可能用 __resource.lua
        legacy = root / "__resource.lua"
        if legacy.exists():
            fxmanifest = legacy

    # ---------- 入口 A：当前是 resource ----------

    if fxmanifest.exists() and fxmanifest.is_file():
        ctx.is_fivem_resource = True
        ctx.fxmanifest_path = fxmanifest
        try:
            manifest = parse_fxmanifest_file(fxmanifest)
        except OSError as e:
            ctx.notes.append(f"读取 fxmanifest 失败：{e}")
            return ctx
        ctx.manifest = manifest

        fw, conf = _framework_from_deps(manifest.dependencies)
        ctx.framework = fw
        ctx.framework_confidence = conf
        ctx.inventory = _inventory_from_deps(manifest.dependencies)
        ctx.target = _target_from_deps(manifest.dependencies)

        if fw == Framework.UNKNOWN:
            ctx.notes.append(
                "fxmanifest 没有 framework 依赖，可能是 standalone 或未声明"
            )
        else:
            ctx.notes.append(
                f"从 fxmanifest dependencies 识别 framework={fw.value} (conf={conf:.2f})"
            )
        if ctx.inventory != InventoryKind.UNKNOWN:
            ctx.notes.append(f"inventory={ctx.inventory.value}")
        if ctx.target != TargetKind.UNKNOWN:
            ctx.notes.append(f"target={ctx.target.value}")
        return ctx

    # ---------- 入口 B：server bundle 根 ----------

    candidates = _find_sub_resources(root)
    if candidates:
        ctx.detected_resources = candidates[:20]  # 防爆库
        ctx.notes.append(
            f"当前不是 resource 但发现 {len(candidates)} 个子 resource"
        )
        # 从 server.cfg 推断
        server_cfg = root / "server.cfg"
        if server_cfg.exists():
            ensures = _parse_server_cfg(server_cfg)
            fw, conf = _framework_from_deps(ensures)
            if fw != Framework.UNKNOWN:
                ctx.framework = fw
                ctx.framework_confidence = conf * 0.7  # cfg 的可信度打折
                ctx.inventory = _inventory_from_deps(ensures)
                ctx.target = _target_from_deps(ensures)
                ctx.notes.append(
                    f"从 server.cfg ensure 列表推断 framework={fw.value}"
                )
        return ctx

    # ---------- 入口 C：什么都不是 ----------

    ctx.notes.append("当前目录不像 FiveM resource 也不像 server bundle 根")
    return ctx


def _find_sub_resources(root: Path, max_depth: int = 4) -> list[Path]:
    """扫 resources/ 子树找含 fxmanifest 的目录。"""
    resources_dir = root / "resources"
    if not resources_dir.exists() or not resources_dir.is_dir():
        return []
    found: list[Path] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth or len(found) >= 200:
            return
        try:
            for child in d.iterdir():
                if child.is_dir():
                    if (child / "fxmanifest.lua").exists() or (
                        child / "__resource.lua"
                    ).exists():
                        found.append(child)
                    else:
                        walk(child, depth + 1)
        except OSError:
            pass

    walk(resources_dir, 0)
    return found


def _parse_server_cfg(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.group("name") for m in _ENSURE_LINE.finditer(text)]


# ============================================================
# system prompt 摘要
# ============================================================


def summarize_for_prompt(ctx: FiveMContext) -> str | None:
    """把 FiveMContext 凝练成一段 system prompt 片段。

    仅在能给玄玑提供有用信息时返回字符串；不像 FiveM 项目时返回 None。
    """
    if not ctx.is_fivem_resource and not ctx.detected_resources:
        return None

    lines = ["【FiveM 项目上下文】"]

    if ctx.is_fivem_resource and ctx.manifest:
        m = ctx.manifest
        lines.append(
            f"- 当前 resource：{m.name or ctx.project_root.name}"
            + (f" v{m.version}" if m.version else "")
        )
        if ctx.framework != Framework.UNKNOWN:
            lines.append(
                f"- framework：{ctx.framework.value}（置信度 {ctx.framework_confidence:.0%}）"
            )
        if ctx.inventory != InventoryKind.UNKNOWN:
            lines.append(f"- inventory：{ctx.inventory.value}")
        if ctx.target != TargetKind.UNKNOWN:
            lines.append(f"- target：{ctx.target.value}")
        if m.dependencies:
            shown = m.dependencies[:8]
            tail = "" if len(m.dependencies) <= 8 else f"…（共 {len(m.dependencies)}）"
            lines.append(f"- dependencies：{', '.join(shown)}{tail}")
    elif ctx.detected_resources:
        names = [p.name for p in ctx.detected_resources[:10]]
        lines.append(
            f"- server bundle 根目录，子 resource：{', '.join(names)}"
        )
        if ctx.framework != Framework.UNKNOWN:
            lines.append(f"- 推断 framework：{ctx.framework.value}")

    if ctx.framework == Framework.UNKNOWN:
        lines.append(
            "- ⚠ framework 未识别——回答 API 用法时需主动询问小宝具体框架"
        )
    if ctx.inventory == InventoryKind.OX_INVENTORY:
        lines.append(
            "- 提示：用 ox_inventory 时，可使用物品要在 items.lua 配 server.export，不走 QBCore.Functions.CreateUseableItem"
        )

    return "\n".join(lines)


__all__ = ["detect_fivem_context", "summarize_for_prompt"]
