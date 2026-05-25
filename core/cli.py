"""玄玑 CLI。

命令族：
- xuanji info           当前激活配置概览
- xuanji config path    显示配置文件路径
- xuanji config list    列出所有 profile
- xuanji config show    查看某个 profile 详情（密钥脱敏）
- xuanji config add     新增 profile（交互式）
- xuanji config use     切换激活 profile
- xuanji config remove  删除 profile
- xuanji config test    实际请求一条 hello 验证 profile 可用
- xuanji chat           进入流式对话（CHAT 模式）
"""

from __future__ import annotations

import asyncio
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

from core.capability.registry import ToolRegistry
from core.capability.tool import Tool
from core.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
    config_file_path,
    knowledge_db_path,
    memory_db_path,
    tool_drafts_dir,
)
from core.config.profiles import DEFAULT_MODELS, OFFICIAL_BASE_URLS
from core.gate.bridge import HITLBridge
from core.knowledge import SqliteKnowledgeStore
from core.knowledge.sources import seed_chunks, seed_sources, seed_symbols
from core.llm.providers.factory import build_provider
from core.memory import Memory, MemoryKind, MemoryScope, SqliteMemoryStore
from core.neural import Conductor
from core.persona import PersonaMode
from core.tools import (
    builtin_tools,
    ingest_tools_offline,
    knowledge_tools,
    memory_tools,
    meta_tools,
    skill_tools,
    tool_factory_tools,
)
from core.tools.ingest_url import IngestUrlTool

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
tool_app = typer.Typer(
    help="工具：列出已注册工具 / 查看 propose_tool 草案",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")
app.add_typer(tool_app, name="tool")

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
    from core.llm.providers.base import Message

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
    from core.tools.skills import SKILLS_NAMESPACE

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
    from core.tools.skills import SKILLS_NAMESPACE

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
    from core.tools.skills import SKILLS_NAMESPACE

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
    # 复刻 chat loop 里同一套注入顺序，仅展示
    knowledge = SqliteKnowledgeStore(knowledge_db_path())
    memory = SqliteMemoryStore(memory_db_path())
    project_namespace = _default_namespace()
    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    registry.register_all(knowledge_tools(knowledge))
    registry.register_all(ingest_tools_offline(knowledge))
    registry.register(IngestUrlTool(knowledge))
    registry.register_all(memory_tools(memory, project_namespace))
    registry.register_all(skill_tools(memory))
    registry.register_all(tool_factory_tools(tool_drafts_dir()))
    registry.register_all(meta_tools(registry, memory))

    table = Table(title=f"已注册工具（{len(registry)} 个）")
    table.add_column("name", style="cyan")
    table.add_column("risk", style="magenta")
    table.add_column("description", overflow="fold")
    for t in registry.all():
        table.add_row(t.name, t.risk.value, (t.description or "").strip()[:80])
    console.print(table)


# ---------- chat ----------


def _greet(profile_name: str, kind: str, model: str, assistant_alias: str, user_alias: str, tools: list[Tool]) -> None:
    text = Text()
    text.append("玄玑 · ", style="bold magenta")
    text.append("北斗第三星，主调度运转\n", style="dim")
    text.append(f"当前 profile：{profile_name}（{kind} · {model}）\n", style="cyan")
    if tools:
        names = "、".join(t.name for t in tools)
        text.append(f"工具：{names}\n", style="green")
    text.append(
        f"{assistant_alias}在这儿，{user_alias}有什么想聊的？输入空行退出。\n",
        style="italic",
    )
    console.print(Panel(text, border_style="magenta"))


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
        body.append("司辰阁拦截 · 高危操作待确认\n\n", style="bold yellow")
        body.append(f"工具：{tool.name}（risk={tool.risk.value}）\n", style="cyan")
        body.append(f"原因：{reason}\n", style="yellow")
        body.append("\n参数：\n", style="dim")
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > 200:
                v_str = v_str[:200] + "…"
            body.append(f"  {k}: ", style="cyan")
            body.append(f"{v_str}\n")
        console.print(Panel(body, border_style="yellow", title="[yellow]司辰阁[/yellow]"))
        return typer.confirm("放行此操作？", default=False)


def _render_tool_event(delta) -> None:  # type: ignore[no-untyped-def]
    """在流式输出中以独立 panel 渲染工具运行事件。"""
    if delta.type == "tool_run_started":
        args_str = ", ".join(f"{k}={v!r}" for k, v in (delta.args_final or {}).items())
        console.print(
            f"[dim cyan]→ 调用 {delta.tool_name}({args_str})[/dim cyan]"
        )
    elif delta.type == "tool_run_blocked":
        console.print(f"[red]× 已拦截：{delta.tool_run_reason}[/red]")
    elif delta.type == "tool_run_done":
        if delta.tool_run_ok:
            console.print(
                f"[green]✓ {delta.tool_name} 完成[/green] "
                f"[dim]({delta.tool_run_duration_ms}ms)[/dim]"
            )
        else:
            console.print(
                f"[red]× {delta.tool_name} 失败：{delta.tool_run_error}[/red]"
            )


async def _chat_loop() -> None:
    cfg = ConfigStore().load()
    profile = cfg.get_active()
    if not profile:
        console.print(
            "[red]还没有激活的 profile。先 [bold]xuanji config add[/bold] 加一个。[/red]"
        )
        raise typer.Exit(1)

    registry = ToolRegistry()
    registry.register_all(builtin_tools())
    # 知识库工具：稷下学宫接通
    knowledge = SqliteKnowledgeStore(knowledge_db_path())
    registry.register_all(knowledge_tools(knowledge))
    # 怀玉阁：记忆库挂上 Conductor，开启 reflux
    memory = SqliteMemoryStore(memory_db_path())

    # 自演化工具集：知识 ingestion / 记忆主动读写 / 技能管理 / 工具提案
    project_namespace = Path.cwd().resolve().name or "default"
    registry.register_all(ingest_tools_offline(knowledge))
    registry.register(IngestUrlTool(knowledge))  # NET 风险 → 司辰阁 HITL
    registry.register_all(memory_tools(memory, project_namespace))
    registry.register_all(skill_tools(memory))
    registry.register_all(tool_factory_tools(tool_drafts_dir()))
    # 元工具最后注册——它们依赖 registry 已经满
    registry.register_all(meta_tools(registry, memory))

    profile_name = cfg.active_profile or "?"
    conductor = Conductor(
        profile=profile,
        mode=PersonaMode.CHAT,
        temperature=cfg.persona_temperature,
        assistant_alias=cfg.assistant_alias,
        user_alias=cfg.user_alias,
        registry=registry,
        hitl_bridge=ConsoleHITL(),
        memory=memory,
    )
    _greet(
        profile_name,
        profile.kind.value,
        conductor.ctx.model,
        cfg.assistant_alias,
        cfg.user_alias,
        registry.all(),
    )

    while True:
        try:
            user_input = console.input("[bold cyan]用户 ▸[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]玄玑先去忙了。[/dim]")
            return
        if not user_input:
            console.print("[dim]玄玑先去忙了。[/dim]")
            return

        accumulated = ""
        live: Live | None = None

        def _open_live() -> Live:
            return Live(
                Panel(
                    Text("……", style="dim"),
                    title="[magenta]玄玑[/magenta]",
                    border_style="magenta",
                ),
                console=console,
                refresh_per_second=12,
            )

        try:
            live = _open_live()
            live.__enter__()
            async for delta in conductor.send(user_input):
                if delta.type == "text_delta" and delta.text:
                    accumulated += delta.text
                    live.update(
                        Panel(
                            Markdown(accumulated),
                            title="[magenta]玄玑[/magenta]",
                            border_style="magenta",
                        ),
                    )
                elif delta.type in (
                    "tool_run_started",
                    "tool_run_blocked",
                    "tool_run_done",
                ):
                    # 工具事件先关 Live 再打印，避免渲染撕裂
                    if live is not None:
                        live.__exit__(None, None, None)
                        live = None
                    _render_tool_event(delta)
                    accumulated = ""  # 下一轮 text 从空开始
                    live = _open_live()
                    live.__enter__()
                elif delta.type == "message_done" and delta.usage:
                    console.print(
                        f"[dim]in={delta.usage.input_tokens} "
                        f"out={delta.usage.output_tokens}[/dim]"
                    )
        except Exception as e:
            console.print(f"\n[red]调用失败：{type(e).__name__}: {e}[/red]")
        finally:
            if live is not None:
                live.__exit__(None, None, None)


@app.command()
def chat() -> None:
    """与玄玑流式对话（CHAT 模式）。"""
    asyncio.run(_chat_loop())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
