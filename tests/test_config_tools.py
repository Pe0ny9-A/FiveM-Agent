"""全家桶配置工具单测。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from xuanji.capability.tool import RiskTag, ToolCtx
from xuanji.config.profiles import AnthropicProfile, ProfileKind
from xuanji.config.store import ConfigStore
from xuanji.mcp.registry import McpServerConfig
from xuanji.persona.modes import PersonaTemperature
from xuanji.tools.config_tools import (
    InstallHookTool,
    ListHooksTool,
    ListProfilesTool,
    SetAliasTool,
    SetChatUITool,
    SetCompactionTool,
    SetMcpEnabledTool,
    SetPersonaTemperatureTool,
    ShowActiveConfigTool,
    SwitchProfileTool,
    config_tools,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.fixture
def cfg_store(tmp_path: Path) -> ConfigStore:
    store = ConfigStore(path=tmp_path / "config.json")
    cfg = store.load()
    cfg.profiles["claude"] = AnthropicProfile(
        kind=ProfileKind.ANTHROPIC,
        label="Claude Sonnet",
        api_key="sk-test-placeholder",
        default_model="claude-sonnet-4-6",
    )
    cfg.profiles["openai"] = AnthropicProfile(
        kind=ProfileKind.ANTHROPIC,
        label="Claude Haiku",
        api_key="sk-test-placeholder",
        default_model="claude-haiku-4-5",
    )
    cfg.active_profile = "claude"
    store.save(cfg)
    return store


@pytest.fixture
def hooks_root(tmp_path: Path) -> Path:
    root = tmp_path / "hooks"
    root.mkdir()
    return root


# ---------------- factory ----------------


def test_factory_returns_full_set(cfg_store: ConfigStore, hooks_root: Path) -> None:
    tools = config_tools(cfg_store, hooks_root)
    names = {t.name for t in tools}
    assert names == {
        "list_profiles",
        "switch_profile",
        "show_active_config",
        "set_chat_ui",
        "set_compaction",
        "set_persona_temperature",
        "set_alias",
        "set_mcp_enabled",
        "list_hooks",
        "install_hook",
    }


def test_risk_tags_correct(cfg_store: ConfigStore, hooks_root: Path) -> None:
    tools = {t.name: t for t in config_tools(cfg_store, hooks_root)}
    assert tools["list_profiles"].risk == RiskTag.SAFE
    assert tools["show_active_config"].risk == RiskTag.SAFE
    assert tools["list_hooks"].risk == RiskTag.SAFE
    assert tools["switch_profile"].risk == RiskTag.IO
    assert tools["set_compaction"].risk == RiskTag.IO
    assert tools["install_hook"].risk == RiskTag.IO


# ---------------- list_profiles ----------------


@pytest.mark.asyncio
async def test_list_profiles_marks_active(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = ListProfilesTool(cfg_store)
    res = await tool.execute({}, ctx)
    assert res.ok
    assert res.extra["count"] == 2
    assert res.extra["active"] == "claude"
    by_name = {item["name"]: item for item in res.output}
    assert by_name["claude"]["active"] is True
    assert by_name["openai"]["active"] is False


# ---------------- switch_profile ----------------


@pytest.mark.asyncio
async def test_switch_profile_changes_active(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SwitchProfileTool(cfg_store)
    res = await tool.execute({"name": "openai"}, ctx)
    assert res.ok
    assert cfg_store.load().active_profile == "openai"


@pytest.mark.asyncio
async def test_switch_profile_unknown_returns_error(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SwitchProfileTool(cfg_store)
    res = await tool.execute({"name": "nonexistent"}, ctx)
    assert res.ok is False
    assert "不存在" in (res.error or "")


@pytest.mark.asyncio
async def test_switch_profile_missing_arg_returns_friendly_error(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    """Bug #4 风格：缺参数也是友好错误，不抛 KeyError。"""
    tool = SwitchProfileTool(cfg_store)
    res = await tool.execute({}, ctx)
    assert res.ok is False
    assert "name" in (res.error or "")


