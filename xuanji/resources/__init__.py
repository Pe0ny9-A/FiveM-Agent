"""玄玑内置示范资源：skills / hooks。

这些文件被打进 wheel；CLI 命令 `xuanji skill-file install-samples` 与
`xuanji hook install-samples` 会把它们拷贝到用户的 skills_dir() / hooks_dir()。

用户拷贝后可自由编辑——本目录的版本只作为「初始模板」存在。
"""

from __future__ import annotations

from pathlib import Path

RESOURCES_ROOT = Path(__file__).parent
SAMPLE_SKILLS_DIR = RESOURCES_ROOT / "skills"
SAMPLE_HOOKS_DIR = RESOURCES_ROOT / "hooks"


def list_sample_skills() -> list[Path]:
    """返回所有内置示范 skill 文件路径。"""
    if not SAMPLE_SKILLS_DIR.exists():
        return []
    return sorted(SAMPLE_SKILLS_DIR.glob("*.md"))


def list_sample_hooks() -> list[Path]:
    """返回所有内置示范 hook 文件路径。"""
    if not SAMPLE_HOOKS_DIR.exists():
        return []
    return sorted(SAMPLE_HOOKS_DIR.glob("*.yaml"))


__all__ = [
    "RESOURCES_ROOT",
    "SAMPLE_HOOKS_DIR",
    "SAMPLE_SKILLS_DIR",
    "list_sample_hooks",
    "list_sample_skills",
]
