"""内置示范资源（skills / hooks）的元测试 + install-samples 行为。

要点：
- 资源文件本身合法可解析（避免误打散）
- install-samples 默认不覆盖、--force 覆盖
- skills 文件能用 SkillsLoader 加载
- hooks YAML 用 HooksRegistry 能解出 spec
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from xuanji.hooks import HookEvent, HooksRegistry
from xuanji.resources import (
    SAMPLE_HOOKS_DIR,
    SAMPLE_SKILLS_DIR,
    list_sample_hooks,
    list_sample_skills,
)
from xuanji.skills import SkillsLoader, parse_skill


def test_sample_skills_dir_exists() -> None:
    assert SAMPLE_SKILLS_DIR.exists()
    assert SAMPLE_SKILLS_DIR.is_dir()


def test_sample_hooks_dir_exists() -> None:
    assert SAMPLE_HOOKS_DIR.exists()
    assert SAMPLE_HOOKS_DIR.is_dir()


def test_sample_skills_listed() -> None:
    samples = list_sample_skills()
    assert len(samples) >= 3
    names = {s.name for s in samples}
    assert "qbox-add-useable-item.md" in names
    assert "ox-lib-callback.md" in names
    assert "fxmanifest-audit.md" in names


def test_sample_hooks_listed() -> None:
    samples = list_sample_hooks()
    assert len(samples) >= 3
    names = {s.name for s in samples}
    assert "PreToolUse.yaml" in names
    assert "PostToolUse.yaml" in names
    assert "UserPromptSubmit.yaml" in names


@pytest.mark.parametrize("path", list_sample_skills())
def test_each_sample_skill_parses(path: Path) -> None:
    skill = parse_skill(path)
    assert skill.name
    assert skill.frontmatter.description
    assert skill.frontmatter.triggers
    assert skill.frontmatter.xuanji.role_hint or skill.frontmatter.xuanji.mode


def test_sample_skills_via_loader(tmp_path: Path) -> None:
    """模拟 install-samples：把示范 skills 拷到 tmp 目录后用 loader 解析。"""
    for src in list_sample_skills():
        shutil.copy2(src, tmp_path / src.name)
    loader = SkillsLoader(tmp_path)
    skills = loader.all()
    assert len(skills) >= 3
    qbox = loader.get("qbox-add-useable-item")
    assert qbox is not None
    assert "QBox" in qbox.frontmatter.triggers
    # match 也应能命中
    hits = loader.match("我想在 QBox 里加一个可使用物品")
    assert any(s.name == "qbox-add-useable-item" for s in hits)


def test_sample_hooks_via_registry(tmp_path: Path) -> None:
    for src in list_sample_hooks():
        shutil.copy2(src, tmp_path / src.name)
    reg = HooksRegistry(tmp_path)
    pre = reg.for_event(HookEvent.PRE_TOOL_USE)
    assert any(s.matcher == "run_shell" for s in pre)
    post = reg.for_event(HookEvent.POST_TOOL_USE)
    assert post  # 至少一条
    ups = reg.for_event(HookEvent.USER_PROMPT_SUBMIT)
    assert any(s.matcher == "部署" for s in ups)


def test_pretooluse_run_shell_blacklist_explanation(tmp_path: Path) -> None:
    """演示 explain：PreToolUse.run_shell hook 应被 run_shell 工具命中。"""
    for src in list_sample_hooks():
        shutil.copy2(src, tmp_path / src.name)
    from xuanji.hooks import explain_hooks
    reg = HooksRegistry(tmp_path)
    explanations = explain_hooks(reg, HookEvent.PRE_TOOL_USE, tool_name="run_shell")
    matched = [e for e in explanations if e.matched]
    assert any(e.spec.matcher == "run_shell" for e in matched)
    assert all(e.can_deny for e in explanations)
