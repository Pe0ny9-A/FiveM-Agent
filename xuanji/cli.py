"""玄玑 CLI。

命令族：
- xuanji version        版本与运行环境
- xuanji info           当前激活配置概览
- xuanji init           首次使用向导（交互式配置 + 种子导入）
- xuanji doctor         自检：环境 / 配置 / 数据库 / profile 可用性
- xuanji config path    显示配置文件路径
- xuanji config list    列出所有 profile
- xuanji config show    查看某个 profile 详情（密钥脱敏）
- xuanji config add     新增 profile（交互式）
- xuanji config use     切换激活 profile
- xuanji config remove  删除 profile
- xuanji config test    实际请求一条 hello 验证 profile 可用
- xuanji chat           进入流式对话（CHAT 模式）
- xuanji serve          启动 FastAPI 服务（HTTP + WebSocket）
- xuanji ipc            启动 stdio JSON-RPC 后端（VS Code / 桌面端用）
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Any

# Windows 默认 GBK 终端遇到非 ANSI 字符会崩，统一切到 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from xuanji.capability.tool import Tool
from xuanji.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
    config_file_path,
    factory_db_path,
    knowledge_db_path,
    memory_db_path,
    scaffold_drafts_dir,
    scaffold_presets_dir,
    tool_drafts_dir,
    tool_published_dir,
    tool_staged_dir,
)
from xuanji.config.profiles import DEFAULT_MODELS, OFFICIAL_BASE_URLS
from xuanji.fivem.scaffold import ScaffoldEngine
from xuanji.gate.bridge import HITLBridge
from xuanji.knowledge import SqliteKnowledgeStore
from xuanji.knowledge.sources import seed_chunks, seed_sources, seed_symbols
from xuanji.llm.providers.base import Message
from xuanji.llm.providers.factory import build_provider
from xuanji.memory import Memory, MemoryKind, MemoryScope, SqliteMemoryStore
from xuanji.neural.session_store import (
    ChatSessionSnapshot,
    clear_last_session,
    format_age,
    load_last_session,
    save_last_session,
)

app = typer.Typer(
    add_completion=False,
    help="玄玑 · FiveM 智能体 CLI",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
config_app = typer.Typer(help="配置管理：profile 增删改与激活切换", no_args_is_help=True)
knowledge_app = typer.Typer(
    help="稷下学宫：FiveM 知识库管理（采集 / 检索 / 命名空间）",
    no_args_is_help=True,
)
memory_app = typer.Typer(
    help="怀玉阁：记忆库管理（写入 / 召回 / 遗忘 / 固化）",
    no_args_is_help=True,
)
skill_app = typer.Typer(
    help="技能：玄玑学到的可复用做事套路（procedural memory 薄壳）",
    no_args_is_help=True,
)
skill_file_app = typer.Typer(
    help="Skills 文件：markdown + frontmatter，与 Claude Code / Codex 互通",
    no_args_is_help=True,
)
hook_app = typer.Typer(
    help="Hooks：YAML + Pre/PostToolUse / UserPromptSubmit / Notification",
    no_args_is_help=True,
)
tool_app = typer.Typer(
    help="工具：列出已注册工具 / 查看 propose_tool 草案",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")
app.add_typer(skill_file_app, name="skill-file")
app.add_typer(hook_app, name="hook")
app.add_typer(tool_app, name="tool")

fivem_app = typer.Typer(
    help="FiveM 项目识别与脚手架（detect / new / analyze）",
    no_args_is_help=True,
)
preset_app = typer.Typer(
    help="Scaffold 预设管理：列出 / 查看 / 接受/拒绝 玄玑提交的预设草案",
    no_args_is_help=True,
)
project_app = typer.Typer(
    help="项目级记忆：XUANJI.md 创建 / 查看 / 路径定位",
    no_args_is_help=True,
)
app.add_typer(fivem_app, name="fivem")
app.add_typer(preset_app, name="preset")
app.add_typer(project_app, name="project")

console = Console()


def _mask(s: str, keep: int = 4) -> str:
    """密钥脱敏：保留首尾各 keep 位，中间星号。"""
    if not s:
        return ""
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}{'*' * 8}{s[-keep:]}"


def _profile_summary(p: Profile) -> str:
    """单行摘要，用于 list 展示。"""
    base = f"[{p.kind.value}] model={p.default_model}"
    if isinstance(p, OpenAICompatibleProfile):
        base += f" base_url={p.base_url}"
    return base


# ---------- version ----------


@app.command()
def version() -> None:
    """显示玄玑版本与运行环境。"""
    import platform

    from xuanji import __version__

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("xuanji", __version__)
    table.add_row("python", f"{platform.python_version()} ({sys.executable})")
    table.add_row("platform", f"{platform.system()} {platform.release()}")
    table.add_row("config_dir", str(config_file_path().parent))
    console.print(table)


# ---------- info ----------


@app.command()
def info() -> None:
    """查看当前激活配置概览。"""
    cfg = ConfigStore().load()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("config_path", str(config_file_path()))
    table.add_row("active_profile", cfg.active_profile or "[dim]未设置[/dim]")
    table.add_row("persona_temperature", cfg.persona_temperature.value)
    table.add_row("assistant_alias", f"{cfg.assistant_alias}  [dim](玄玑自称)[/dim]")
    table.add_row("user_alias", f"{cfg.user_alias}  [dim](玄玑对你的称呼)[/dim]")
    table.add_row("profiles_count", str(len(cfg.profiles)))
    active = cfg.get_active()
    if active:
        table.add_row("active.kind", active.kind.value)
        table.add_row("active.model", active.default_model)
        table.add_row("active.api_key", _mask(active.api_key))
        if isinstance(active, OpenAICompatibleProfile):
            table.add_row("active.base_url", str(active.base_url))
    console.print(table)


# ---------- init ----------


def _do_init(
    profile_name: str,
    kind: ProfileKind,
    api_key: str,
    base_url: str | None,
    seed_knowledge: bool,
    skip_test: bool,
) -> None:
    """init 命令的纯函数核心，便于单测。"""
    common = {
        "label": profile_name,
        "api_key": api_key,
        "default_model": DEFAULT_MODELS[kind],
    }
    profile: Profile
    if kind == ProfileKind.ANTHROPIC:
        profile = AnthropicProfile(**common)
    elif kind == ProfileKind.OPENAI:
        profile = OpenAIProfile(**common)
    elif kind == ProfileKind.DEEPSEEK:
        profile = DeepSeekProfile(**common)
    elif kind == ProfileKind.OPENAI_COMPATIBLE:
        if not base_url:
            console.print("[red]openai-compatible 必须提供 base_url[/red]")
            raise typer.Exit(1)
        profile = OpenAICompatibleProfile(base_url=base_url, **common)

    ConfigStore().upsert_profile(profile_name, profile, activate=True)
    console.print(f"[green]✓ profile [bold]{profile_name}[/bold] 已保存并激活[/green]")

    if seed_knowledge:
        store = _open_knowledge_store()
        sources = seed_sources()
        symbols = seed_symbols()
        chunks = seed_chunks()
        for src in sources:
            store.upsert_source(src)
        store.upsert_symbols(symbols)
        store.upsert_chunks(chunks)
        console.print(
            f"[green]✓ 种子已导入：{len(sources)} sources / "
            f"{len(symbols)} symbols / {len(chunks)} chunks[/green]"
        )

    if not skip_test:
        try:
            asyncio.run(_test_profile(profile_name))
        except typer.Exit:
            console.print(
                "[yellow]测试未通过——profile 已保存，"
                "等小宝补完 API Key 再 [bold]xuanji config test[/bold] 验一次。[/yellow]"
            )


@app.command()
def init(
    name: str | None = typer.Option(
        None, "--name", "-n", help="profile 名（短标识）；不传走交互向导",
    ),
    kind: ProfileKind | None = typer.Option(
        None, "--kind", "-k",
        help="provider 种类（anthropic/openai/deepseek/openai-compatible）；不传走交互向导",
    ),
    api_key: str | None = typer.Option(
        None, "--api-key",
        help="API Key；不传走交互向导（hidden 输入）",
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", "-u",
        help="openai-compatible 必填",
    ),
    seed_knowledge: bool = typer.Option(
        True, "--seed/--no-seed",
        help="是否导入 FiveM 种子知识（QBCore/ox_lib/...）",
    ),
    skip_test: bool = typer.Option(
        False, "--skip-test",
        help="跳过 profile 实际请求测试",
    ),
) -> None:
    """首次使用向导：建 profile + 导入种子 + 测试连接。

    无参数运行时进入交互向导，逐项选 provider / 模型 / API Key；
    全部通过 flag 传入时走非交互快路径（便于脚本与 CI）。
    """
    console.print(
        Panel(
            "玄玑首次使用向导\n"
            "建一个默认 profile、导入 FiveM 种子知识、做一次连通性测试。\n"
            "[dim]全部步骤完成后，xuanji chat 就能直接用了。[/dim]",
            border_style="magenta",
            title="[magenta]玄玑 init[/magenta]",
        )
    )

    if kind is None:
        name, kind, api_key, base_url = _init_wizard(
            name_hint=name, base_url_hint=base_url,
        )
    else:
        if name is None:
            name = "default"
        if api_key is None:
            api_key = typer.prompt("API Key", hide_input=True)

    _do_init(name, kind, api_key, base_url, seed_knowledge, skip_test)
    console.print(
        "[green]姐姐这边都准备好了。[/green]\n"
        "[dim]下一步：[bold]xuanji chat[/bold] 进入对话，"
        "或 [bold]xuanji doctor[/bold] 再做一次环境自检。[/dim]"
    )


_WIZARD_OPTIONS: list[tuple[str, ProfileKind, str]] = [
    ("Claude", ProfileKind.ANTHROPIC, "Anthropic 官方端点"),
    ("GPT", ProfileKind.OPENAI, "OpenAI 官方端点"),
    ("DeepSeek", ProfileKind.DEEPSEEK, "DeepSeek 官方端点（0.9.3 默认偏好）"),
    ("自定义 Base URL", ProfileKind.OPENAI_COMPATIBLE,
     "OneAPI / Ollama / Kimi / 智谱 / 火山方舟 / 其他 OpenAI 兼容端点"),
]


def _init_wizard(
    *, name_hint: str | None, base_url_hint: str | None,
) -> tuple[str, ProfileKind, str, str | None]:
    """交互式向导：返回 (profile_name, kind, api_key, base_url)。

    UI 格式参考 Claude Code 的 init 向导，rich 表格 + typer.prompt 数字选择。
    """
    table = Table(
        title="选一个 provider",
        show_lines=False,
        title_style="bold magenta",
    )
    table.add_column("#", style="cyan", no_wrap=True, width=3)
    table.add_column("名称", style="bold", no_wrap=True)
    table.add_column("默认模型", style="green", no_wrap=True)
    table.add_column("说明", style="dim")
    for idx, (label, k, desc) in enumerate(_WIZARD_OPTIONS, 1):
        table.add_row(str(idx), label, DEFAULT_MODELS[k], desc)
    console.print(table)

    choice = typer.prompt(
        "请输入序号（默认 3，姐姐推荐 DeepSeek）",
        default="3",
    ).strip()
    try:
        n = int(choice)
        if not 1 <= n <= len(_WIZARD_OPTIONS):
            raise ValueError
    except ValueError as exc:
        console.print(f"[red]无效序号：{choice}[/red]")
        raise typer.Exit(1) from exc

    label, kind, _ = _WIZARD_OPTIONS[n - 1]

    default_name = name_hint or {
        ProfileKind.ANTHROPIC: "claude",
        ProfileKind.OPENAI: "gpt",
        ProfileKind.DEEPSEEK: "deepseek",
        ProfileKind.OPENAI_COMPATIBLE: "custom",
    }[kind]
    profile_name = typer.prompt("profile 名（短标识）", default=default_name).strip()
    if not profile_name:
        console.print("[red]profile 名不能为空[/red]")
        raise typer.Exit(1)

    base_url: str | None = None
    if kind == ProfileKind.OPENAI_COMPATIBLE:
        base_url = typer.prompt(
            "Base URL（如 https://oneapi.example.com/v1）",
            default=base_url_hint or "",
        ).strip()
        if not base_url:
            console.print("[red]Base URL 不能为空[/red]")
            raise typer.Exit(1)

    api_key = typer.prompt(f"{label} API Key", hide_input=True).strip()
    if not api_key:
        console.print("[red]API Key 不能为空[/red]")
        raise typer.Exit(1)

    console.print(
        f"[dim]→ {label} · profile={profile_name} · "
        f"model={DEFAULT_MODELS[kind]}{f' · base={base_url}' if base_url else ''}[/dim]"
    )
    return profile_name, kind, api_key, base_url


# ---------- doctor ----------


def _doctor_checks() -> list[tuple[str, bool, str]]:
    """返回 (项目, 通过?, 详情) 列表。纯函数，便于单测。"""
    import importlib
    import platform

    checks: list[tuple[str, bool, str]] = []

    # 1. Python 版本
    py = platform.python_version_tuple()
    py_ok = (int(py[0]), int(py[1])) >= (3, 12)
    checks.append((
        "python>=3.12",
        py_ok,
        f"{platform.python_version()}",
    ))

    # 2. 关键依赖
    for mod in ["typer", "rich", "pydantic", "anthropic", "openai", "httpx", "jieba"]:
        try:
            importlib.import_module(mod)
            checks.append((f"import {mod}", True, "ok"))
        except ImportError as e:
            checks.append((f"import {mod}", False, str(e)))

    # 3. 配置文件
    cfg_path = config_file_path()
    if cfg_path.exists():
        try:
            cfg = ConfigStore().load()
            checks.append((
                "config.json",
                True,
                f"{cfg_path}（{len(cfg.profiles)} profile / "
                f"active={cfg.active_profile or '未设置'}）",
            ))
            # 4. 至少一个激活 profile
            if cfg.get_active():
                checks.append(("active profile", True, cfg.active_profile or ""))
            else:
                checks.append((
                    "active profile",
                    False,
                    "未设置——跑 [bold]xuanji init[/bold] 或 [bold]xuanji config add[/bold]",
                ))
        except ValueError as e:
            checks.append(("config.json", False, str(e)))
    else:
        checks.append((
            "config.json",
            False,
            "不存在——跑 [bold]xuanji init[/bold] 创建",
        ))
        checks.append(("active profile", False, "（未配置）"))

    # 5. 数据目录可写
    try:
        from xuanji.config import data_dir

        d = data_dir()
        probe = d / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("data dir writable", True, str(d)))
    except OSError as e:
        checks.append(("data dir writable", False, str(e)))

    # 6. 知识库
    try:
        store = _open_knowledge_store()
        s = store.stats()
        n_chunks = int(s["chunks"])
        n_sources = int(s["sources"])
        if n_chunks == 0:
            checks.append((
                "knowledge db",
                False,
                "空——跑 [bold]xuanji knowledge ingest[/bold] 导种子",
            ))
        else:
            checks.append((
                "knowledge db",
                True,
                f"{n_sources} sources / {n_chunks} chunks",
            ))
    except (OSError, RuntimeError) as e:
        checks.append(("knowledge db", False, str(e)))

    return checks


@app.command()
def doctor() -> None:
    """环境自检：Python/依赖/配置/数据库/profile。"""
    checks = _doctor_checks()
    table = Table(title="玄玑 · 环境自检", show_lines=False)
    table.add_column("项目", style="cyan", no_wrap=True)
    table.add_column("结果", justify="center")
    table.add_column("详情", overflow="fold")
    fail = 0
    for name, ok, detail in checks:
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(name, mark, detail)
        if not ok:
            fail += 1
    console.print(table)
    if fail == 0:
        console.print("[green]全部通过——姐姐这儿一切正常。[/green]")
    else:
        console.print(f"[yellow]{fail} 项需要小宝处理一下。[/yellow]")
        raise typer.Exit(1)


# ---------- config path ----------


@config_app.command("path")
def config_path() -> None:
    """显示配置文件路径。"""
    console.print(str(config_file_path()))


# ---------- config list ----------


@config_app.command("list")
def config_list() -> None:
    """列出所有 profile。"""
    cfg = ConfigStore().load()
    if not cfg.profiles:
        console.print(
            "[yellow]还没有配置过 profile，先用 [bold]xuanji config add[/bold] 加一个。[/yellow]"
        )
        return
    table = Table(title="玄玑 · profile 列表", show_lines=False)
    table.add_column("名称", style="cyan", no_wrap=True)
    table.add_column("kind", style="magenta")
    table.add_column("默认模型")
    table.add_column("base_url", overflow="fold")
    table.add_column("API Key")
    table.add_column("激活", justify="center")
    for name, p in cfg.profiles.items():
        base_url = (
            str(p.base_url)
            if isinstance(p, OpenAICompatibleProfile)
            else OFFICIAL_BASE_URLS.get(p.kind, "-")
        )
        active_mark = "[green]●[/green]" if name == cfg.active_profile else ""
        table.add_row(
            name, p.kind.value, p.default_model, base_url, _mask(p.api_key), active_mark
        )
    console.print(table)


# ---------- config show ----------


@config_app.command("show")
def config_show(name: str) -> None:
    """查看某个 profile 详情（密钥脱敏）。"""
    cfg = ConfigStore().load()
    p = cfg.profiles.get(name)
    if not p:
        console.print(f"[red]找不到 profile：{name}[/red]")
        raise typer.Exit(1)
    data = p.model_dump(mode="json")
    data["api_key"] = _mask(p.api_key)
    table = Table(show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column()
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(Panel(table, title=f"profile · {name}", border_style="magenta"))


# ---------- config add ----------


@config_app.command("add")
def config_add(
    name: str = typer.Argument(..., help="profile 名称（短标识，用于切换）"),
    kind: ProfileKind = typer.Option(..., "--kind", "-k", help="provider 种类"),
    api_key: str = typer.Option(..., "--api-key", prompt=True, hide_input=True, help="API Key"),
    label: str | None = typer.Option(None, "--label", "-l", help="人类可读名（默认同 name）"),
    model: str | None = typer.Option(None, "--model", "-m", help="默认模型 id（不填用 kind 推荐值）"),
    base_url: str | None = typer.Option(
        None, "--base-url", "-u", help="仅 openai-compatible 必填"
    ),
    activate: bool = typer.Option(True, "--activate/--no-activate", help="是否同时激活"),
) -> None:
    """新增或覆盖一个 profile。"""
    label_final = label or name
    model_final = model or DEFAULT_MODELS[kind]
    common = {"label": label_final, "api_key": api_key, "default_model": model_final}

    profile: Profile
    try:
        if kind == ProfileKind.ANTHROPIC:
            profile = AnthropicProfile(**common)
        elif kind == ProfileKind.OPENAI:
            profile = OpenAIProfile(**common)
        elif kind == ProfileKind.DEEPSEEK:
            profile = DeepSeekProfile(**common)
        elif kind == ProfileKind.OPENAI_COMPATIBLE:
            if not base_url:
                console.print("[red]openai-compatible 必须提供 --base-url[/red]")
                raise typer.Exit(1)
            profile = OpenAICompatibleProfile(base_url=base_url, **common)
    except ValidationError as e:
        console.print(f"[red]profile 校验失败：\n{e}[/red]")
        raise typer.Exit(1) from e

    ConfigStore().upsert_profile(name, profile, activate=activate)
    console.print(
        f"[green]已保存 profile [bold]{name}[/bold]"
        f"{'，并激活' if activate else ''}。[/green]"
    )


# ---------- config use ----------


@config_app.command("use")
def config_use(name: str) -> None:
    """切换激活 profile。"""
    try:
        ConfigStore().use_profile(name)
    except KeyError:
        console.print(f"[red]找不到 profile：{name}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]已切换到 [bold]{name}[/bold]。[/green]")


# ---------- config remove ----------


@config_app.command("remove")
def config_remove(
    name: str,
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除一个 profile。"""
    if not force and not typer.confirm(f"确定删除 profile {name}？"):
        raise typer.Exit()
    ok = ConfigStore().remove_profile(name)
    if not ok:
        console.print(f"[red]找不到 profile：{name}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]已删除 profile [bold]{name}[/bold]。[/green]")


