"""自配置工具：让玄玑能用自然语言改自己的配置。

允许玄玑读 / 写自己的配置：profile、人设温度、对话称呼、聊天 UI、
context 压缩阈值、MCP 开关、安装 hook。

风险等级：
- list_profiles / show_active_config / list_mcp_servers / list_hooks → SAFE（只读）
- 其他写类工具 → IO（走司辰阁 HITL，小宝看到改什么再确认）

设计取舍：
- 只暴露"对话里有意义"的旋钮。API Key 增删仍需 CLI `xuanji config add`，
  避免模型在对话里看到密钥明文，也避免模型自己往 profile 里写错 endpoint。
- install_hook 写 YAML 文件，hooks_dir() 落盘后下次 chat 自动生效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import yaml

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from xuanji.config.store import ConfigStore
from xuanji.persona.modes import PersonaTemperature
from xuanji.tools._args import require_str

_VALID_HOOK_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Notification",
}


# ----------------------------- profile 管理 -----------------------------


class ListProfilesTool(Tool):
    """列出所有 LLM profile。"""

    name = "list_profiles"
    description = (
        "列出小宝配置过的所有 LLM profile（Anthropic / OpenAI / DeepSeek / OpenAI-Compatible），"
        "标记当前激活的那一个。用于：小宝问「我都配了哪些模型」、"
        "或者你判断要切 profile 之前先看看有哪些可选。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        cfg = self._store.load()
        items: list[dict[str, Any]] = []
        for name, profile in cfg.profiles.items():
            items.append(
                {
                    "name": name,
                    "kind": profile.kind.value,
                    "label": profile.label,
                    "default_model": profile.default_model,
                    "active": name == cfg.active_profile,
                },
            )
        return ToolResult(
            ok=True,
            output=items,
            extra={"active": cfg.active_profile, "count": len(items)},
        )


class SwitchProfileTool(Tool):
    """切换当前激活的 profile。"""

    name = "switch_profile"
    description = (
        "把激活的 LLM profile 切到指定的那个。切完下次 chat 起效——本次会话仍用旧的。"
        "适用：小宝说「换成 Claude」「用 DeepSeek 跑这个长任务」。"
        "不适用：新增或删除 profile（那些走 CLI `xuanji config add/remove`，避免 Key 在对话里出现）。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "profile 名（需已存在）"},
        },
        "required": ["name"],
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name, err = require_str(args, "name")
        if err is not None:
            return err
        assert name is not None
        try:
            self._store.use_profile(name)
        except KeyError:
            return ToolResult(
                ok=False,
                error=f"profile {name!r} 不存在；用 list_profiles 看一下都有哪些。",
            )
        return ToolResult(
            ok=True,
            output={"active": name},
            extra={"hint": "下次 chat 起效；本会话仍用切换前的 profile。"},
        )


# ----------------------------- 聊天 UI / 压缩 -----------------------------


class ShowActiveConfigTool(Tool):
    """查看当前激活配置摘要。"""

    name = "show_active_config"
    description = (
        "返回当前激活配置的摘要：active profile / 人设温度 / 称呼 / "
        "compaction 阈值 / chat_ui 偏好 / mcp 开关清单。"
        "不包含 API Key 等敏感字段。改配置前先用它看清现状。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        cfg = self._store.load()
        active = cfg.get_active()
        return ToolResult(
            ok=True,
            output={
                "active_profile": cfg.active_profile,
                "active_kind": active.kind.value if active else None,
                "active_default_model": active.default_model if active else None,
                "persona_temperature": cfg.persona_temperature.value,
                "user_alias": cfg.user_alias,
                "assistant_alias": cfg.assistant_alias,
                "compaction": {
                    "enabled": cfg.compaction.enabled,
                    "max_context_tokens": cfg.compaction.max_context_tokens,
                    "keep_recent_turns": cfg.compaction.keep_recent_turns,
                },
                "chat_ui": {"show_thinking": cfg.chat_ui.show_thinking},
                "mcp_servers": [
                    {"name": s.name, "enabled": s.enabled} for s in cfg.mcp_servers
                ],
            },
        )


class SetChatUITool(Tool):
    """改 CLI 聊天框 UI 偏好（thinking 显示开关）。"""

    name = "set_chat_ui"
    description = (
        "调 CLI 聊天显示偏好。目前只有一项：是否打印 thinking 思维链。"
        "默认关闭——思维链对调试有用，对日常对话是噪音。"
        "对话里小宝说「把思考过程显示出来」「关掉那串紫色文字」时用。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "show_thinking": {
                "type": "boolean",
                "description": "true 显示 thinking_delta；false 隐藏",
            },
        },
        "required": ["show_thinking"],
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        if "show_thinking" not in args:
            return ToolResult(ok=False, error="missing required arg: 'show_thinking'。")
        raw = args["show_thinking"]
        if not isinstance(raw, bool):
            return ToolResult(
                ok=False,
                error=f"show_thinking 必须是 boolean，收到 {type(raw).__name__}。",
            )
        cfg = self._store.load()
        cfg.chat_ui.show_thinking = raw
        self._store.save(cfg)
        return ToolResult(
            ok=True,
            output={"show_thinking": raw},
            extra={"hint": "下次进 chat 起效；本会话即时生效（CLI 每轮都重读）。"},
        )


class SetCompactionTool(Tool):
    """改 context 自动压缩配置。"""

    name = "set_compaction"
    description = (
        "调上下文自动压缩阈值。当 history 估算 token 超 max_context_tokens 时，"
        "玄玑会把最早的轮次折叠成摘要。"
        "适用：小宝说「我的模型有 200 万上下文，不要压」、"
        "「跑长任务前把阈值放宽到 30 万」、「关闭自动压缩」。"
        "提示：状态栏左边的 ctx 百分比是按真实 window 算的；"
        "右边的 compact 才看这里设的阈值。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "true 开启自动压缩；false 完全关闭",
            },
            "max_context_tokens": {
                "type": "integer",
                "description": "触发压缩的 token 阈值（如 80000 / 300000 / 1000000）",
                "minimum": 4000,
            },
            "keep_recent_turns": {
                "type": "integer",
                "description": "尾部保留多少轮原文不压缩，默认 4",
                "minimum": 1,
                "maximum": 32,
            },
        },
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        if not args:
            return ToolResult(ok=False, error="至少提供一个字段：enabled / max_context_tokens / keep_recent_turns。")
        cfg = self._store.load()
        changed: dict[str, Any] = {}
        if "enabled" in args:
            raw = args["enabled"]
            if not isinstance(raw, bool):
                return ToolResult(ok=False, error="enabled 必须是 boolean。")
            cfg.compaction.enabled = raw
            changed["enabled"] = raw
        if "max_context_tokens" in args:
            try:
                v = int(args["max_context_tokens"])
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="max_context_tokens 必须是整数。")
            if v < 4000:
                return ToolResult(
                    ok=False,
                    error="max_context_tokens 不能低于 4000——压得太狠摘要也装不下。",
                )
            cfg.compaction.max_context_tokens = v
            changed["max_context_tokens"] = v
        if "keep_recent_turns" in args:
            try:
                v = int(args["keep_recent_turns"])
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="keep_recent_turns 必须是整数。")
            if v < 1 or v > 32:
                return ToolResult(ok=False, error="keep_recent_turns 范围 1~32。")
            cfg.compaction.keep_recent_turns = v
            changed["keep_recent_turns"] = v
        self._store.save(cfg)
        return ToolResult(
            ok=True,
            output=changed,
            extra={"hint": "本会话不动——已经活着的 Conductor 持有快照；下次 chat 起效。"},
        )


# ----------------------------- 人设 -----------------------------


class SetPersonaTemperatureTool(Tool):
    """改人设温度档。"""

    name = "set_persona_temperature"
    description = (
        "调玄玑的人设温度：playful 全程调侃 / balanced 适度（默认）/ professional 关闭人设。"
        "温度只影响语气与污段子频次，不影响判断逻辑与守护边界。"
        "适用：小宝说「严肃点」「太正经了，活泼一点」。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "temperature": {
                "type": "string",
                "enum": ["playful", "balanced", "professional"],
            },
        },
        "required": ["temperature"],
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        temp_str, err = require_str(args, "temperature")
        if err is not None:
            return err
        assert temp_str is not None
        try:
            temp = PersonaTemperature(temp_str)
        except ValueError:
            return ToolResult(
                ok=False,
                error=f"temperature 必须是 playful / balanced / professional 之一，收到 {temp_str!r}。",
            )
        self._store.set_persona_temperature(temp)
        return ToolResult(
            ok=True,
            output={"temperature": temp.value},
            extra={"hint": "下次 chat 起效。"},
        )


class SetAliasTool(Tool):
    """改对话称呼。"""

    name = "set_alias"
    description = (
        "改玄玑在对话中的称呼：自称（默认「姐姐」）和对用户的称呼（默认「小宝」）。"
        "玄玑这个真名永远不变。"
        "适用：小宝说「以后叫我老板」「你别自称姐姐了，叫我先生」。"
        "两个字段都可选，单独传一个就只改一个。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "user_alias": {
                "type": "string",
                "description": "玄玑对用户的称呼，1~16 字",
                "minLength": 1,
                "maxLength": 16,
            },
            "assistant_alias": {
                "type": "string",
                "description": "玄玑自称，1~16 字",
                "minLength": 1,
                "maxLength": 16,
            },
        },
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        user_alias = args.get("user_alias")
        assistant_alias = args.get("assistant_alias")
        if user_alias is None and assistant_alias is None:
            return ToolResult(
                ok=False,
                error="user_alias 和 assistant_alias 至少传一个。",
            )
        for k, v in (("user_alias", user_alias), ("assistant_alias", assistant_alias)):
            if v is None:
                continue
            if not isinstance(v, str):
                return ToolResult(ok=False, error=f"{k} 必须是字符串。")
            if len(v) < 1 or len(v) > 16:
                return ToolResult(ok=False, error=f"{k} 长度必须 1~16 字。")
        self._store.set_aliases(
            user_alias=user_alias,
            assistant_alias=assistant_alias,
        )
        cfg = self._store.load()
        return ToolResult(
            ok=True,
            output={
                "user_alias": cfg.user_alias,
                "assistant_alias": cfg.assistant_alias,
            },
            extra={"hint": "下次 chat 起效。"},
        )


# ----------------------------- MCP -----------------------------


class SetMcpEnabledTool(Tool):
    """开关一个已配置的 MCP server。"""

    name = "set_mcp_enabled"
    description = (
        "把已配置的某个 MCP server 启用或停用。enabled=true 下次 chat 启动时拉起，"
        "false 不连。新增 MCP server 仍走 CLI `xuanji mcp add`（避免在对话里出现 token）。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "MCP server 名"},
            "enabled": {"type": "boolean"},
        },
        "required": ["name", "enabled"],
    }

    def __init__(self, cfg_store: ConfigStore) -> None:
        self._store = cfg_store

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        name, err = require_str(args, "name")
        if err is not None:
            return err
        if "enabled" not in args:
            return ToolResult(ok=False, error="missing required arg: 'enabled'。")
        raw = args["enabled"]
        if not isinstance(raw, bool):
            return ToolResult(ok=False, error="enabled 必须是 boolean。")
        assert name is not None
        ok = self._store.set_mcp_enabled(name, raw)
        if not ok:
            return ToolResult(
                ok=False,
                error=f"MCP server {name!r} 不存在，先用 CLI `xuanji mcp add` 配进来。",
            )
        return ToolResult(
            ok=True,
            output={"name": name, "enabled": raw},
            extra={"hint": "下次 chat 起效；本会话已 attach 的 MCP 不动。"},
        )


# ----------------------------- Hooks -----------------------------


class ListHooksTool(Tool):
    """查当前已安装的 hooks。"""

    name = "list_hooks"
    description = (
        "列出 hooks 目录下每个事件文件的所有 hook spec。"
        "用于：小宝问「我有哪些 hook」、或者你要新增 hook 之前先看看有没有同名的。"
    )
    risk = RiskTag.SAFE
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "event": {
                "type": "string",
                "enum": list(_VALID_HOOK_EVENTS),
                "description": "可选：仅看某个事件",
            },
        },
    }

    def __init__(self, hooks_root: Path) -> None:
        self._root = hooks_root

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        events = (
            [args["event"]]
            if args.get("event") in _VALID_HOOK_EVENTS
            else sorted(_VALID_HOOK_EVENTS)
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            path = self._root / f"{ev}.yaml"
            if not path.exists():
                out[ev] = []
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                out[ev] = [{"error": f"YAML 解析失败：{e}"}]
                continue
            specs = data.get("hooks") if isinstance(data, dict) else None
            if not isinstance(specs, list):
                out[ev] = []
                continue
            out[ev] = [
                {
                    "matcher": s.get("matcher", "*"),
                    "command": s.get("command", ""),
                    "timeout": s.get("timeout", 30.0),
                    "description": s.get("description", ""),
                }
                for s in specs
                if isinstance(s, dict)
            ]
        return ToolResult(ok=True, output=out, extra={"hooks_dir": str(self._root)})


class InstallHookTool(Tool):
    """往 hooks 目录新增一条 hook。"""

    name = "install_hook"
    description = (
        "新增一条 hook 到对应事件的 YAML 文件里——追加，不覆盖。"
        "事件名（PreToolUse / PostToolUse / UserPromptSubmit / Notification）与 Claude Code 一致。"
        "matcher：PreToolUse/PostToolUse 是 tool_name glob，UserPromptSubmit 是子串，Notification 仅 '*'。"
        "command 是完整 shell 命令。下次 chat 起效。"
        "适用：小宝说「每次 run_shell 之前先 echo 一下」「prompt 里出现 deploy 时跑 audit.py」。"
    )
    risk = RiskTag.IO
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "event": {
                "type": "string",
                "enum": list(_VALID_HOOK_EVENTS),
            },
            "matcher": {
                "type": "string",
                "description": "tool_name glob 或 prompt 子串",
                "default": "*",
            },
            "command": {
                "type": "string",
                "description": "完整 shell 命令",
            },
            "timeout": {
                "type": "number",
                "description": "秒，默认 30",
                "default": 30.0,
            },
            "description": {
                "type": "string",
                "description": "可选：写给以后的自己看，这个 hook 干嘛的",
            },
        },
        "required": ["event", "command"],
    }

    def __init__(self, hooks_root: Path) -> None:
        self._root = hooks_root

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        event, err = require_str(args, "event")
        if err is not None:
            return err
        command, err = require_str(args, "command")
        if err is not None:
            return err
        assert event is not None and command is not None
        if event not in _VALID_HOOK_EVENTS:
            return ToolResult(
                ok=False,
                error=f"event 必须是 {sorted(_VALID_HOOK_EVENTS)} 之一。",
            )
        matcher = args.get("matcher", "*")
        if not isinstance(matcher, str) or not matcher:
            return ToolResult(ok=False, error="matcher 必须是非空字符串。")
        timeout_raw = args.get("timeout", 30.0)
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            return ToolResult(ok=False, error="timeout 必须是数字（秒）。")
        if timeout <= 0:
            return ToolResult(ok=False, error="timeout 必须 > 0。")
        description = args.get("description", "")
        if not isinstance(description, str):
            description = ""

        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{event}.yaml"
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    raw_hooks = data.get("hooks", [])
                    if isinstance(raw_hooks, list):
                        existing = [h for h in raw_hooks if isinstance(h, dict)]
            except yaml.YAMLError as e:
                return ToolResult(ok=False, error=f"现有 {path.name} YAML 损坏：{e}")
        new_spec: dict[str, Any] = {
            "matcher": matcher,
            "command": command,
            "timeout": timeout,
        }
        if description:
            new_spec["description"] = description
        existing.append(new_spec)
        path.write_text(
            yaml.safe_dump(
                {"hooks": existing},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return ToolResult(
            ok=True,
            output={
                "event": event,
                "path": str(path),
                "total_hooks": len(existing),
                "added": new_spec,
            },
            extra={"hint": "下次 chat 起效；HooksRegistry 按 mtime 缓存，会自动重读。"},
        )


# ----------------------------- 工厂 -----------------------------


def config_tools(cfg_store: ConfigStore, hooks_root: Path) -> list[Tool]:
    """工厂：返回全家桶配置工具。"""
    return [
        ListProfilesTool(cfg_store),
        SwitchProfileTool(cfg_store),
        ShowActiveConfigTool(cfg_store),
        SetChatUITool(cfg_store),
        SetCompactionTool(cfg_store),
        SetPersonaTemperatureTool(cfg_store),
        SetAliasTool(cfg_store),
        SetMcpEnabledTool(cfg_store),
        ListHooksTool(hooks_root),
        InstallHookTool(hooks_root),
    ]


__all__ = [
    "InstallHookTool",
    "ListHooksTool",
    "ListProfilesTool",
    "SetAliasTool",
    "SetChatUITool",
    "SetCompactionTool",
    "SetMcpEnabledTool",
    "SetPersonaTemperatureTool",
    "ShowActiveConfigTool",
    "SwitchProfileTool",
    "config_tools",
]
