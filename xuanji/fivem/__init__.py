"""FiveM 专精层 · 项目识别与脚手架。

不属于七大子系统之一——这是 0.4.0 新加的"领域知识层"，
让玄玑在 FiveM 资源目录里"开箱即懂"，不用每次问框架版本。

模块：
- models：FiveMContext 等数据模型
- manifest：fxmanifest.lua 解析
- detector：从工程目录推断 framework / inventory / target
- scaffold：从模板生成新 resource 骨架
"""

from xuanji.fivem.detector import detect_fivem_context, summarize_for_prompt
from xuanji.fivem.models import (
    FiveMContext,
    Framework,
    FxManifest,
    InventoryKind,
    TargetKind,
)
from xuanji.fivem.scaffold import (
    SCAFFOLD_PRESETS,
    ScaffoldEngine,
    ScaffoldResult,
)

__all__ = [
    "SCAFFOLD_PRESETS",
    "FiveMContext",
    "Framework",
    "FxManifest",
    "InventoryKind",
    "ScaffoldEngine",
    "ScaffoldResult",
    "TargetKind",
    "detect_fivem_context",
    "summarize_for_prompt",
]