# ---------- config alias ----------


@config_app.command("alias")
def config_alias(
    self_name: str = typer.Option(
        None,
        "--self",
        "-s",
        help='玄玑自称（默认"姐姐"）。例如：师父、玄玑姐、老板娘',
    ),
    user_name: str = typer.Option(
        None,
        "--user",
        "-u",
        help='玄玑对你的称呼（默认"小宝"）。例如：徒儿、阿白、东家',
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="重置为默认值（姐姐 / 小宝）",
    ),
) -> None:
    """设置玄玑在对话中的称呼。

    玄玑的真名永远是"玄玑"——CLI 框架文字、流式回复 panel 的标题不会变。
    这里只改对话内容里玄玑的自称（assistant_alias）和对用户的称呼（user_alias）。
    """
    if reset:
        ConfigStore().set_aliases(user_alias="小宝", assistant_alias="姐姐")
        console.print("[green]称呼已重置为默认：玄玑自称『姐姐』，对你称『小宝』。[/green]")
        return

    if self_name is None and user_name is None:
        cfg = ConfigStore().load()
        console.print(
            f"当前称呼：\n"
            f"  玄玑自称：[magenta]{cfg.assistant_alias}[/magenta]\n"
            f"  玄玑对你称：[cyan]{cfg.user_alias}[/cyan]\n"
            f"\n用 [bold]--self[/bold] / [bold]--user[/bold] 修改，或 [bold]--reset[/bold] 重置。"
        )
        return

    ConfigStore().set_aliases(user_alias=user_name, assistant_alias=self_name)
    cfg = ConfigStore().load()
    console.print(
        f"[green]称呼已更新：玄玑自称『{cfg.assistant_alias}』，对你称『{cfg.user_alias}』。[/green]"
    )


# ---------- config test ----------


async def _test_profile(name: str | None = None) -> None:
    cfg = ConfigStore().load()
    profile_name = name or cfg.active_profile
    if not profile_name:
        console.print("[red]没有指定 profile，且没有激活 profile。[/red]")
        raise typer.Exit(1)
    profile = cfg.profiles.get(profile_name)
    if not profile:
        console.print(f"[red]找不到 profile：{profile_name}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[cyan]正在用 [bold]{profile_name}[/bold]"
        f"（{profile.kind.value} · {profile.default_model}）发一条测试请求……[/cyan]"
    )
    from xuanji.llm.providers.base import Message

    provider = build_provider(profile)
    try:
        msg = await provider.chat(
            model=profile.default_model,
            messages=[Message(role="user", content="ping")],
            system="只回复『连接成功』四个字，不要加标点。",
            max_tokens=32,
        )
    except Exception as e:
        console.print(f"[red]调用失败：{type(e).__name__}: {e}[/red]")
        raise typer.Exit(1) from e

    console.print(
        Panel(
            f"[green]通过[/green]\n"
            f"模型回复：{msg.text}\n"
            f"[dim]usage: in={msg.usage.input_tokens} "
            f"out={msg.usage.output_tokens}[/dim]",
            title=f"测试 · {profile_name}",
            border_style="green",
        )
    )


@config_app.command("test")
def config_test(
    name: str = typer.Argument(None, help="要测的 profile 名（不传则测当前激活）"),
) -> None:
    """实际请求一次，验证 profile 可用。"""
    asyncio.run(_test_profile(name))


# ---------- config mcp ----------

mcp_app = typer.Typer(
    help="MCP server：收编外部工具（spec 兼容 Claude Code / Codex）",
    no_args_is_help=True,
)
config_app.add_typer(mcp_app, name="mcp")


@mcp_app.command("list")
def config_mcp_list() -> None:
    """列出所有 MCP server 配置。"""
    cfg = ConfigStore().load()
    if not cfg.mcp_servers:
        console.print("[yellow]还没有配 MCP server。[/yellow]")
        console.print(
            "用 [bold]xuanji config mcp add --name X --command Y --args ...[/bold] 加一个。"
        )
        return
    table = Table(title="MCP servers")
    table.add_column("名称", style="cyan", no_wrap=True)
    table.add_column("transport")
    table.add_column("命令 / URL", overflow="fold")
    table.add_column("状态")
    for s in cfg.mcp_servers:
        cmd_text = s.command or s.url or "-"
        if s.args:
            cmd_text = f"{cmd_text} {' '.join(s.args)}"
        status = "[green]on[/green]" if s.enabled else "[dim]off[/dim]"
        table.add_row(s.name, s.transport, cmd_text, status)
    console.print(table)


@mcp_app.command("add")
def config_mcp_add(
    name: str = typer.Option(..., "--name", help="server 显式名（工具前缀）"),
    command: str = typer.Option(None, "--command", help="stdio 模式下的可执行文件"),
    args: list[str] = typer.Option(
        None, "--arg", "-a",
        help="传给 command 的参数，可重复多次：-a foo -a bar",
    ),
    url: str = typer.Option(None, "--url", help="http+sse 模式的 server URL"),
    cwd: str = typer.Option(None, "--cwd", help="子进程工作目录"),
    description: str = typer.Option("", "--description"),
    enabled: bool = typer.Option(True, "--enabled/--disabled"),
) -> None:
    """新增（或按名覆盖）一个 MCP server 配置。"""
    from xuanji.mcp.registry import McpServerConfig

    if not command and not url:
        console.print("[red]必须给 --command 或 --url 之一[/red]")
        raise typer.Exit(1)
    transport = "stdio" if command else "http+sse"
    server = McpServerConfig(
        name=name,
        transport=transport,
        command=command,
        args=list(args or []),
        cwd=cwd,
        url=url,
        description=description,
        enabled=enabled,
    )
    ConfigStore().upsert_mcp_server(server)
    console.print(f"[green]已保存 MCP server[/green] [bold]{name}[/bold]")


