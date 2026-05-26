"""Scaffold 引擎：从预设模板生成新 resource 骨架。

设计：
- 6 套 builtin 预设（presets.py 硬编码）
- + 用户预设：玄玑通过 `propose_preset` 落草案到 `<data_dir>/scaffold_drafts/`
  小宝跑 `xuanji preset accept <key>` 升级到 `<data_dir>/scaffold_presets/`
- ScaffoldEngine 启动时 builtin + user 合并加载（同名 user 覆盖 builtin）
- 模板用最小 {{var}} 占位符（不引 jinja2）

不动 file system 直到最后一步，**不会半截污染目录**。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from xuanji.fivem.models import Framework, InventoryKind, TargetKind
from xuanji.fivem.presets import (
    SCAFFOLD_PRESETS,
    ScaffoldFile,
    ScaffoldPreset,
)

# {{ var }} / {{var}} 都接
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render(tpl: str, params: dict[str, str]) -> str:
    """最小模板渲染：替换 {{var}}，缺失变量保持原样不抛错。"""
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), tpl)


@dataclass
class ScaffoldResult:
    """生成结果摘要。"""

    target_dir: Path
    preset: str
    files_written: list[Path] = field(default_factory=list)
    files_skipped: list[Path] = field(default_factory=list)
    """已存在、未覆盖的文件。"""

    @property
    def ok(self) -> bool:
        return bool(self.files_written) or bool(self.files_skipped)


class ScaffoldEngine:
    """Scaffold 执行器。

    加载顺序：builtin 预设 → 用户已激活预设（覆盖同名 builtin）。
    草案目录是独立的，不参与 generate 直到 accept。
    """

    def __init__(
        self,
        *,
        builtin: dict[str, ScaffoldPreset] | None = None,
        user_presets_dir: Path | None = None,
        drafts_dir: Path | None = None,
    ) -> None:
        self._builtin = builtin or SCAFFOLD_PRESETS
        self._user_presets_dir = user_presets_dir
        self._drafts_dir = drafts_dir
        self._user_cache: dict[str, ScaffoldPreset] | None = None

    # ---------------- preset 加载 ----------------

    def _load_user_presets(self) -> dict[str, ScaffoldPreset]:
        if self._user_cache is not None:
            return self._user_cache
        out: dict[str, ScaffoldPreset] = {}
        if self._user_presets_dir is not None and self._user_presets_dir.exists():
            for fp in sorted(self._user_presets_dir.glob("*.json")):
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                    preset = ScaffoldPreset.model_validate(data)
                    out[preset.key] = preset
                except (OSError, json.JSONDecodeError, ValueError):
                    # 损坏的 user preset 不让全局崩——跳过
                    continue
        self._user_cache = out
        return out

    @property
    def presets(self) -> dict[str, ScaffoldPreset]:
        """合并视图：builtin + user（user 覆盖同名 builtin）。"""
        merged = dict(self._builtin)
        merged.update(self._load_user_presets())
        return merged

    def list_presets(self) -> list[dict[str, str]]:
        return [
            {
                "key": k,
                "label": p.label,
                "description": p.description,
                "framework": p.framework.value,
                "inventory": p.inventory.value,
                "target": p.target.value,
                "source": p.source,
            }
            for k, p in self.presets.items()
        ]

    def get(self, key: str) -> ScaffoldPreset:
        merged = self.presets
        if key not in merged:
            raise KeyError(
                f"未知预设：{key!r}。可用：{sorted(merged.keys())}"
            )
        return merged[key]

    # ---------------- 草案 / 激活 / 删除 ----------------

    def list_drafts(self) -> list[ScaffoldPreset]:
        if self._drafts_dir is None or not self._drafts_dir.exists():
            return []
        out: list[ScaffoldPreset] = []
        for fp in sorted(self._drafts_dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                out.append(ScaffoldPreset.model_validate(data))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return out

    def get_draft(self, key: str) -> ScaffoldPreset | None:
        if self._drafts_dir is None:
            return None
        fp = self._drafts_dir / f"{key}.json"
        if not fp.exists():
            return None
        try:
            return ScaffoldPreset.model_validate_json(
                fp.read_text(encoding="utf-8"),
            )
        except (OSError, ValueError):
            return None

    def save_draft(self, preset: ScaffoldPreset) -> Path:
        """玄玑通过 propose_preset 落草案。源标记自动覆盖为 user。"""
        if self._drafts_dir is None:
            raise RuntimeError(
                "ScaffoldEngine 没配 drafts_dir，无法保存草案",
            )
        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        preset = preset.model_copy(update={"source": "user"})
        fp = self._drafts_dir / f"{preset.key}.json"
        fp.write_text(
            preset.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return fp

    def accept_draft(self, key: str) -> Path:
        """小宝 review 通过——把草案移到激活目录，玄玑后续 new 能用到。"""
        if self._drafts_dir is None or self._user_presets_dir is None:
            raise RuntimeError(
                "ScaffoldEngine 没配 drafts_dir / user_presets_dir",
            )
        draft = self.get_draft(key)
        if draft is None:
            raise FileNotFoundError(f"草案不存在：{key}")
        self._user_presets_dir.mkdir(parents=True, exist_ok=True)
        target = self._user_presets_dir / f"{key}.json"
        target.write_text(
            draft.model_dump_json(indent=2),
            encoding="utf-8",
        )
        # 刷缓存让下次 list 看到
        self._user_cache = None
        # 草案已激活就清掉，避免混淆
        (self._drafts_dir / f"{key}.json").unlink(missing_ok=True)
        return target

    def reject_draft(self, key: str) -> bool:
        if self._drafts_dir is None:
            return False
        fp = self._drafts_dir / f"{key}.json"
        if not fp.exists():
            return False
        fp.unlink()
        return True

    def remove_user_preset(self, key: str) -> bool:
        """删除一个已激活的用户预设。builtin 不可删。"""
        if self._user_presets_dir is None:
            return False
        fp = self._user_presets_dir / f"{key}.json"
        if not fp.exists():
            return False
        fp.unlink()
        self._user_cache = None
        return True

    # ---------------- render / generate ----------------

    def render(
        self,
        preset_key: str,
        *,
        resource_name: str,
        author: str = "",
        description: str = "",
        version: str = "1.0.0",
    ) -> list[tuple[Path, str]]:
        """只渲染、不写盘。返回 [(relative_path, content), ...]。"""
        preset = self.get(preset_key)
        params = {
            "name": resource_name,
            "author": author,
            "description": description or preset.description,
            "version": version,
        }
        out: list[tuple[Path, str]] = []
        for f in preset.files:
            rel = Path(_render(f.path, params))
            content = _render(f.content, params)
            out.append((rel, content))
        return out

    def generate(
        self,
        preset_key: str,
        target_dir: Path,
        *,
        resource_name: str | None = None,
        author: str = "",
        description: str = "",
        version: str = "1.0.0",
        overwrite: bool = False,
    ) -> ScaffoldResult:
        """生成到磁盘。

        target_dir：resource 目录（不包含 resources/ 父目录）。
        如果不存在会自动创建；已存在但非空时除非 overwrite=True，否则只生成缺失文件。
        """
        target_dir = target_dir.resolve()
        name = resource_name or target_dir.name
        result = ScaffoldResult(target_dir=target_dir, preset=preset_key)

        rendered = self.render(
            preset_key,
            resource_name=name,
            author=author,
            description=description,
            version=version,
        )

        target_dir.mkdir(parents=True, exist_ok=True)
        for rel, content in rendered:
            full = target_dir / rel
            if full.exists() and not overwrite:
                result.files_skipped.append(full)
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            result.files_written.append(full)
        return result


__all__ = [
    "SCAFFOLD_PRESETS",
    "Framework",
    "InventoryKind",
    "ScaffoldEngine",
    "ScaffoldFile",
    "ScaffoldPreset",
    "ScaffoldResult",
    "TargetKind",
]
