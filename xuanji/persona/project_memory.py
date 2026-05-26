"""项目级记忆与规则文件 XUANJI.md。

设计参考 Claude Code 的 CLAUDE.md：把"这个项目里玄玑该怎么做"沉淀到一份
markdown，进入项目目录就自动加载到 system prompt。

优先级与边界：
- **项目级 XUANJI.md** 从 cwd 沿目录树向上查找（含 git root），找到第一个就停。
  优先级最高，最贴近当前手头的工作。
- **用户级 XUANJI.md** 在 `config_dir() / XUANJI.md`，跨项目共享，是兜底。
- **合成顺序**：用户级 → 项目级（后写后压先写，所以项目级实际优先级更高，
  与"局部覆盖全局"直觉一致）。

文件不存在时静默跳过，玄玑就按默认人设运转。

`init_project_xuanji_md` 提供模板写入：根据 detector 结果生成一份种子内容，
让小宝/玄玑在此基础上继续完善。

不在范围：YAML frontmatter、include 引用、版本控制——保持纯 markdown，
跨工具（Claude Code / Codex / Cursor）肉眼可读。
"""

from __future__ import annotations

from pathlib import Path

from xuanji.config.paths import config_dir

PROJECT_MEMORY_FILENAME = "XUANJI.md"


def find_project_xuanji_md(start: Path | None = None, *, max_levels: int = 12) -> Path | None:
    """从 start 沿目录树向上找 XUANJI.md，返回第一个命中的绝对路径。

    - start 默认为 `Path.cwd()`
    - 命中根目录或越过 max_levels 仍未找到时返回 None
    """
    cwd = (start or Path.cwd()).resolve()
    for level, p in enumerate([cwd, *cwd.parents]):
        if level >= max_levels:
            break
        candidate = p / PROJECT_MEMORY_FILENAME
        if candidate.is_file():
            return candidate
    return None


def user_xuanji_md_path() -> Path:
    """用户级 XUANJI.md 路径（跨项目共享）。"""
    return config_dir() / PROJECT_MEMORY_FILENAME


def load_user_xuanji_md() -> str | None:
    """读用户级 XUANJI.md，不存在返回 None。"""
    p = user_xuanji_md_path()
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def load_project_xuanji_md(start: Path | None = None) -> tuple[Path, str] | None:
    """读项目级 XUANJI.md，不存在返回 None。命中时返回 (路径, 内容)。"""
    found = find_project_xuanji_md(start)
    if found is None:
        return None
    try:
        text = found.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return found, text
    except OSError:
        return None


def collect_xuanji_fragments(start: Path | None = None) -> list[str]:
    """合成所有 XUANJI.md 片段。

    返回顺序：用户级（先）→ 项目级（后）。
    后写入的片段在 system prompt 末尾，模型对靠后的指令更敏感，
    因此项目级实际优先级更高，符合"局部覆盖全局"直觉。

    每段会被包成 `<xuanji_md scope="project|user" path="...">…</xuanji_md>`
    标签，让模型清楚这段规则的来源。
    """
    fragments: list[str] = []
    user_text = load_user_xuanji_md()
    if user_text:
        fragments.append(
            f"【用户级 XUANJI.md（{user_xuanji_md_path()}）】\n{user_text}"
        )
    project = load_project_xuanji_md(start)
    if project is not None:
        path, text = project
        fragments.append(f"【项目级 XUANJI.md（{path}）】\n{text}")
    return fragments


_DEFAULT_TEMPLATE = """\
# 玄玑 · 项目记忆

> 这个文件是玄玑进入本项目时自动加载的"项目宪法"。
> 玄玑会先读项目级 XUANJI.md，再读用户级，越靠下的规则优先级越高。

## 项目身份

- **项目名**：{project_name}
- **类型**：{project_kind}
- **Framework**：{framework}
- **Inventory**：{inventory}
- **Target**：{target}

## 关键约定

- （在这里写本项目的命名、目录、依赖约束）
- （比如：物品都注册在 `qbx_core/shared/items.lua`）
- （比如：服务端事件统一前缀 `myresource:server:xxx`）

## 玄玑该怎么做

- 默认 framework：**{framework}**——除非明确说明，否则按这个写代码。
- 默认 inventory：**{inventory}**——加可使用物品时优先使用对应 API。
- 默认 target：**{target}**——交互点用对应的 zone API。
- （在这里加你希望玄玑遵守的项目规矩）

## 玄玑不该做

- （在这里加该项目的禁区，比如：不要碰 legacy 目录）
- （比如：不要主动改 server.cfg）

## 上下文片段（可选）

<!-- 这一段是给玄玑长期记的项目上下文，比如某个 bug 的根因、某段历史决策。 -->
"""


def render_default_template(
    project_name: str,
    *,
    project_kind: str = "FiveM resource / NPC plugin",
    framework: str = "未识别（请补全）",
    inventory: str = "未识别（请补全）",
    target: str = "未识别（请补全）",
) -> str:
    """生成一份种子模板。可由 detector 结果填充各字段。"""
    return _DEFAULT_TEMPLATE.format(
        project_name=project_name,
        project_kind=project_kind,
        framework=framework,
        inventory=inventory,
        target=target,
    )


def init_project_xuanji_md(
    project_root: Path,
    *,
    overwrite: bool = False,
    content: str | None = None,
) -> tuple[Path, bool]:
    """在 project_root 写一份 XUANJI.md。

    - overwrite=False 时：文件已存在则 raise FileExistsError（保护用户已有内容）
    - content 提供则原样写入；否则用 detector 结果填默认模板
    - 返回 (path, created)；created=True 表示新建，False 表示覆盖

    detector 失败不抛错——会用"未识别"占位符，让小宝手填。
    """
    target_path = project_root / PROJECT_MEMORY_FILENAME
    existed = target_path.exists()
    if existed and not overwrite:
        raise FileExistsError(f"{target_path} 已存在，加 overwrite=True 才覆盖。")

    if content is None:
        content = _build_seed_content(project_root)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return target_path, not existed


def _build_seed_content(project_root: Path) -> str:
    """从 detector 结果合成种子内容；探测失败用占位符。"""
    project_name = project_root.name or "untitled"
    framework = inventory = target = "未识别（请补全）"
    project_kind = "FiveM resource / NPC plugin"
    try:
        from xuanji.fivem import detect_fivem_context

        ctx = detect_fivem_context(project_root)
        if ctx.framework.value != "unknown":
            framework = ctx.framework.value
        if ctx.inventory.value != "unknown":
            inventory = ctx.inventory.value
        if ctx.target.value != "unknown":
            target = ctx.target.value
        if ctx.is_fivem_resource:
            project_kind = "FiveM resource"
        elif ctx.detected_resources:
            project_kind = f"FiveM server bundle（含 {len(ctx.detected_resources)} 个 resource）"
    except Exception:
        # detector 失败不应阻塞 init——用占位符即可，小宝会手填
        pass

    return render_default_template(
        project_name,
        project_kind=project_kind,
        framework=framework,
        inventory=inventory,
        target=target,
    )


__all__ = [
    "PROJECT_MEMORY_FILENAME",
    "collect_xuanji_fragments",
    "find_project_xuanji_md",
    "init_project_xuanji_md",
    "load_project_xuanji_md",
    "load_user_xuanji_md",
    "render_default_template",
    "user_xuanji_md_path",
]