@mcp_app.command("remove")
def config_mcp_remove(
    name: str = typer.Argument(..., help="要删除的 server 名"),
) -> None:
    """删除一个 MCP server 配置。"""
    if ConfigStore().remove_mcp_server(name):
        console.print(f"[green]已删除[/green] {name}")
    else:
        console.print(f"[yellow]未找到 server：{name}[/yellow]")
        raise typer.Exit(1)


@mcp_app.command("enable")
def config_mcp_enable(name: str) -> None:
    """启用一个 MCP server。"""
    if ConfigStore().set_mcp_enabled(name, True):
        console.print(f"[green]已启用[/green] {name}")
    else:
        raise typer.Exit(1)


@mcp_app.command("disable")
def config_mcp_disable(name: str) -> None:
    """暂停一个 MCP server（保留配置但不连）。"""
    if ConfigStore().set_mcp_enabled(name, False):
        console.print(f"[yellow]已停用[/yellow] {name}")
    else:
        raise typer.Exit(1)


@mcp_app.command("test")
def config_mcp_test(
    name: str = typer.Argument(..., help="要试连的 server 名"),
) -> None:
    """实际拉起一次 server，跑 initialize + tools/list 验证连通。"""
    from xuanji.mcp.registry import McpClientRegistry

    cfg = ConfigStore().load()
    found = next((s for s in cfg.mcp_servers if s.name == name), None)
    if found is None:
        console.print(f"[red]没找到 server：{name}[/red]")
        raise typer.Exit(1)

    async def _run() -> None:
        reg = McpClientRegistry([found])
        await reg.connect_all()
        handle = reg.handles.get(name)
        try:
            if handle is None or handle.error:
                msg = handle.error if handle else "未知错误"
                console.print(f"[red]连接失败[/red]：{msg}")
                raise typer.Exit(1)
            console.print(
                Panel(
                    f"[green]通过[/green]\n"
                    f"server: {handle.client.server_info.serverInfo.name if handle.client.server_info else '?'}"
                    f"\ntools: {len(handle.tools)}",
                    title=f"MCP · {name}",
                    border_style="green",
                )
            )
            for t in handle.tools[:10]:
                console.print(f"  • [cyan]{t.name}[/cyan]  {t.description[:60]}")
            if len(handle.tools) > 10:
                console.print(f"  [dim]…还有 {len(handle.tools) - 10} 个[/dim]")
        finally:
            await reg.close_all()

    asyncio.run(_run())


# ---------- knowledge ----------


def _open_knowledge_store() -> SqliteKnowledgeStore:
    return SqliteKnowledgeStore(knowledge_db_path())


@knowledge_app.command("path")
def knowledge_path() -> None:
    """显示知识库 SQLite 文件路径。"""
    console.print(str(knowledge_db_path()))


@knowledge_app.command("stats")
def knowledge_stats() -> None:
    """显示知识库统计：sources / chunks / symbols / 命名空间。"""
    store = _open_knowledge_store()
    s = store.stats()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("path", str(s["path"]))
    table.add_row("sources", str(s["sources"]))
    table.add_row("chunks", str(s["chunks"]))
    table.add_row("symbols", str(s["symbols"]))
    table.add_row("namespaces", ", ".join(s["namespaces"]) or "[dim]空[/dim]")
    console.print(table)


@knowledge_app.command("list")
def knowledge_list() -> None:
    """列出所有 source。"""
    store = _open_knowledge_store()
    sources = store.list_sources()
    if not sources:
        console.print(
            "[yellow]知识库还是空的。先 [bold]xuanji knowledge ingest[/bold] "
            "导入种子数据。[/yellow]"
        )
        return
    table = Table(title="稷下学宫 · 数据源")
    table.add_column("命名空间", style="cyan", no_wrap=True)
    table.add_column("标题")
    table.add_column("版本", style="magenta")
    table.add_column("URL", overflow="fold")
    for s in sources:
        table.add_row(s.namespace, s.title, s.version or "-", s.url or "-")
    console.print(table)


@knowledge_app.command("ingest")
def knowledge_ingest(
    seeds: bool = typer.Option(
        True,
        "--seeds/--no-seeds",
        help="是否导入手写种子数据（QBCore / ox_lib / ox_inventory / cfx）",
    ),
) -> None:
    """导入知识库内容。M1 阶段只支持种子；M2+ 接爬虫与本地文档。"""
    store = _open_knowledge_store()
    if seeds:
        sources = seed_sources()
        symbols = seed_symbols()
        chunks = seed_chunks()
        for src in sources:
            store.upsert_source(src)
        store.upsert_symbols(symbols)
        store.upsert_chunks(chunks)
        console.print(
            f"[green]已导入种子：{len(sources)} sources / "
            f"{len(symbols)} symbols / {len(chunks)} chunks。[/green]"
        )
    s = store.stats()
    console.print(
        f"[dim]当前知识库：{s['sources']} sources / "
        f"{s['chunks']} chunks / {s['symbols']} symbols[/dim]"
    )


@knowledge_app.command("search")
def knowledge_search(
    query: str = typer.Argument(..., help="检索关键词或问题"),
    namespace: list[str] = typer.Option(
        None, "--namespace", "-n", help="命名空间过滤，可多次"
    ),
    k: int = typer.Option(5, "--k", "-k", help="返回 top-k"),
) -> None:
    """对知识库做一次 FTS5 检索（与 chat 里玄玑用的同一个工具）。"""
    store = _open_knowledge_store()
    hits = store.search(query, namespaces=namespace or None, k=k)
    if not hits:
        console.print("[yellow]没找到相关内容。[/yellow]")
        return
    for i, h in enumerate(hits, 1):
        title = f"{i}. [{h.chunk.namespace}] {h.chunk.source_title}"
        if h.chunk.section:
            title += f" · {h.chunk.section}"
        body = h.chunk.text
        if h.matched_symbol:
            body = f"⚓ 锚点：{h.matched_symbol.name}\n\n" + body
        console.print(
            Panel(
                body,
                title=title,
                subtitle=f"[dim]score={h.score:.3f}[/dim]",
                border_style="green",
            )
        )


@knowledge_app.command("symbol")
def knowledge_symbol(
    name: str = typer.Argument(..., help="Symbol 名（全限定或片段）"),
    namespace: list[str] = typer.Option(
        None, "--namespace", "-n", help="命名空间过滤"
    ),
) -> None:
    """精准查询 Symbol 卡片。"""
    store = _open_knowledge_store()
    syms = store.lookup_symbol(name, namespaces=namespace or None)
    if not syms:
        console.print("[yellow]没找到匹配的 Symbol。[/yellow]")
        return
    for s in syms:
        body = []
        if s.signature:
            body.append(f"[cyan]{s.signature}[/cyan]")
        body.append(f"[dim]{s.kind} · {s.side}[/dim]")
        if s.summary:
            body.append("")
            body.append(s.summary)
        if s.params:
            body.append("")
            body.append("[bold]参数：[/bold]")
            for p in s.params:
                body.append(f"  • {p.get('name', '')} : {p.get('type', '')} — {p.get('desc', '')}")
        if s.returns:
            body.append("")
            body.append(f"[bold]返回：[/bold]{s.returns}")
        if s.example:
            body.append("")
            body.append("[bold]示例：[/bold]")
            body.append(s.example)
        console.print(
            Panel(
                "\n".join(body),
                title=f"[magenta]{s.name}[/magenta]  [dim]{s.namespace}[/dim]",
                border_style="magenta",
            )
        )


@knowledge_app.command("clear")
def knowledge_clear(
    namespace: str = typer.Argument(..., help="要清空的命名空间"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """清空某个命名空间下的所有内容。"""
    if not force and not typer.confirm(f"确定清空 {namespace} 命名空间？"):
        raise typer.Exit()
    store = _open_knowledge_store()
    n = store.clear_namespace(namespace)
    console.print(f"[green]已清空 {namespace}（{n} chunks）[/green]")


@knowledge_app.command("reindex-vectors")
def knowledge_reindex_vectors(
    backend: str = typer.Option(
        "lancedb",
        "--backend",
        help="目标向量后端：lancedb / inmemory（仅做演练）",
    ),
    batch: int = typer.Option(128, "--batch", help="批写入大小"),
) -> None:
    """把 SQLite 里的全部 chunks 重新 embed 写入指定向量后端。

    切换 InMemory ↔ LanceDB 后跑这个命令把历史 chunks 一次性灌进新存储。
    LanceDB 落盘到 vector_db_path()。
    """
    from xuanji.config import vector_db_path
    from xuanji.knowledge.vector import HashingEmbedder, InMemoryVectorStore, LanceDBVectorStore

    store = _open_knowledge_store()
    embedder = HashingEmbedder()
    if backend.lower() == "lancedb":
        try:
            vstore = LanceDBVectorStore(str(vector_db_path()), dim=embedder.dim)
        except ImportError:
            console.print(
                "[red]lancedb / pyarrow 未安装。先 [bold]uv sync --extra vector[/bold]。[/red]",
            )
            raise typer.Exit(2) from None
        target_path: str = str(vector_db_path())
    elif backend.lower() == "inmemory":
        vstore = InMemoryVectorStore(dim=embedder.dim)  # type: ignore[assignment]
        target_path = "(memory)"
    else:
        console.print(f"[red]未知 backend：{backend}[/red]")
        raise typer.Exit(2)

    total = 0
    pending: list[tuple[str, list[float], dict[str, Any]]] = []
    for chunk in store.iter_chunks():
        vec = embedder.embed(chunk.text)
        pending.append(
            (chunk.id, vec, {"namespace": chunk.namespace, "source_title": chunk.source_title}),
        )
        if len(pending) >= batch:
            vstore.upsert_batch(pending)
            total += len(pending)
            pending.clear()
    if pending:
        vstore.upsert_batch(pending)
        total += len(pending)
    console.print(
        f"[green]reindex 完成：{total} chunks → {backend}（{target_path}）[/green]",
    )
    if backend.lower() == "lancedb":
        console.print(
            "[dim]启动玄玑前 set XUANJI_VECTOR_BACKEND=lancedb 才会用上这份索引。[/dim]",
        )


# ---------- memory ----------


def _open_memory_store() -> SqliteMemoryStore:
    return SqliteMemoryStore(memory_db_path())


def _default_namespace() -> str:
    """memory CLI 命令的默认命名空间：当前工作目录名。"""
    return Path.cwd().name or "default"


@memory_app.command("path")
def memory_path() -> None:
    """显示记忆库 SQLite 文件路径。"""
    console.print(str(memory_db_path()))


@memory_app.command("stats")
def memory_stats() -> None:
    """显示记忆库统计：总数、按 scope/kind 分布、命名空间。"""
    store = _open_memory_store()
    s = store.stats()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("path", str(s["path"]))
    table.add_row("total", str(s["total"]))
    if s["by_scope"]:
        table.add_row("by_scope", ", ".join(f"{k}={v}" for k, v in s["by_scope"].items()))
    if s["by_kind"]:
        table.add_row("by_kind", ", ".join(f"{k}={v}" for k, v in s["by_kind"].items()))
    table.add_row("namespaces", ", ".join(s["namespaces"]) or "[dim]空[/dim]")
    console.print(table)


@memory_app.command("write")
def memory_write(
    text: str = typer.Argument(..., help="记忆主体文本"),
    kind: MemoryKind = typer.Option(
        MemoryKind.SEMANTIC, "--kind", "-k", help="记忆类型"
    ),
    scope: MemoryScope = typer.Option(
        MemoryScope.PROJECT, "--scope", "-s", help="记忆作用域"
    ),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="命名空间，默认当前目录名"
    ),
    summary: str = typer.Option(None, "--summary", help="一句话摘要"),
    importance: float = typer.Option(
        0.6, "--importance", "-i", help="重要性 0~1，默认 0.6"
    ),
    tag: list[str] = typer.Option(
        None, "--tag", "-t", help="标签，可多次"
    ),
) -> None:
    """手动写入一条记忆。"""
    store = _open_memory_store()
    ns = namespace or _default_namespace()
    m = store.write(
        Memory(
            scope=scope,
            kind=kind,
            namespace=ns,
            text=text,
            summary=summary,
            importance=importance,
            tags=tag or [],
        ),
    )
    console.print(
        f"[green]已写入 [bold]{m.id[:8]}[/bold] @ "
        f"{ns}（{scope.value}/{kind.value}，importance={importance}）[/green]"
    )


@memory_app.command("recall")
def memory_recall(
    query: str = typer.Argument(..., help="召回关键词或问题"),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="命名空间过滤，默认当前目录名"
    ),
    scope: list[MemoryScope] = typer.Option(
        None, "--scope", "-s", help="作用域过滤，可多次"
    ),
    kind: list[MemoryKind] = typer.Option(
        None, "--kind", "-k", help="类型过滤，可多次"
    ),
    k: int = typer.Option(8, "--k", help="返回 top-k"),
    cross_ns: bool = typer.Option(
        False, "--cross-ns", help="跨命名空间召回（忽略 namespace 过滤）"
    ),
) -> None:
    """对记忆库召回（与 chat 的 reflux 走同一路径）。"""
    store = _open_memory_store()
    ns = None if cross_ns else (namespace or _default_namespace())
    hits = store.recall(
        query,
        scopes=scope or None,
        kinds=kind or None,
        namespace=ns,
        k=k,
    )
    if not hits:
        console.print("[yellow]没召回任何记忆。[/yellow]")
        return
    for i, m in enumerate(hits, 1):
        title = (
            f"{i}. [{m.scope.value}/{m.kind.value}] {m.namespace}  "
            f"[dim]importance={m.importance:.2f} hits={m.hits}[/dim]"
        )
        body = m.summary or m.text
        console.print(Panel(body, title=title, border_style="cyan"))