# ---------------- show_active_config ----------------


@pytest.mark.asyncio
async def test_show_active_config_summary(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = ShowActiveConfigTool(cfg_store)
    res = await tool.execute({}, ctx)
    assert res.ok
    out = res.output
    assert out["active_profile"] == "claude"
    assert out["active_kind"] == "anthropic"
    assert out["active_default_model"] == "claude-sonnet-4-6"
    assert out["persona_temperature"] == "balanced"
    assert out["compaction"]["enabled"] is True
    assert out["chat_ui"]["show_thinking"] is False


# ---------------- set_chat_ui ----------------


@pytest.mark.asyncio
async def test_set_chat_ui_toggles_thinking(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetChatUITool(cfg_store)
    res = await tool.execute({"show_thinking": True}, ctx)
    assert res.ok
    assert cfg_store.load().chat_ui.show_thinking is True
    res = await tool.execute({"show_thinking": False}, ctx)
    assert res.ok
    assert cfg_store.load().chat_ui.show_thinking is False


@pytest.mark.asyncio
async def test_set_chat_ui_rejects_non_bool(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetChatUITool(cfg_store)
    res = await tool.execute({"show_thinking": "yes"}, ctx)
    assert res.ok is False


# ---------------- set_compaction ----------------


@pytest.mark.asyncio
async def test_set_compaction_updates_threshold(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetCompactionTool(cfg_store)
    res = await tool.execute({"max_context_tokens": 1_000_000}, ctx)
    assert res.ok
    cfg = cfg_store.load()
    assert cfg.compaction.max_context_tokens == 1_000_000


@pytest.mark.asyncio
async def test_set_compaction_can_disable(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetCompactionTool(cfg_store)
    res = await tool.execute({"enabled": False}, ctx)
    assert res.ok
    assert cfg_store.load().compaction.enabled is False


@pytest.mark.asyncio
async def test_set_compaction_rejects_too_low(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetCompactionTool(cfg_store)
    res = await tool.execute({"max_context_tokens": 100}, ctx)
    assert res.ok is False


@pytest.mark.asyncio
async def test_set_compaction_rejects_empty_args(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetCompactionTool(cfg_store)
    res = await tool.execute({}, ctx)
    assert res.ok is False


@pytest.mark.asyncio
async def test_set_compaction_keep_recent_turns(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetCompactionTool(cfg_store)
    res = await tool.execute({"keep_recent_turns": 8}, ctx)
    assert res.ok
    assert cfg_store.load().compaction.keep_recent_turns == 8

    res = await tool.execute({"keep_recent_turns": 100}, ctx)
    assert res.ok is False


# ---------------- set_persona_temperature ----------------


@pytest.mark.asyncio
async def test_set_persona_temperature(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetPersonaTemperatureTool(cfg_store)
    res = await tool.execute({"temperature": "professional"}, ctx)
    assert res.ok
    assert cfg_store.load().persona_temperature == PersonaTemperature.PROFESSIONAL

    res = await tool.execute({"temperature": "playful"}, ctx)
    assert res.ok
    assert cfg_store.load().persona_temperature == PersonaTemperature.PLAYFUL


@pytest.mark.asyncio
async def test_set_persona_temperature_rejects_unknown(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetPersonaTemperatureTool(cfg_store)
    res = await tool.execute({"temperature": "spicy"}, ctx)
    assert res.ok is False


# ---------------- set_alias ----------------


@pytest.mark.asyncio
async def test_set_alias_user_only(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetAliasTool(cfg_store)
    res = await tool.execute({"user_alias": "老板"}, ctx)
    assert res.ok
    cfg = cfg_store.load()
    assert cfg.user_alias == "老板"
    assert cfg.assistant_alias == "姐姐"  # 不变


@pytest.mark.asyncio
async def test_set_alias_both(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetAliasTool(cfg_store)
    res = await tool.execute(
        {"user_alias": "boss", "assistant_alias": "xuanji"}, ctx,
    )
    assert res.ok
    cfg = cfg_store.load()
    assert cfg.user_alias == "boss"
    assert cfg.assistant_alias == "xuanji"


@pytest.mark.asyncio
async def test_set_alias_requires_at_least_one(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetAliasTool(cfg_store)
    res = await tool.execute({}, ctx)
    assert res.ok is False


@pytest.mark.asyncio
async def test_set_alias_too_long(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetAliasTool(cfg_store)
    res = await tool.execute({"user_alias": "x" * 50}, ctx)
    assert res.ok is False


# ---------------- set_mcp_enabled ----------------


@pytest.mark.asyncio
async def test_set_mcp_enabled_toggles(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    cfg = cfg_store.load()
    cfg.mcp_servers.append(
        McpServerConfig(name="filesystem", command="npx", args=[], enabled=True),
    )
    cfg_store.save(cfg)

    tool = SetMcpEnabledTool(cfg_store)
    res = await tool.execute({"name": "filesystem", "enabled": False}, ctx)
    assert res.ok
    cfg2 = cfg_store.load()
    assert cfg2.mcp_servers[0].enabled is False


@pytest.mark.asyncio
async def test_set_mcp_enabled_unknown(
    cfg_store: ConfigStore, ctx: ToolCtx,
) -> None:
    tool = SetMcpEnabledTool(cfg_store)
    res = await tool.execute({"name": "nope", "enabled": True}, ctx)
    assert res.ok is False


# ---------------- list_hooks / install_hook ----------------


@pytest.mark.asyncio
async def test_list_hooks_empty_dir(hooks_root: Path, ctx: ToolCtx) -> None:
    tool = ListHooksTool(hooks_root)
    res = await tool.execute({}, ctx)
    assert res.ok
    assert all(v == [] for v in res.output.values())


@pytest.mark.asyncio
async def test_install_hook_creates_file(
    hooks_root: Path, ctx: ToolCtx,
) -> None:
    tool = InstallHookTool(hooks_root)
    res = await tool.execute(
        {
            "event": "PreToolUse",
            "matcher": "run_shell",
            "command": "echo hi",
            "description": "log every shell call",
        },
        ctx,
    )
    assert res.ok
    path = hooks_root / "PreToolUse.yaml"
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(data["hooks"]) == 1
    assert data["hooks"][0]["matcher"] == "run_shell"
    assert data["hooks"][0]["command"] == "echo hi"
    assert data["hooks"][0]["description"] == "log every shell call"


@pytest.mark.asyncio
async def test_install_hook_appends_existing(
    hooks_root: Path, ctx: ToolCtx,
) -> None:
    """新增 hook 不能覆盖已有的——追加。"""
    tool = InstallHookTool(hooks_root)
    await tool.execute(
        {"event": "PreToolUse", "matcher": "run_shell", "command": "a"}, ctx,
    )
    await tool.execute(
        {"event": "PreToolUse", "matcher": "write_file", "command": "b"}, ctx,
    )
    data = yaml.safe_load(
        (hooks_root / "PreToolUse.yaml").read_text(encoding="utf-8"),
    )
    assert len(data["hooks"]) == 2


@pytest.mark.asyncio
async def test_install_hook_rejects_bad_event(
    hooks_root: Path, ctx: ToolCtx,
) -> None:
    tool = InstallHookTool(hooks_root)
    res = await tool.execute(
        {"event": "BeforeShell", "command": "echo"}, ctx,
    )
    assert res.ok is False


@pytest.mark.asyncio
async def test_list_hooks_after_install(
    hooks_root: Path, ctx: ToolCtx,
) -> None:
    install = InstallHookTool(hooks_root)
    await install.execute(
        {
            "event": "UserPromptSubmit",
            "matcher": "deploy",
            "command": "audit.py",
        },
        ctx,
    )
    listing = ListHooksTool(hooks_root)
    res = await listing.execute({"event": "UserPromptSubmit"}, ctx)
    assert res.ok
    assert len(res.output["UserPromptSubmit"]) == 1
    assert res.output["UserPromptSubmit"][0]["matcher"] == "deploy"
