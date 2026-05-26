"""Skills 子系统：markdown + YAML frontmatter，与 Claude Code / Codex 互通。

设计要点：
- 单个 skill 一个 .md 文件，frontmatter 走 YAML，正文走 markdown
- 标准字段（CC/Codex 兼容）：name / description / triggers / tools / allowed_tools
- 玄玑特定字段放 `metadata.xuanji.*`：mode / temperature / risk_floor 等
- 文件可双向迁移：从 CC 拷过来直接能用，玄玑产出的也能给 CC 用

Skill 不引入新调度——它在 Conductor 看来就是一段额外的 system_prompt。
匹配 + 注入由 SkillsLoader 负责，注入时机由调用方（chat / dispatch_subagent）决定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class XuanjiSkillExtensions(BaseModel):
    """玄玑特定的 skill 扩展。CC/Codex 看不见这块，他们 ignore unknown fields。"""

    model_config = {"extra": "allow"}

    mode: str | None = None
    """触发后建议切换到的 PersonaMode（chat/dev/ops/review）"""

    temperature: str | None = None
    """触发后建议的 PersonaTemperature 档位"""

    risk_floor: str | None = None
    """该 skill 涉及的最低风险档（safe/io/exec/net/destructive）。
    Conductor 可据此提前提示 Gate 用户。"""

    role_hint: str | None = None
    """建议哪个 sub-agent role（稷下生 / 百工匠 / 司鉴 / 天枢令）"""


class SkillFrontmatter(BaseModel):
    """skill .md 文件的 YAML frontmatter schema。

    保留 extra 字段，便于 CC/Codex 加它们自己的私有字段而不破坏玄玑端解析。
    """

    model_config = {"extra": "allow"}

    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    """关键词或正则。任一命中就视为该 skill 应激活。"""

    tools: list[str] = Field(default_factory=list)
    """该 skill 期望可用的工具名（参考用，不强制注入）"""

    allowed_tools: list[str] = Field(default_factory=list)
    """显式 allow-list。若非空，调用方应在 dispatch 时把工具集裁剪到这个集合。"""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """杂项。玄玑特定字段从 `metadata.xuanji.*` 读。"""

    @property
    def xuanji(self) -> XuanjiSkillExtensions:
        raw = self.metadata.get("xuanji") or {}
        if not isinstance(raw, dict):
            return XuanjiSkillExtensions()
        return XuanjiSkillExtensions.model_validate(raw)


@dataclass
class Skill:
    """已加载的 skill。"""

    path: Path
    frontmatter: SkillFrontmatter
    body: str
    """markdown 正文，注入时可整段塞进 system prompt 的 extra_fragments。"""

    @property
    def name(self) -> str:
        return self.frontmatter.name

    def matches(self, query: str) -> bool:
        """简单关键词匹配——大小写不敏感，子串命中即可。"""
        q = query.lower()
        for trig in self.frontmatter.triggers:
            if not trig:
                continue
            if trig.lower() in q:
                return True
        return False


class SkillParseError(Exception):
    """skill 文件格式错误。"""


def parse_skill(path: Path) -> Skill:
    """读单个 .md 文件，解析 frontmatter + body。失败抛 SkillParseError。"""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise SkillParseError(f"{path} 没有合法的 YAML frontmatter（--- 分隔）")
    yaml_text, body = m.group(1), m.group(2).strip()
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"{path} frontmatter YAML 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise SkillParseError(f"{path} frontmatter 必须是 mapping")
    try:
        fm = SkillFrontmatter.model_validate(data)
    except Exception as e:
        raise SkillParseError(f"{path} frontmatter 不符 schema：{e}") from e
    return Skill(path=path, frontmatter=fm, body=body)


class SkillsLoader:
    """skills 目录扫描器 + 缓存。

    刷新策略：每次 list/match 都会按 mtime 检查文件，有变化就重读。
    skills 目录通常不大（< 100 个），暴力扫描成本可忽略。
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[Path, tuple[float, Skill]] = {}
        self._errors: dict[Path, str] = {}

    def all(self) -> list[Skill]:
        self._refresh()
        return sorted(
            (s for _, s in self._cache.values()),
            key=lambda s: s.name,
        )

    def get(self, name: str) -> Skill | None:
        for s in self.all():
            if s.name == name:
                return s
        return None

    def match(self, query: str) -> list[Skill]:
        return [s for s in self.all() if s.matches(query)]

    def errors(self) -> dict[str, str]:
        """返回当前扫描期间报错的文件 → 错误信息。"""
        return {str(p): msg for p, msg in self._errors.items()}

    def _refresh(self) -> None:
        if not self.root.exists():
            self._cache.clear()
            self._errors.clear()
            return
        seen: set[Path] = set()
        for path in sorted(self.root.glob("*.md")):
            seen.add(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            cached = self._cache.get(path)
            if cached and cached[0] == mtime:
                continue
            try:
                skill = parse_skill(path)
                self._cache[path] = (mtime, skill)
                self._errors.pop(path, None)
            except SkillParseError as e:
                self._errors[path] = str(e)
                self._cache.pop(path, None)
        # 清掉被删的文件
        for p in list(self._cache.keys()):
            if p not in seen:
                self._cache.pop(p, None)
        for p in list(self._errors.keys()):
            if p not in seen:
                self._errors.pop(p, None)


__all__ = [
    "Skill",
    "SkillFrontmatter",
    "SkillParseError",
    "SkillsLoader",
    "XuanjiSkillExtensions",
    "parse_skill",
]