@memory_app.command("list")
def memory_list(
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="命名空间，默认当前目录名"
    ),
    limit: int = typer.Option(50, "--limit", help="最大返回数"),
) -> None:
    """列出某命名空间下的记忆。"""
    store = _open_memory_store()
    ns = namespace or _default_namespace()
    items = store.list_by_namespace(ns, limit=limit)
    if not items:
        console.print(f"[yellow]{ns} 命名空间下还没有记忆。[/yellow]")
        return
    table = Table(title=f"怀玉阁 · {ns}")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("scope", style="magenta")
    table.add_column("kind", style="cyan")
    table.add_column("importance", justify="right")
    table.add_column("hits", justify="right")
    table.add_column("text/summary", overflow="fold")
    for m in items:
        head = m.summary or m.text
        if len(head) > 100:
            head = head[:100] + "…"
        table.add_row(
            m.id[:8],
            m.scope.value,
            m.kind.value,
            f"{m.importance:.2f}",
            str(m.hits),
            head,
        )
    console.print(table)


@memory_app.command("forget")
def memory_forget(
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="按命名空间删除"
    ),
    scope: MemoryScope = typer.Option(None, "--scope", "-s", help="按作用域删除"),
    id_: str = typer.Option(None, "--id", help="按单条 id 删除"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除记忆。namespace / scope / id 任意组合。"""
    if namespace is None and scope is None and id_ is None:
        console.print("[red]至少传一个过滤条件（--namespace / --scope / --id）[/red]")
        raise typer.Exit(1)
    if not force and not typer.confirm("确认删除？此操作不可逆"):
        raise typer.Exit()
    store = _open_memory_store()
    n = store.forget(
        ids=[id_] if id_ else None,
        namespace=namespace,
        scope=scope,
    )
    console.print(f"[green]已删除 {n} 条记忆。[/green]")


@memory_app.command("consolidate")
def memory_consolidate(
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="目标命名空间，默认当前目录名"
    ),
    max_kept: int = typer.Option(100, "--max-kept", help="episodic 保留上限"),
) -> None:
    """固化：episodic 累积过多时按重要性截断。"""
    store = _open_memory_store()
    ns = namespace or _default_namespace()
    n = store.consolidate(ns, max_kept=max_kept)
    console.print(f"[green]{ns}：固化掉 {n} 条 episodic。[/green]")


# ---------- skill ----------


@skill_app.command("list")
def skill_list(
    namespace: str = typer.Option(
        "skills", "--namespace", "-n", help="技能命名空间，默认全局 'skills'"
    ),
    limit: int = typer.Option(50, "--limit", help="最大返回数"),
) -> None:
    """列出技能。"""
    from xuanji.tools.skills import SKILLS_NAMESPACE

    store = _open_memory_store()
    items = store.list_by_namespace(
        namespace or SKILLS_NAMESPACE,
        kinds=[MemoryKind.PROCEDURAL],
        limit=limit,
    )
    if not items:
        console.print(f"[yellow]{namespace} 下还没有技能。让玄玑用 save_skill 沉淀第一条。[/yellow]")
        return
    table = Table(title=f"技能库 · {namespace}")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("summary", overflow="fold")
    table.add_column("tools", style="cyan", overflow="fold")
    table.add_column("hits", justify="right")
    table.add_column("imp", justify="right")
    for m in items:
        tools_used = m.metadata.get("tools_used") if m.metadata else []
        table.add_row(
            m.id[:8],
            m.summary or m.text[:80],
            ", ".join(tools_used) if tools_used else "-",
            str(m.hits),
            f"{m.importance:.2f}",
        )
    console.print(table)


@skill_app.command("show")
def skill_show(id_: str = typer.Argument(..., help="技能 id 前缀（≥6 位）或全名")) -> None:
    """显示一个技能的完整正文。"""
    from xuanji.tools.skills import SKILLS_NAMESPACE

    store = _open_memory_store()
    m = store.get(id_)
    if m is None:
        for cand in store.list_by_namespace(
            SKILLS_NAMESPACE, kinds=[MemoryKind.PROCEDURAL], limit=200
        ):
            if cand.id.startswith(id_):
                m = cand
                break
    if m is None or m.kind != MemoryKind.PROCEDURAL:
        console.print(f"[red]找不到技能：{id_}[/red]")
        raise typer.Exit(1)
    body_parts = [m.text]
    tools_used = m.metadata.get("tools_used") if m.metadata else []
    if tools_used:
        body_parts.append(f"\n[bold]建议工具：[/bold]{', '.join(tools_used)}")
    if m.tags:
        body_parts.append(f"[bold]标签：[/bold]{', '.join(m.tags)}")
    console.print(
        Panel(
            "\n".join(body_parts),
            title=f"[magenta]{m.summary or m.id}[/magenta]  [dim]{m.id}[/dim]",
            border_style="magenta",
        ),
    )


@skill_app.command("save")
def skill_save(
    summary: str = typer.Argument(..., help="一句话标题"),
    steps: str = typer.Argument(..., help="完整步骤正文（markdown）"),
    tag: list[str] = typer.Option(
        None, "--tag", "-t", help="标签，可多次"
    ),
    tool_used: list[str] = typer.Option(
        None, "--tool", help="建议工具名，可多次"
    ),
    namespace: str = typer.Option(
        "skills", "--namespace", "-n", help="命名空间，默认全局 'skills'"
    ),
    importance: float = typer.Option(0.7, "--importance", "-i"),
) -> None:
    """手动保存一条技能（与 save_skill 工具同路径）。"""
    store = _open_memory_store()
    saved = store.write(
        Memory(
            scope=MemoryScope.USER,
            kind=MemoryKind.PROCEDURAL,
            namespace=namespace,
            text=steps,
            summary=summary,
            importance=max(0.0, min(1.0, importance)),
            tags=list(tag or []),
            metadata={"tools_used": list(tool_used or [])},
        ),
    )
    console.print(
        f"[green]已保存技能 [bold]{saved.id[:8]}[/bold] @ {namespace}：{summary}[/green]"
    )


@skill_app.command("forget")
def skill_forget(
    id_: str = typer.Argument(..., help="技能 id（前缀或全名）"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """删除一个技能。"""
    from xuanji.tools.skills import SKILLS_NAMESPACE

    store = _open_memory_store()
    target = store.get(id_)
    if target is None:
        for cand in store.list_by_namespace(
            SKILLS_NAMESPACE, kinds=[MemoryKind.PROCEDURAL], limit=200
        ):
            if cand.id.startswith(id_):
                target = cand
                break
    if target is None or target.kind != MemoryKind.PROCEDURAL:
        console.print(f"[red]找不到技能：{id_}[/red]")
        raise typer.Exit(1)
    if not force and not typer.confirm(f"确认删除技能「{target.summary}」？"):
        raise typer.Exit()
    n = store.forget(ids=[target.id])
    console.print(f"[green]已删除 {n} 条技能。[/green]")


# ---------- tool ----------


@tool_app.command("drafts")
def tool_drafts(
    show: str = typer.Option(None, "--show", "-s", help="查看某个草案的完整 JSON")
) -> None:
    """列出 / 查看 propose_tool 提交的草案。"""
    import json

    drafts_dir = tool_drafts_dir()
    files = sorted(drafts_dir.glob("*.json"))
    if show:
        match = [f for f in files if show in f.stem]
        if not match:
            console.print(f"[red]找不到草案：{show}[/red]")
            raise typer.Exit(1)
        for f in match:
            data = json.loads(f.read_text(encoding="utf-8"))
            console.print(
                Panel(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    title=str(f),
                    border_style="cyan",
                ),
            )
        return

    if not files:
        console.print(
            f"[yellow]{drafts_dir} 还没有草案。"
            "玄玑通过 propose_tool 工具产出草案后会出现在这里。[/yellow]"
        )
        return
    table = Table(title=f"工具草案 · {drafts_dir}")
    table.add_column("文件", style="cyan", no_wrap=True)
    table.add_column("name", style="magenta")
    table.add_column("risk")
    table.add_column("description", overflow="fold")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        table.add_row(
            f.name,
            str(data.get("name", "?")),
            str(data.get("risk", "?")),
            str(data.get("description", ""))[:80],
        )
    console.print(table)
    console.print(
        "[dim]用 [bold]xuanji tool drafts --show <slug>[/bold] 看完整 JSON；"
        "review 通过后人工实现并加到 ToolRegistry。[/dim]"
    )


@tool_app.command("list")
def tool_list_cmd() -> None:
    """列出当前会话注入的所有工具（演示性，与 chat 启动时的 registry 一致）。"""
    from xuanji.server.runtime import ServerRuntime

    runtime = ServerRuntime()
    registry = runtime.build_registry()

    table = Table(title=f"已注册工具（{len(registry)} 个）")
    table.add_column("name", style="cyan")
    table.add_column("risk", style="magenta")
    table.add_column("description", overflow="fold")
    for t in registry.all():
        table.add_row(t.name, t.risk.value, (t.description or "").strip()[:80])
    console.print(table)


def _open_factory() -> Any:
    """打开 ToolFactory，复用激活 profile 与默认 model。"""
    from xuanji.tools.tool_factory import FactoryRegistry, ToolFactory

    cfg_store = ConfigStore()
    profile = cfg_store.load().get_active()
    return ToolFactory(
        drafts_dir=tool_drafts_dir(),
        staged_dir=tool_staged_dir(),
        published_dir=tool_published_dir(),
        registry=FactoryRegistry(factory_db_path()),
        profile=profile,
        model=profile.default_model if profile else None,
    )


def _render_factory_status(status: Any) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("slug", status.slug)
    table.add_row("status", status.status)
    if status.draft_path:
        table.add_row("draft", str(status.draft_path))
    if status.code_path:
        table.add_row("code", str(status.code_path))
    if status.test_path:
        table.add_row("test", str(status.test_path))
    if status.last_test_passed is not None:
        table.add_row(
            "last_test",
            "[green]passed[/green]" if status.last_test_passed else "[red]failed[/red]",
        )
    console.print(table)


@tool_app.command("generate")
def tool_generate(
    slug: str = typer.Argument(..., help="草案 slug（不带 .json 后缀）"),
) -> None:
    """跑 LLM 把 draft 变成 staged 代码 + 单测。需要激活 profile。"""
    factory = _open_factory()
    if factory.profile is None:
        console.print("[red]没有激活的 profile，先 xuanji config use <name>[/red]")
        raise typer.Exit(1)

    async def _run() -> Any:
        return await factory.generate(slug)

    try:
        status = asyncio.run(_run())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except ValueError as e:
        console.print(f"[red]生成失败：{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]✓[/green] codegen 成功（status={status.status}）")
    _render_factory_status(status)
    console.print(
        "[dim]下一步：[bold]xuanji tool test " + slug + "[/bold] 跑单测[/dim]"
    )


@tool_app.command("test")
def tool_test(
    slug: str = typer.Argument(..., help="生成过代码的 slug"),
    timeout: float = typer.Option(60.0, "--timeout", help="pytest 超时秒数"),
) -> None:
    """subprocess 跑生成的单测；通过则 status → tested。"""
    factory = _open_factory()
    try:
        status = factory.test(slug, timeout_sec=timeout)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if status.last_test_passed:
        console.print(f"[green]✓ 单测通过[/green]（status={status.status}）")
    else:
        console.print(f"[red]× 单测未通过[/red]（status={status.status}）")
    _render_factory_status(status)
    if status.last_test_output:
        console.print(
            Panel(
                status.last_test_output,
                title="pytest 输出",
                border_style="dim",
            ),
        )


@tool_app.command("publish")
def tool_publish(
    slug: str = typer.Argument(..., help="测试通过的 slug"),
) -> None:
    """把 staged 代码复制到 published；下次启动 ServerRuntime 自动加载。"""
    factory = _open_factory()
    try:
        status = factory.publish(slug)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]✓ 已发布[/green] → {status.code_path}")
    _render_factory_status(status)
    console.print("[dim]下次 chat / serve / ipc 启动时会自动加载。[/dim]")


@tool_app.command("reject")
def tool_reject(
    slug: str = typer.Argument(..., help="要拒绝的 slug"),
    reason: str = typer.Option("", "--reason", "-r", help="拒绝理由（写进状态）"),
) -> None:
    """标记草案/生成版被拒。代码不删，但 status → rejected，不再被 publish。"""
    factory = _open_factory()
    status = factory.reject(slug, reason=reason)
    console.print(f"[yellow]已拒绝：{slug}[/yellow]（status={status.status}）")
    if reason:
        console.print(f"[dim]reason: {reason}[/dim]")


@tool_app.command("status")
def tool_status(
    slug: str | None = typer.Argument(None, help="不传则列出所有；传则看单个详情"),
) -> None:
    """看工厂注册表的状态：每个 slug 走到哪一步了。"""
    from xuanji.tools.tool_factory import FactoryRegistry

    reg = FactoryRegistry(factory_db_path())
    if slug:
        st = reg.get(slug)
        if st is None:
            console.print(f"[yellow]找不到 slug={slug}[/yellow]")
            raise typer.Exit(1)
        _render_factory_status(st)
        if st.last_test_output:
            console.print(
                Panel(
                    st.last_test_output,
                    title="最近一次测试输出",
                    border_style="dim",
                ),
            )
        return

    rows = reg.all()
    if not rows:
        console.print("[dim]工厂注册表是空的——还没人 generate 过。[/dim]")
        return
    table = Table(title=f"ToolFactory 状态（{len(rows)} 条）")
    table.add_column("slug", style="cyan")
    table.add_column("status", style="magenta")
    table.add_column("test", overflow="fold")
    table.add_column("code", overflow="fold")
    for st in rows:
        test_cell = "-"
        if st.last_test_passed is True:
            test_cell = "[green]passed[/green]"
        elif st.last_test_passed is False:
            test_cell = "[red]failed[/red]"
        table.add_row(
            st.slug,
            st.status,
            test_cell,
            str(st.code_path) if st.code_path else "-",
        )
    console.print(table)


# ---------- fivem ----------


def _open_scaffold_engine() -> ScaffoldEngine:
    return ScaffoldEngine(
        user_presets_dir=scaffold_presets_dir(),
        drafts_dir=scaffold_drafts_dir(),
    )


@fivem_app.command("detect")
def fivem_detect(
    path: str = typer.Argument(".", help="目标目录，默认当前 cwd"),
) -> None:
    """识别一个目录是不是 FiveM resource，推断 framework / inventory / target。"""
    from xuanji.fivem import detect_fivem_context, summarize_for_prompt

    p = Path(path).resolve()
    if not p.exists():
        console.print(f"[red]路径不存在：{p}[/red]")
        raise typer.Exit(1)
    ctx = detect_fivem_context(p)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("path", str(ctx.project_root))
    table.add_row(
        "is_fivem_resource",
        "[green]是[/green]" if ctx.is_fivem_resource else "[dim]否[/dim]",
    )
    table.add_row("framework", f"{ctx.framework.value} ({ctx.framework_confidence:.0%})")
    table.add_row("inventory", ctx.inventory.value)
    table.add_row("target", ctx.target.value)
    if ctx.manifest:
        m = ctx.manifest
        table.add_row("name", m.name or "-")
        table.add_row("version", m.version or "-")
        deps = ", ".join(m.dependencies[:10]) or "-"
        if len(m.dependencies) > 10:
            deps += f" …（共 {len(m.dependencies)}）"
        table.add_row("dependencies", deps)
    if ctx.detected_resources:
        names = ", ".join(p.name for p in ctx.detected_resources[:10])
        table.add_row("sub_resources", names)
    console.print(table)
    if ctx.notes:
        console.print()
        for n in ctx.notes:
            console.print(f"[dim]· {n}[/dim]")
    summary = summarize_for_prompt(ctx)
    if summary:
        console.print(Panel(summary, title="塞给玄玑的 system prompt 摘要", border_style="cyan"))


@fivem_app.command("presets")
def fivem_list_presets() -> None:
    """列出所有 scaffold 预设（builtin + 用户激活的）。"""
    engine = _open_scaffold_engine()
    items = engine.list_presets()
    table = Table(title=f"Scaffold 预设（{len(items)} 套）")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("source", style="magenta")
    table.add_column("framework")
    table.add_column("label", overflow="fold")
    for it in items:
        table.add_row(it["key"], it["source"], it["framework"], it["label"])
    console.print(table)
    console.print(
        "[dim]玄玑提交的草案见 [bold]xuanji preset list[/bold]，"
        "通过后用 [bold]xuanji preset accept <key>[/bold] 激活。[/dim]"
    )


@fivem_app.command("new")
def fivem_new(
    name: str = typer.Argument(..., help="新 resource 的名字（也是目录名）"),
    preset: str = typer.Option(
        "qbox-basic", "--preset", "-p", help="使用的预设 key"
    ),
    target: str = typer.Option(
        ".", "--target", "-t", help="生成到哪个目录下，默认 cwd"
    ),
    author: str = typer.Option("", "--author"),
    description: str = typer.Option("", "--description"),
    version: str = typer.Option("1.0.0", "--version"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已存在的同名文件"),
) -> None:
    """从预设生成一个新 FiveM resource 骨架。"""
    engine = _open_scaffold_engine()
    target_dir = Path(target).resolve() / name
    try:
        result = engine.generate(
            preset,
            target_dir,
            resource_name=name,
            author=author,
            description=description,
            version=version,
            overwrite=overwrite,
        )
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    console.print(
        f"[green]已生成 {len(result.files_written)} 个文件到 {result.target_dir}[/green]"
    )
    for fp in result.files_written:
        console.print(f"  + {fp.relative_to(result.target_dir)}")
    if result.files_skipped:
        console.print(
            f"[yellow]{len(result.files_skipped)} 个文件已存在，跳过（用 --overwrite 强写）[/yellow]"
        )


@fivem_app.command("analyze")
def fivem_analyze(
    path: str = typer.Argument(".", help="resource 路径，默认当前 cwd"),
) -> None:
    """分析一个 resource，列出 exports / events / API 调用频率。"""
    from xuanji.fivem.analyzer import analyze_resource

    p = Path(path).resolve()
    if not p.exists():
        console.print(f"[red]路径不存在：{p}[/red]")
        raise typer.Exit(1)
    analysis = analyze_resource(p)

    if not analysis.context.is_fivem_resource:
        console.print("[yellow]不是 FiveM resource。说明：[/yellow]")
        for n in analysis.notes:
            console.print(f"  · {n}")
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("path", str(analysis.resource_path))
    table.add_row("framework", analysis.context.framework.value)
    table.add_row("files_scanned", str(analysis.files_scanned))
    table.add_row("exports", ", ".join(analysis.exports[:20]) or "-")
    table.add_row(
        "events_registered",
        ", ".join(analysis.events_registered[:15]) or "-",
    )
    table.add_row(
        "events_triggered",
        ", ".join(analysis.events_triggered[:15]) or "-",
    )
    table.add_row("callbacks", ", ".join(analysis.callbacks[:10]) or "-")
    console.print(table)

    if analysis.framework_api_calls:
        api_table = Table(title="高频 API 调用（top 15）")
        api_table.add_column("call", style="cyan", overflow="fold")
        api_table.add_column("count", justify="right")
        for k, v in list(analysis.framework_api_calls.items())[:15]:
            api_table.add_row(k, str(v))
        console.print(api_table)


# ---------- preset ----------


@preset_app.command("list")
def preset_list() -> None:
    """列出所有"待 review"的预设草案（玄玑通过 propose_preset 提交的）。"""
    engine = _open_scaffold_engine()
    drafts = engine.list_drafts()
    if not drafts:
        from xuanji.config import scaffold_drafts_dir

        console.print(
            f"[yellow]暂无草案。玄玑通过 [bold]propose_preset[/bold] 提交后会出现在这里："
            f"\n{scaffold_drafts_dir()}[/yellow]"
        )
        return
    table = Table(title=f"预设草案（{len(drafts)} 个待 review）")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("framework", style="magenta")
    table.add_column("inventory")
    table.add_column("files")
    table.add_column("label", overflow="fold")
    for d in drafts:
        table.add_row(
            d.key,
            d.framework.value,
            d.inventory.value,
            str(len(d.files)),
            d.label,
        )
    console.print(table)


@preset_app.command("show")
def preset_show(
    key: str = typer.Argument(..., help="预设草案 key"),
    body: bool = typer.Option(False, "--body", help="同时打印每个文件正文"),
) -> None:
    """查看一个草案详情。"""
    engine = _open_scaffold_engine()
    draft = engine.get_draft(key)
    if draft is None:
        # 也许是已激活的
        try:
            preset = engine.get(key)
        except KeyError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        console.print(
            f"[dim]({key} 已激活，不是草案)[/dim]"
        )
        draft = preset
    table = Table(show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("key", draft.key)
    table.add_row("source", draft.source)
    table.add_row("label", draft.label)
    table.add_row("description", draft.description)
    table.add_row("framework", draft.framework.value)
    table.add_row("inventory", draft.inventory.value)
    table.add_row("target", draft.target.value)
    table.add_row("files", str(len(draft.files)))
    if draft.metadata:
        for k, v in draft.metadata.items():
            table.add_row(f"metadata.{k}", str(v))
    console.print(Panel(table, title=f"preset · {key}", border_style="magenta"))

    for f in draft.files:
        if body:
            console.print(Panel(f.content, title=f.path, border_style="dim"))
        else:
            console.print(f"  · {f.path}  [dim]({len(f.content)} chars)[/dim]")


@preset_app.command("accept")
def preset_accept(
    key: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """激活一个草案——之后 xuanji fivem new --preset <key> 就能用。"""
    engine = _open_scaffold_engine()
    draft = engine.get_draft(key)
    if draft is None:
        console.print(f"[red]找不到草案：{key}[/red]")
        raise typer.Exit(1)
    if not force:
        console.print(
            Panel(
                f"准备激活：{draft.label}\n"
                f"framework={draft.framework.value} inventory={draft.inventory.value}\n"
                f"包含 {len(draft.files)} 个文件",
                title=f"review · {key}",
                border_style="yellow",
            ),
        )
        if not typer.confirm("确认激活？"):
            raise typer.Exit()
    target = engine.accept_draft(key)
    console.print(f"[green]已激活到 {target}[/green]")


@preset_app.command("reject")
def preset_reject(
    key: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """拒绝并删除一个草案。"""
    if not force and not typer.confirm(f"确定拒绝草案 {key}？"):
        raise typer.Exit()
    engine = _open_scaffold_engine()
    if engine.reject_draft(key):
        console.print(f"[green]已删除草案 {key}[/green]")
    else:
        console.print(f"[red]草案不存在：{key}[/red]")
        raise typer.Exit(1)


@preset_app.command("remove")
def preset_remove(
    key: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """删除一个已激活的用户预设（builtin 不可删）。"""
    if not force and not typer.confirm(f"确定删除已激活预设 {key}？"):
        raise typer.Exit()
    engine = _open_scaffold_engine()
    if engine.remove_user_preset(key):
        console.print(f"[green]已删除预设 {key}[/green]")
    else:
        console.print(f"[red]找不到用户预设 {key}（builtin 不可删）[/red]")
        raise typer.Exit(1)


# ---------- project（XUANJI.md 项目级记忆）----------


@project_app.command("init")
def project_init_cmd(
    overwrite: bool = typer.Option(
        False, "--overwrite", "-f", help="覆盖已有 XUANJI.md（默认禁止）"
    ),
    path: Path | None = typer.Option(
        None, "--path", "-p", help="目标项目根，不指定则用当前目录"
    ),
) -> None:
    """在工程根创建 XUANJI.md 项目记忆模板。

    会跑一次 detector 把 framework / inventory / target 填进模板，小宝再补充约定与禁区。
    """
    from xuanji.persona.project_memory import init_project_xuanji_md

    root = (path or Path.cwd()).resolve()
    try:
        target_path, created = init_project_xuanji_md(root, overwrite=overwrite)
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        console.print("[dim]加 --overwrite 强制覆盖，或先用 [bold]xuanji project show[/bold] 看现状。[/dim]")
        raise typer.Exit(1) from None
    action = "已创建" if created else "已覆盖"
    console.print(f"[green]{action}：{target_path}[/green]")
    console.print("[dim]进入该目录后再跑 [bold]xuanji chat[/bold]，玄玑会自动加载这份项目宪法。[/dim]")


@project_app.command("show")
def project_show_cmd(
    path: Path | None = typer.Option(
        None, "--path", "-p", help="目标目录，不指定则从当前目录沿目录树向上找"
    ),
) -> None:
    """打印当前项目级 + 用户级 XUANJI.md（如果有）。"""
    from xuanji.persona.project_memory import (
        load_project_xuanji_md,
        load_user_xuanji_md,
        user_xuanji_md_path,
    )

    start = (path or Path.cwd()).resolve()
    proj = load_project_xuanji_md(start)
    user_text = load_user_xuanji_md()

    if proj is None and user_text is None:
        console.print("[dim]还没有任何 XUANJI.md。先跑 [bold]xuanji project init[/bold]。[/dim]")
        raise typer.Exit()

    if user_text is not None:
        console.print(
            Panel(
                Markdown(user_text),
                title=f"[cyan]用户级 · {user_xuanji_md_path()}[/cyan]",
                title_align="left",
                border_style="cyan",
            )
        )
    if proj is not None:
        path_, text = proj
        console.print(
            Panel(
                Markdown(text),
                title=f"[magenta]项目级 · {path_}[/magenta]",
                title_align="left",
                border_style="magenta",
            )
        )


@project_app.command("path")
def project_path_cmd() -> None:
    """打印当前 cwd 沿目录树查到的 XUANJI.md 路径。"""
    from xuanji.persona.project_memory import (
        find_project_xuanji_md,
        user_xuanji_md_path,
    )

    proj = find_project_xuanji_md()
    user_path = user_xuanji_md_path()
    console.print(f"[dim]用户级：[/dim]{user_path}{' [green](存在)[/green]' if user_path.is_file() else ' [dim](未创建)[/dim]'}")
    if proj is None:
        console.print("[dim]项目级：未找到（沿目录树向上未命中 XUANJI.md）[/dim]")
    else:
        console.print(f"[magenta]项目级：[/magenta]{proj} [green](存在)[/green]")


@project_app.command("edit")
def project_edit_cmd(
    user: bool = typer.Option(
        False, "--user", "-u", help="编辑用户级 XUANJI.md 而非项目级"
    ),
) -> None:
    """用 $EDITOR 打开 XUANJI.md 编辑（项目级或用户级）。

    Windows 默认 notepad，类 Unix 用 $EDITOR 或 vi。
    """
    import os
    import subprocess

    from xuanji.persona.project_memory import (
        find_project_xuanji_md,
        init_project_xuanji_md,
        user_xuanji_md_path,
    )

    if user:
        target_path = user_xuanji_md_path()
        if not target_path.is_file():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "# 玄玑 · 用户级 XUANJI.md\n\n> 跨项目共享的偏好与规则。\n",
                encoding="utf-8",
            )
            console.print(f"[dim]已新建空白用户级模板：{target_path}[/dim]")
    else:
        proj = find_project_xuanji_md()
        if proj is None:
            console.print("[dim]当前目录没有项目级 XUANJI.md，先帮你建一个。[/dim]")
            target_path, _ = init_project_xuanji_md(Path.cwd().resolve(), overwrite=False)
        else:
            target_path = proj

    editor = os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "vi")
    console.print(f"[dim]启动 {editor} 编辑：{target_path}[/dim]")
    try:
        subprocess.run([editor, str(target_path)], check=False)
    except FileNotFoundError:
        console.print(f"[red]找不到编辑器 {editor}，把 $EDITOR 设到合适的程序后再试。[/red]")
        raise typer.Exit(1) from None


# ---------- chat ----------


# ---- Chat UI 风格表（借鉴 Claude Code）----
# ●  assistant 文本起始符（粉品红）
# ⏺  工具调用起始符（青）
# ⎿  工具子项缩进符（暗灰）
# ✱  思维链起始符（紫）
# >  用户输入提示符（粗青）
_ICON_ASSISTANT = "●"
_ICON_TOOL = "⏺"
_ICON_SUB = "⎿"
_ICON_THINK = "✱"
_ICON_USER = "›"

_SLASH_HINTS = "/help · /model · /stats · /clear · /exit"

_HELP_TEXT = """\
[bold]斜杠命令[/bold]
  [cyan]/help[/cyan]      显示本帮助
  [cyan]/model[/cyan]     显示当前模型与 profile
  [cyan]/stats[/cyan]     显示当前会话累计统计（token/上下文/轮数）
  [cyan]/think[/cyan]     切换是否显示思维链（on / off / 不带参数翻转）
  [cyan]/clear[/cyan]     清屏（保留会话上下文）
  [cyan]/reset[/cyan]     重置会话（清空历史与思维链）
  [cyan]/forget[/cyan]    删除磁盘上的会话快照（启动时不再提示恢复）
  [cyan]/exit[/cyan]      退出（也可用 Ctrl+D 或空行）

[bold]小贴士[/bold]
  • 直接输入文字开始对话，[dim]Enter[/dim] 发送
  • 工具调用会以 [cyan]⏺[/cyan] 标出，子项缩进显示
  • 思维链以 [magenta]✱[/magenta] 标出（仅 thinking 模型 · 默认关闭）
  • 每轮对话后会显示状态栏：模型 / 本轮 / 累计 / ctx / 轮数 / 模式
  • 退出后会保存最近一次对话，下次启动可恢复
"""


def _greet(
    profile_name: str,
    kind: str,
    model: str,
    assistant_alias: str,
    user_alias: str,
    tools: list[Tool],
    show_thinking: bool = False,
) -> None:
    """开场屏：紧凑式头部 + 提示行，仿 Claude Code 启动样式。"""
    title = Text()
    title.append("玄玑", style="bold magenta")
    title.append("  ", style="")
    title.append("北斗第三星·主调度运转", style="dim italic")

    body = Text()
    body.append("  profile  ", style="dim")
    body.append(f"{profile_name}", style="cyan")
    body.append("  ", style="")
    body.append(f"({kind} · {model})\n", style="dim")
    body.append("  tools    ", style="dim")
    body.append(f"{len(tools)} 个", style="green")
    if tools:
        body.append("  ", style="")
        # 只展示前 4 个工具名，多了省略
        preview = "、".join(t.name for t in tools[:4])
        if len(tools) > 4:
            preview += f"…（+{len(tools) - 4}）"
        body.append(f"[{preview}]", style="dim")
    body.append("\n  thinking ", style="dim")
    body.append("on" if show_thinking else "off", style="green" if show_thinking else "dim")
    body.append("    ", style="")
    body.append("（/think 切换）", style="dim")
    body.append("\n  hints    ", style="dim")
    body.append(_SLASH_HINTS, style="dim cyan")

    console.print()
    console.print(title)
    console.print(Text("  ─────────────────────────────────────────", style="dim"))
    console.print(body)
    console.print()
    console.print(
        Text(
            f"  {assistant_alias}在这儿，{user_alias}随时开聊。",
            style="italic dim",
        )
    )
    console.print()


class ConsoleHITL(HITLBridge):
    """CLI 的 HITL 实现：用 rich 渲染确认面板，typer.confirm 拿用户裁决。"""

    async def confirm(
        self,
        *,
        tool: Tool,
        args: dict[str, Any],
        reason: str,
    ) -> bool:
        body = Text()
        body.append(f"工具  {tool.name}", style="bold cyan")
        body.append(f"  (risk={tool.risk.value})\n", style="dim")
        body.append(f"原因  {reason}\n", style="yellow")
        if args:
            body.append("参数\n", style="dim")
            for k, v in args.items():
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "…"
                body.append(f"  {k}: ", style="cyan")
                body.append(f"{v_str}\n", style="")
        console.print(
            Panel(
                body,
                title="[bold yellow]司辰阁 · 高危操作待确认[/bold yellow]",
                title_align="left",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        return typer.confirm("放行此操作？", default=False)


def _render_tool_event(delta) -> None:  # type: ignore[no-untyped-def]
    """以缩进式列表渲染工具运行事件（Claude Code 风格）。

    样式：
      ⏺ tool_name(args)
        ⎿  ✓ 完成 (32ms)
    """
    if delta.type == "tool_run_started":
        args_pairs = []
        for k, v in (delta.args_final or {}).items():
            v_repr = repr(v)
            if len(v_repr) > 60:
                v_repr = v_repr[:60] + "…"
            args_pairs.append(f"{k}={v_repr}")
        args_str = ", ".join(args_pairs)
        line = Text()
        line.append(f"{_ICON_TOOL} ", style="bold cyan")
        line.append(f"{delta.tool_name}", style="bold")
        line.append(f"({args_str})", style="dim")
        console.print(line)
    elif delta.type == "tool_run_blocked":
        line = Text()
        line.append(f"  {_ICON_SUB}  ", style="dim")
        line.append("× 已拦截", style="bold red")
        line.append(f"  {delta.tool_run_reason}", style="red")
        console.print(line)
    elif delta.type == "tool_run_done":
        line = Text()
        line.append(f"  {_ICON_SUB}  ", style="dim")
        if delta.tool_run_ok:
            line.append("✓ 完成", style="bold green")
            line.append(f"  ({delta.tool_run_duration_ms}ms)", style="dim")
        else:
            line.append("× 失败", style="bold red")
            err = (delta.tool_run_error or "")[:120]
            line.append(f"  {err}", style="red")
        console.print(line)


def _print_assistant_marker() -> None:
    """assistant 段落起始符：● (粉品红)。"""
    line = Text()
    line.append(f"{_ICON_ASSISTANT} ", style="bold magenta")
    console.print(line, end="")


def _print_thinking_marker() -> None:
    """thinking 段落起始符：✱ Thinking…（暗紫）。"""
    line = Text()
    line.append(f"{_ICON_THINK} ", style="magenta")
    line.append("Thinking…", style="dim italic magenta")
    console.print(line)


def _format_tokens(n: int) -> str:
    """大数字带 k/M 后缀，让状态栏更紧凑。"""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


def _resolve_context_window(conductor: Any) -> int:
    """读取当前 model 的真实上下文窗口（不是压缩阈值）。

    走 provider.capabilities(model) 拿厂商声明的 context_window；任何环节失败兜底到
    compaction.max_context_tokens——保守选项，至少不会让状态栏的百分比看起来诡异。
    """
    try:
        caps = conductor.ctx.provider.capabilities(conductor.ctx.model)
        win = int(getattr(caps, "context_window", 0) or 0)
        if win > 0:
            return win
    except Exception:
        pass
    return int(conductor.compaction.max_context_tokens)


def _print_status_bar(
    *,
    provider: str,
    model: str,
    profile_name: str,
    turn_usage: Any,
    totals: dict[str, int],
    turn_count: int,
    history_len: int,
    context_window: int,
    compact_threshold: int,
    show_thinking: bool,
    persona_mode: str,
    persona_temp: str,
) -> None:
    """对话框下方的状态条。

    一行式紧凑布局，按视觉权重分组：
      [模型/profile] · [本轮 in/out/cache] · [累计] · [窗口 %] · [压缩阈值] · [N 轮] · 模式

    `context_window` 是模型真实可吃的最大上下文（如 Sonnet 4.6 = 200k，DeepSeek-V4 = 1M）；
    `compact_threshold` 是玄玑提前折叠头部的红线，默认 80k——保守得多，避免触底反弹。
    两个口径分开显示：ctx % 看离窗口上限多近；compact 提示什么时候开始压缩。
    """
    # 用 (input + cache_read 已经计费的部分) 估算上下文占用
    ctx_used = turn_usage.input_tokens + turn_usage.cache_read_tokens
    win_pct = min(100, int(ctx_used * 100 / context_window)) if context_window else 0
    win_color = "green" if win_pct < 50 else "yellow" if win_pct < 85 else "red"
    compact_pct = (
        min(100, int(ctx_used * 100 / compact_threshold)) if compact_threshold else 0
    )
    compact_color = (
        "green" if compact_pct < 60 else "yellow" if compact_pct < 90 else "red"
    )

    bar = Text()
    bar.append("  ")
    # 模型
    bar.append(f"{model}", style="cyan")
    bar.append(f"@{provider}", style="dim cyan")
    bar.append("  ·  ", style="dim")
    # 本轮 token
    bar.append("本轮 ", style="dim")
    bar.append(f"in {_format_tokens(turn_usage.input_tokens)}", style="green")
    bar.append("  ", style="dim")
    bar.append(f"out {_format_tokens(turn_usage.output_tokens)}", style="magenta")
    if turn_usage.cache_read_tokens or turn_usage.cache_write_tokens:
        bar.append("  ", style="dim")
        bar.append(
            f"cache {_format_tokens(turn_usage.cache_read_tokens)}↓",
            style="cyan",
        )
        if turn_usage.cache_write_tokens:
            bar.append(
                f"/{_format_tokens(turn_usage.cache_write_tokens)}↑",
                style="dim cyan",
            )
    bar.append("  ·  ", style="dim")
    # 累计
    total_all = totals["input"] + totals["output"]
    bar.append("累计 ", style="dim")
    bar.append(f"{_format_tokens(total_all)}", style="bold")
    bar.append(
        f" (in {_format_tokens(totals['input'])} / out {_format_tokens(totals['output'])}",
        style="dim",
    )
    if totals["cache_read"]:
        bar.append(
            f" / cache {_format_tokens(totals['cache_read'])}",
            style="dim",
        )
    bar.append(")", style="dim")
    bar.append("  ·  ", style="dim")
    # 窗口占用 = 离模型真实上下文上限多远
    bar.append("ctx ", style="dim")
    bar.append(f"{win_pct}%", style=win_color)
    bar.append(
        f" ({_format_tokens(ctx_used)}/{_format_tokens(context_window)})",
        style="dim",
    )
    bar.append("  ·  ", style="dim")
    # 压缩阈值进度 = 离玄玑主动压缩头部的红线多远
    bar.append("compact ", style="dim")
    bar.append(f"{compact_pct}%", style=compact_color)
    bar.append(f"@{_format_tokens(compact_threshold)}", style="dim")
    bar.append("  ·  ", style="dim")
    # 会话进度
    bar.append(f"{turn_count} 轮", style="dim")
    bar.append("  ·  ", style="dim")
    bar.append(f"{history_len} msg", style="dim")
    bar.append("  ·  ", style="dim")
    # 模式与人设
    bar.append(f"{persona_mode}/{persona_temp}", style="dim")
    bar.append("  ·  ", style="dim")
    # 思维链开关
    bar.append(
        "think on" if show_thinking else "think off",
        style="green" if show_thinking else "dim",
    )
    bar.append("  ·  ", style="dim")
    bar.append(profile_name, style="dim")

    console.print(bar)


def _handle_slash_command(
    cmd: str,
    conductor: Any,
    state: dict[str, Any],
) -> bool | None:
    """处理 /xxx 内置命令。返回值约定：
    - True：处理完毕，继续 loop
    - None：不是斜杠命令，按普通输入处理
    - False：要求退出 loop

    state 是 chat loop 持有的可变状态字典（如 show_thinking 开关），
    斜杠命令会就地修改它，chat loop 下一轮读到新值。
    """
    if not cmd.startswith("/"):
        return None
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    if name in ("/exit", "/quit", "/q"):
        return False
    if name == "/help":
        console.print()
        console.print(_HELP_TEXT)
        console.print()
        return True
    if name == "/clear":
        # 清屏但不清历史
        console.clear()
        return True
    if name == "/reset":
        # 清空 conductor.ctx.history（保留 system 状态由下一次 send 重建）
        conductor.ctx.history.clear()
        console.print("[dim]会话已重置。[/dim]")
        return True
    if name == "/model":
        line = Text()
        line.append("  当前模型  ", style="dim")
        line.append(f"{conductor.ctx.model}", style="cyan")
        line.append("  provider  ", style="dim")
        line.append(f"{conductor.ctx.provider.name}", style="cyan")
        console.print()
        console.print(line)
        console.print()
        return True
    if name == "/stats":
        # 拉一份"凑出来的"零本轮 usage（cumulative-only 视图）
        from xuanji.llm.providers.base import Usage as _Usage

        zero = _Usage()
        totals = state.get("totals") or {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
        }
        console.print()
        _print_status_bar(
            provider=conductor.ctx.provider.name,
            model=conductor.ctx.model,
            profile_name=state.get("profile_name", "?"),
            turn_usage=zero,
            totals=totals,
            turn_count=state.get("turn_count", 0),
            history_len=len(conductor.ctx.history),
            context_window=_resolve_context_window(conductor),
            compact_threshold=conductor.compaction.max_context_tokens,
            show_thinking=state.get("show_thinking", False),
            persona_mode=conductor.ctx.mode.value,
            persona_temp=conductor.ctx.temperature.value,
        )
        console.print()
        return True
    if name == "/think":
        # /think           翻转
        # /think on/off    显式设置
        if arg in ("on", "true", "1", "yes"):
            new_val = True
        elif arg in ("off", "false", "0", "no"):
            new_val = False
        elif arg == "":
            new_val = not state.get("show_thinking", False)
        else:
            console.print(f"[red]/think 参数无效：{arg}[/red]   用法：/think [on|off]")
            return True
        state["show_thinking"] = new_val
        # 落盘到 chat_ui.show_thinking，下次启动也生效
        try:
            store = ConfigStore()
            cfg = store.load()
            cfg.chat_ui.show_thinking = new_val
            store.save(cfg)
        except Exception as e:
            console.print(f"[dim yellow]（保存失败：{e}）[/dim yellow]")
        status = "[green]开[/green]" if new_val else "[dim]关[/dim]"
        console.print(f"  思维链显示  {status}")
        return True
    if name == "/forget":
        removed = clear_last_session()
        if removed:
            console.print("[dim]已清除磁盘上的会话快照。[/dim]")
        else:
            console.print("[dim]没有可清除的快照。[/dim]")
        return True
    console.print(f"[red]未知命令：{name}[/red]   输入 [cyan]/help[/cyan] 看帮助。")
    return True


async def _chat_loop() -> None:
    from xuanji.server.runtime import ServerRuntime

    cfg = ConfigStore().load()
    profile = cfg.get_active()
    if not profile:
        console.print(
            "[red]还没有激活的 profile。先 [bold]xuanji config add[/bold] 加一个。[/red]"
        )
        raise typer.Exit(1)

    runtime = ServerRuntime(cfg_store=ConfigStore())
    registry = runtime.build_registry()

    profile_name = cfg.active_profile or "?"
    conductor = runtime.make_conductor(
        profile=profile,
        hitl_bridge=ConsoleHITL(),
        registry=registry,
    )

    # 询问是否恢复上次会话（profile/model 一致时才提示，避免 thinking 块灌错端点）
    snap = load_last_session()
    if snap is not None and snap.history:
        if (
            snap.profile_name == profile_name
            and snap.provider == conductor.ctx.provider.name
            and snap.model == conductor.ctx.model
        ):
            line = Text()
            line.append("  上次对话  ", style="dim")
            line.append(f"{format_age(snap.age_seconds)}", style="cyan")
            line.append("  ·  ", style="dim")
            line.append(f"{snap.turn_count} 轮", style="green")
            line.append("  ·  ", style="dim")
            line.append(f"~{snap.estimated_tokens} tokens", style="dim")
            console.print()
            console.print(line)
            if typer.confirm("  恢复上次的对话？", default=True):
                conductor.ctx.history = list(snap.history)
                console.print("[dim]  已恢复历史。/reset 可清空。[/dim]")
            else:
                console.print("[dim]  好，从头开始。[/dim]")
        else:
            line = Text()
            line.append("  ", style="")
            line.append("发现快照", style="dim yellow")
            line.append(
                f"，但 profile/model 不匹配（旧={snap.profile_name}/{snap.model}），跳过恢复。",
                style="dim",
            )
            console.print()
            console.print(line)

    _greet(
        profile_name,
        profile.kind.value,
        conductor.ctx.model,
        cfg.assistant_alias,
        cfg.user_alias,
        registry.all(),
        show_thinking=cfg.chat_ui.show_thinking,
    )

    # chat loop 的可变状态（slash 命令会改写它）
    state: dict[str, Any] = {
        "show_thinking": cfg.chat_ui.show_thinking,
        "turn_count": 0,
        "totals": {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        },
        "profile_name": profile_name,
        "last_turn_usage": None,
    }

    def _render_pinned_status() -> None:
        """把状态栏粘到当前光标位置——用户输入框正上方。

        没有打过模型时（last_turn_usage=None），仅显示模型 / 累计 / ctx 的零值版，
        小宝抬眼就能确认 profile/model/ctx 还是不是预期的。
        """
        from xuanji.llm.providers.base import Usage as _Usage

        u = state.get("last_turn_usage") or _Usage()
        _print_status_bar(
            provider=conductor.ctx.provider.name,
            model=conductor.ctx.model,
            profile_name=state["profile_name"],
            turn_usage=u,
            totals=state["totals"],
            turn_count=state["turn_count"],
            history_len=len(conductor.ctx.history),
            context_window=_resolve_context_window(conductor),
            compact_threshold=conductor.compaction.max_context_tokens,
            show_thinking=state["show_thinking"],
            persona_mode=conductor.ctx.mode.value,
            persona_temp=conductor.ctx.temperature.value,
        )

    while True:
        # 每轮提示输入前都把状态栏贴一次到输入框上方
        _render_pinned_status()
        try:
            user_input = console.input(
                f"[bold cyan]{_ICON_USER}[/bold cyan] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]玄玑先去忙了。[/dim]")
            return
        if not user_input:
            console.print("[dim]玄玑先去忙了。[/dim]")
            return

        slash = _handle_slash_command(user_input, conductor, state)
        if slash is False:
            console.print("[dim]玄玑先去忙了。[/dim]")
            return
        if slash is True:
            continue

        # 输出区状态机
        accumulated = ""        # 当前 assistant 文本段累积
        text_open = False       # 当前是否有打开的文本段
        thinking_open = False   # 当前是否处于 thinking 段
        live: Live | None = None

        def _close_live() -> None:
            nonlocal live
            if live is not None:
                live.__exit__(None, None, None)
                live = None

        try:
            console.print()  # assistant 段开始前空一行
            async for delta in conductor.send(user_input):
                if delta.type == "thinking_start":
                    if not state["show_thinking"]:
                        continue
                    _close_live()
                    if not thinking_open:
                        _print_thinking_marker()
                        thinking_open = True
                elif delta.type == "thinking_delta" and delta.text:
                    if not state["show_thinking"]:
                        continue
                    # 思维链以缩进 + 暗灰展示，按 chunk 直接打印
                    console.print(
                        Text(delta.text, style="dim italic"),
                        end="",
                        soft_wrap=True,
                    )
                elif delta.type == "thinking_end":
                    if not state["show_thinking"]:
                        continue
                    if thinking_open:
                        console.print()  # 思维链结束换行
                        thinking_open = False
                elif delta.type == "text_delta" and delta.text:
                    if not text_open:
                        # 文本段刚开始：打 ● 标记，再开 Live 渲染 markdown
                        _print_assistant_marker()
                        text_open = True
                        live = Live(
                            Markdown(""),
                            console=console,
                            refresh_per_second=12,
                            vertical_overflow="visible",
                        )
                        live.__enter__()
                    accumulated += delta.text
                    if live is not None:
                        live.update(Markdown(accumulated))
                elif delta.type in (
                    "tool_run_started",
                    "tool_run_blocked",
                    "tool_run_done",
                ):
                    # 工具事件先关 Live + 复位文本段，避免渲染撕裂
                    _close_live()
                    if text_open:
                        accumulated = ""
                        text_open = False
                    _render_tool_event(delta)
                elif delta.type == "message_done" and delta.usage:
                    _close_live()
                    if text_open:
                        text_open = False
                    u = delta.usage
                    state["turn_count"] += 1
                    totals = state["totals"]
                    totals["input"] += u.input_tokens
                    totals["output"] += u.output_tokens
                    totals["cache_read"] += u.cache_read_tokens
                    totals["cache_write"] += u.cache_write_tokens
                    state["last_turn_usage"] = u
                    console.print()
                    # 落盘最新历史，下次启动可恢复（失败不打断对话）
                    with contextlib.suppress(Exception):
                        save_last_session(
                            ChatSessionSnapshot(
                                profile_name=profile_name,
                                provider=conductor.ctx.provider.name,
                                model=conductor.ctx.model,
                                history=[
                                    Message.model_validate(m.model_dump())
                                    for m in conductor.ctx.history
                                ],
                            )
                        )
        except Exception as e:
            _close_live()
            console.print(f"\n[red]调用失败：{type(e).__name__}: {e}[/red]\n")
        finally:
            _close_live()


@app.command()
def chat() -> None:
    """与玄玑流式对话（CHAT 模式）。"""
    asyncio.run(_chat_loop())


def main() -> None:
    app()


# ---------- serve ----------


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="监听地址"),
    port: int = typer.Option(8765, "--port", "-p", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="代码改动自动重载（开发用）"),
) -> None:
    """启动 FastAPI 服务（HTTP + WebSocket）。

    打开 http://127.0.0.1:8765 即可在浏览器里跟玄玑聊。
    """
    import uvicorn

    from xuanji.server.app import create_app

    cfg = ConfigStore().load()
    if cfg.get_active() is None:
        console.print(
            "[red]还没有激活的 profile。先 [bold]xuanji config add[/bold] 加一个再启动服务。[/red]"
        )
        raise typer.Exit(1)

    if reload:
        # reload 模式只能传 import string
        uvicorn.run(
            "xuanji.server.app:create_app",
            host=host,
            port=port,
            factory=True,
            reload=True,
        )
    else:
        app_instance = create_app()
        uvicorn.run(app_instance, host=host, port=port)


# ---------- skill-file（markdown + frontmatter，与 Claude Code / Codex 互通）----------


@skill_file_app.command("list")
def skill_file_list() -> None:
    """列出 skills 目录下所有 markdown skill。"""
    from xuanji.config import skills_dir
    from xuanji.skills import SkillsLoader

    loader = SkillsLoader(skills_dir())
    skills = loader.all()
    errors = loader.errors()
    if not skills and not errors:
        console.print(
            f"[yellow]{skills_dir()} 下还没有 skill 文件。"
            "可以从 Claude Code / Codex 拷过来，或手动写一个 .md。[/yellow]",
        )
        return
    table = Table(title=f"Skills · {skills_dir()}")
    table.add_column("name", style="cyan")
    table.add_column("description", overflow="fold")
    table.add_column("triggers", style="green", overflow="fold")
    table.add_column("xuanji.mode", style="magenta")
    for s in skills:
        table.add_row(
            s.name,
            s.frontmatter.description,
            ", ".join(s.frontmatter.triggers) or "-",
            s.frontmatter.xuanji.mode or "-",
        )
    console.print(table)
    if errors:
        console.print("[red]解析失败：[/red]")
        for path, msg in errors.items():
            console.print(f"  - {path}: {msg}")


@skill_file_app.command("show")
def skill_file_show(name: str = typer.Argument(..., help="skill 名（frontmatter.name）")) -> None:
    """显示一个 skill 的 frontmatter 与正文。"""
    from xuanji.config import skills_dir
    from xuanji.skills import SkillsLoader

    loader = SkillsLoader(skills_dir())
    skill = loader.get(name)
    if skill is None:
        console.print(f"[red]找不到 skill：{name}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold cyan]{skill.name}[/bold cyan] · {skill.path}")
    console.print(f"[dim]{skill.frontmatter.description}[/dim]")
    if skill.frontmatter.triggers:
        console.print(f"triggers: {', '.join(skill.frontmatter.triggers)}")
    if skill.frontmatter.allowed_tools:
        console.print(f"allowed_tools: {', '.join(skill.frontmatter.allowed_tools)}")
    xj = skill.frontmatter.xuanji
    if xj.mode or xj.role_hint or xj.risk_floor or xj.temperature:
        console.print(
            f"xuanji: mode={xj.mode} temperature={xj.temperature} "
            f"role_hint={xj.role_hint} risk_floor={xj.risk_floor}",
        )
    console.print()
    console.print(skill.body)


@skill_file_app.command("path")
def skill_file_path() -> None:
    """打印 skills 目录路径。"""
    from xuanji.config import skills_dir
    console.print(str(skills_dir()))


@skill_file_app.command("install-samples")
def skill_file_install_samples(
    force: bool = typer.Option(
        False, "--force", "-f", help="覆盖同名文件（默认遇到同名跳过）",
    ),
) -> None:
    """把内置示范 skill 拷到 skills_dir()，立即可用。

    内置示范：
    - qbox-add-useable-item.md
    - ox-lib-callback.md
    - fxmanifest-audit.md
    """
    import shutil

    from xuanji.config import skills_dir
    from xuanji.resources import list_sample_skills

    target = skills_dir()
    samples = list_sample_skills()
    if not samples:
        console.print("[yellow]没找到内置示范 skill（resources/skills 为空）[/yellow]")
        return
    installed: list[str] = []
    skipped: list[str] = []
    for src in samples:
        dst = target / src.name
        if dst.exists() and not force:
            skipped.append(src.name)
            continue
        shutil.copy2(src, dst)
        installed.append(src.name)
    for name in installed:
        console.print(f"[green]✔[/green] {name}")
    for name in skipped:
        console.print(f"[dim]·[/dim] {name}（已存在，跳过；--force 覆盖）")
    console.print(f"[bold]目标目录：[/bold]{target}")


# ---------- hook（YAML + Pre/PostToolUse / UserPromptSubmit / Notification）----------


_HOOK_EVENT_NAMES = ["PreToolUse", "PostToolUse", "UserPromptSubmit", "Notification"]


def _resolve_hook_event(name: str) -> Any:
    from xuanji.hooks import HookEvent
    for ev in HookEvent:
        if ev.value.lower() == name.lower():
            return ev
    raise typer.BadParameter(
        f"未知事件 {name!r}，可选：{', '.join(_HOOK_EVENT_NAMES)}",
    )


@hook_app.command("path")
def hook_path() -> None:
    """打印 hooks 目录路径。"""
    from xuanji.config import hooks_dir
    console.print(str(hooks_dir()))


@hook_app.command("install-samples")
def hook_install_samples(
    force: bool = typer.Option(
        False, "--force", "-f", help="覆盖同名文件（默认遇到同名跳过）",
    ),
) -> None:
    """把内置示范 hook YAML 拷到 hooks_dir()，立即可用。

    内置：
    - PreToolUse.yaml（黑名单 / 敏感写入预警）
    - PostToolUse.yaml（命令日志）
    - UserPromptSubmit.yaml（部署/生产 hint）
    """
    import shutil

    from xuanji.config import hooks_dir
    from xuanji.resources import list_sample_hooks

    target = hooks_dir()
    samples = list_sample_hooks()
    if not samples:
        console.print("[yellow]没找到内置示范 hook（resources/hooks 为空）[/yellow]")
        return
    installed: list[str] = []
    skipped: list[str] = []
    for src in samples:
        dst = target / src.name
        if dst.exists() and not force:
            skipped.append(src.name)
            continue
        shutil.copy2(src, dst)
        installed.append(src.name)
    for name in installed:
        console.print(f"[green]✔[/green] {name}")
    for name in skipped:
        console.print(f"[dim]·[/dim] {name}（已存在，跳过；--force 覆盖）")
    console.print(f"[bold]目标目录：[/bold]{target}")


@hook_app.command("list")
def hook_list() -> None:
    """列出全部事件下已注册的 hook spec。"""
    from xuanji.config import hooks_dir
    from xuanji.hooks import HookEvent, HooksRegistry

    reg = HooksRegistry(hooks_dir())
    table = Table(title=f"Hooks · {hooks_dir()}")
    table.add_column("event", style="cyan")
    table.add_column("matcher", style="green")
    table.add_column("command", overflow="fold")
    table.add_column("timeout", style="magenta")
    total = 0
    for ev in HookEvent:
        for spec in reg.for_event(ev):
            table.add_row(ev.value, spec.matcher, spec.command, f"{spec.timeout}s")
            total += 1
    if total == 0:
        console.print(
            f"[yellow]{hooks_dir()} 下还没有 hook 文件。"
            "在 PreToolUse.yaml / PostToolUse.yaml / UserPromptSubmit.yaml / Notification.yaml 下写 hooks。[/yellow]",
        )
        return
    console.print(table)


@hook_app.command("explain")
def hook_explain(
    event: str = typer.Option(
        ...,
        "--event",
        "-e",
        help="事件名：PreToolUse / PostToolUse / UserPromptSubmit / Notification",
    ),
    tool: str | None = typer.Option(
        None, "--tool", "-t", help="假设触发的 tool 名（PreToolUse / PostToolUse 用）",
    ),
    prompt: str | None = typer.Option(
        None, "--prompt", "-p", help="假设的用户输入（UserPromptSubmit 用）",
    ),
) -> None:
    """dry-run：当前事件 + 输入会触发哪些 hook，每条解释为什么命中。

    不启动子进程，纯静态。用来排查 matcher 是否写对、拒绝是否会真起作用。

    例：xuanji hook explain --event PreToolUse --tool run_shell
    """
    from xuanji.config import hooks_dir
    from xuanji.hooks import HooksRegistry, explain_hooks

    ev = _resolve_hook_event(event)
    reg = HooksRegistry(hooks_dir())
    explanations = explain_hooks(reg, ev, tool_name=tool, prompt=prompt)
    if not explanations:
        console.print(
            f"[yellow]{ev.value} 下没有任何 hook 注册。文件：{hooks_dir() / (ev.value + '.yaml')}[/yellow]",
        )
        return
    table = Table(title=f"Hook explain · {ev.value}")
    table.add_column("matcher", style="green")
    table.add_column("命中?", justify="center")
    table.add_column("拒绝有效?", justify="center")
    table.add_column("原因", overflow="fold")
    table.add_column("command", overflow="fold")
    for ex in explanations:
        hit_cell = "[green]√[/green]" if ex.matched else "[dim]·[/dim]"
        deny_cell = "[red]√[/red]" if ex.can_deny else "[dim]N/A[/dim]"
        table.add_row(ex.spec.matcher, hit_cell, deny_cell, ex.reason, ex.spec.command)
    console.print(table)


@hook_app.command("test")
def hook_test(
    event: str = typer.Option(..., "--event", "-e", help="事件名"),
    tool: str | None = typer.Option(None, "--tool", "-t", help="假设触发的 tool 名"),
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="假设的用户输入"),
    payload_json: str = typer.Option(
        "{}", "--payload", help="喂给 hook stdin 的 JSON payload",
    ),
) -> None:
    """**真的执行**命中的 hook，看 stdout/stderr/exit_code/decision。

    与 explain 不同：会启动子进程跑 hook 命令。生产 deny 逻辑调试用。
    """
    import asyncio
    import json

    from xuanji.config import hooks_dir
    from xuanji.hooks import HooksRegistry, run_matching_hooks

    ev = _resolve_hook_event(event)
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"--payload 不是合法 JSON：{e}") from e
    reg = HooksRegistry(hooks_dir())
    results = asyncio.run(
        run_matching_hooks(
            reg, ev, payload, cwd=Path.cwd(), tool_name=tool, prompt=prompt,
        ),
    )
    if not results:
        console.print(f"[yellow]没有 hook 命中 {ev.value}。[/yellow]")
        return
    for r in results:
        head = f"[bold]matcher={r.spec.matcher!r}[/bold] exit={r.exit_code}"
        if r.error:
            head += f" [red]error={r.error}[/red]"
        if r.denied:
            head += " [red]DENIED[/red]"
        console.print(head)
        if r.stdout:
            console.print(f"[dim]stdout:[/dim] {r.stdout.strip()}")
        if r.stderr:
            console.print(f"[dim]stderr:[/dim] {r.stderr.strip()}")
        if r.reason:
            console.print(f"[dim]reason:[/dim] {r.reason}")
        console.print()


# ---------- ipc ----------


@app.command()
def ipc() -> None:
    """启动 stdio JSON-RPC 后端（VS Code 插件 / Tauri 桌面端调用）。

    协议：LSP 风格 Content-Length 分帧 + JSON-RPC 2.0。
    日志走 stderr，避免污染 stdout 协议流。
    服务端可主动推流（chat.* / ensemble.* 通知）。
    """
    from xuanji.ipc.dispatcher import build_full_dispatcher
    from xuanji.ipc.notifier import StdoutNotifier
    from xuanji.ipc.server import run_stdio_server
    from xuanji.server.runtime import ServerRuntime

    runtime = ServerRuntime()
    notifier = StdoutNotifier()

    def _factory(_: object) -> Any:
        return build_full_dispatcher(runtime=runtime, notifier=notifier)

    asyncio.run(run_stdio_server(_factory, notifier=notifier))


# ---------- mcp-serve ----------


@app.command(name="mcp-serve")
def mcp_serve(
    project_root: Path | None = typer.Option(
        None, "--project-root", "-r",
        help="项目根目录，默认 cwd",
        exists=True, file_okay=False, dir_okay=True,
    ),
) -> None:
    """以 MCP Server 身份暴露玄玑工具到 stdio。

    协议：JSON-RPC 2.0 over stdio NDJSON（与 Claude Code / Codex 互通）。
    日志走 stderr，stdout 留给协议流。

    用法（在 CC 端配 mcp_servers）：
        {"command": "uv", "args": ["run", "xuanji", "mcp-serve"]}
    """
    import io
    import sys as _sys

    from xuanji.mcp.server import McpServer
    from xuanji.server.runtime import ServerRuntime

    # 强制 UTF-8 stdio，避免 Windows GBK 把中文打成 �
    if isinstance(_sys.stdout, io.TextIOWrapper):
        _sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(_sys.stderr, io.TextIOWrapper):
        _sys.stderr.reconfigure(encoding="utf-8")
    if isinstance(_sys.stdin, io.TextIOWrapper):
        _sys.stdin.reconfigure(encoding="utf-8")

    runtime = ServerRuntime(project_root=project_root)
    registry = runtime.build_registry()
    server = McpServer(registry, project_root=runtime.project_root)
    asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
