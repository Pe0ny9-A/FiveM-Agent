"""config.* / mcp.* / hooks.* / skills.* IPC method 集合。

VS Code 1.0 配置面板用得到的 CRUD 直接写到这里——绕开 LLM 工具
loop（config_tools 那套是给玄玑自己改配置用的，必经 Gate HITL）。
插件面板里点按钮，应当立刻见效，不需要走对话。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from xuanji.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    ProfileKind,
)
from xuanji.config.profiles import OFFICIAL_BASE_URLS, Profile
from xuanji.config.store import ChatUIConfig
from xuanji.hooks import HookEvent, HooksFile, HookSpec
from xuanji.ipc.errors import INVALID_PARAMS, RpcError
from xuanji.mcp.registry import McpServerConfig
from xuanji.neural.compaction import CompactionConfig
from xuanji.persona.modes import PersonaTemperature
from xuanji.skills import SkillsLoader


def _profile_summary(profile: Profile) -> dict[str, Any]:
    base_url = (
        str(profile.base_url)
        if isinstance(profile, OpenAICompatibleProfile)
        else OFFICIAL_BASE_URLS.get(profile.kind, "")
    )
    return {
        "label": profile.label,
        "kind": profile.kind.value,
        "default_model": profile.default_model,
        "base_url": base_url,
    }


def _require(params: dict[str, Any], key: str) -> Any:
    if key not in params:
        raise RpcError(INVALID_PARAMS, f"缺少参数：{key}")
    return params[key]


def build_config_methods(
    *,
    cfg_store_factory: Any,
    hooks_dir: Path,
    skills_dir: Path,
) -> dict[str, Any]:
    """构造所有 config / mcp / hooks / skills 的 RPC 方法。"""

    def _store() -> ConfigStore:
        store: ConfigStore = cfg_store_factory()
        return store

    # ---------------- config.* ----------------

    async def config_summary(params: dict[str, Any]) -> dict[str, Any]:
        cfg = _store().load()
        return {
            "active_profile": cfg.active_profile,
            "user_alias": cfg.user_alias,
            "assistant_alias": cfg.assistant_alias,
            "persona_temperature": cfg.persona_temperature.value,
            "chat_ui": cfg.chat_ui.model_dump(),
            "compaction": cfg.compaction.model_dump(),
        }

    async def config_set_aliases(params: dict[str, Any]) -> dict[str, Any]:
        _store().set_aliases(
            user_alias=params.get("user_alias"),
            assistant_alias=params.get("assistant_alias"),
        )
        return {"ok": True}

    async def config_set_persona_temperature(
        params: dict[str, Any],
    ) -> dict[str, Any]:
        value = _require(params, "value")
        try:
            temp = PersonaTemperature(value)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e
        _store().set_persona_temperature(temp)
        return {"ok": True, "value": temp.value}

    async def config_set_chat_ui(params: dict[str, Any]) -> dict[str, Any]:
        store = _store()
        cfg = store.load()
        if "show_thinking" in params:
            cfg.chat_ui = ChatUIConfig(show_thinking=bool(params["show_thinking"]))
        store.save(cfg)
        return {"ok": True, "chat_ui": cfg.chat_ui.model_dump()}

    async def config_set_compaction(params: dict[str, Any]) -> dict[str, Any]:
        store = _store()
        cfg = store.load()
        cur = cfg.compaction
        cfg.compaction = CompactionConfig(
            enabled=bool(params.get("enabled", cur.enabled)),
            max_context_tokens=int(
                params.get("max_context_tokens", cur.max_context_tokens),
            ),
            keep_recent_turns=int(
                params.get("keep_recent_turns", cur.keep_recent_turns),
            ),
        )
        store.save(cfg)
        return {"ok": True, "compaction": cfg.compaction.model_dump()}

    # ---------------- profiles.* ----------------

    async def profiles_list(params: dict[str, Any]) -> dict[str, Any]:
        cfg = _store().load()
        return {
            "active": cfg.active_profile,
            "items": [
                {"name": name, **_profile_summary(p)}
                for name, p in cfg.profiles.items()
            ],
        }

    async def profiles_show(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        cfg = _store().load()
        p = cfg.profiles.get(name)
        if p is None:
            raise RpcError(INVALID_PARAMS, f"profile 不存在：{name}")
        # api_key 不回传，只回是否设置
        return {
            "name": name,
            **_profile_summary(p),
            "api_key_set": bool(p.api_key),
        }

    async def profiles_upsert(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        kind_raw = _require(params, "kind")
        try:
            kind = ProfileKind(kind_raw)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"未知 profile kind：{kind_raw}") from e
        api_key = _require(params, "api_key")
        label = params.get("label") or name
        default_model = params.get("default_model") or _default_model_for_kind(kind)
        activate = bool(params.get("activate", False))

        profile: Profile
        if kind is ProfileKind.OPENAI_COMPATIBLE:
            base_url = params.get("base_url")
            if not base_url:
                raise RpcError(INVALID_PARAMS, "openai-compatible 需要 base_url")
            profile = OpenAICompatibleProfile(
                label=label,
                api_key=api_key,
                default_model=default_model,
                base_url=base_url,
            )
        elif kind is ProfileKind.ANTHROPIC:
            profile = AnthropicProfile(
                label=label, api_key=api_key, default_model=default_model,
            )
        elif kind is ProfileKind.OPENAI:
            profile = OpenAIProfile(
                label=label, api_key=api_key, default_model=default_model,
            )
        else:  # DEEPSEEK
            profile = DeepSeekProfile(
                label=label, api_key=api_key, default_model=default_model,
            )
        _store().upsert_profile(name, profile, activate=activate)
        return {"ok": True, "name": name, "activated": activate}

    async def profiles_use(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        try:
            _store().use_profile(name)
        except KeyError as e:
            raise RpcError(INVALID_PARAMS, f"profile 不存在：{name}") from e
        return {"ok": True, "active_profile": name}

    async def profiles_remove(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        ok = _store().remove_profile(name)
        return {"ok": ok}

    # ---------------- mcp.* ----------------

    async def mcp_list(params: dict[str, Any]) -> dict[str, Any]:
        cfg = _store().load()
        return {
            "items": [s.model_dump() for s in cfg.mcp_servers],
        }

    async def mcp_upsert(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        try:
            server = McpServerConfig(
                name=name,
                transport=params.get("transport", "stdio"),
                command=params.get("command"),
                args=list(params.get("args") or []),
                cwd=params.get("cwd"),
                env=dict(params.get("env") or {}),
                url=params.get("url"),
                enabled=bool(params.get("enabled", True)),
                description=params.get("description", ""),
            )
        except (ValueError, TypeError) as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e
        _store().upsert_mcp_server(server)
        return {"ok": True, "name": name}

    async def mcp_remove(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        ok = _store().remove_mcp_server(name)
        return {"ok": ok}

    async def mcp_set_enabled(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        enabled = bool(_require(params, "enabled"))
        ok = _store().set_mcp_enabled(name, enabled)
        return {"ok": ok}

    # ---------------- hooks.* ----------------

    def _hooks_path(event: HookEvent) -> Path:
        return hooks_dir / f"{event.value}.yaml"

    def _read_hooks_file(event: HookEvent) -> HooksFile:
        path = _hooks_path(event)
        if not path.exists():
            return HooksFile(hooks=[])
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise RpcError(INVALID_PARAMS, f"hook 文件解析失败：{e}") from e
        try:
            return HooksFile.model_validate(data)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"hook 文件 schema 错误：{e}") from e

    def _write_hooks_file(event: HookEvent, file_obj: HooksFile) -> None:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        path = _hooks_path(event)
        path.write_text(
            yaml.safe_dump(
                file_obj.model_dump(),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    async def hooks_list(params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, list[dict[str, Any]]] = {}
        for event in HookEvent:
            file_obj = _read_hooks_file(event)
            out[event.value] = [h.model_dump() for h in file_obj.hooks]
        return {"events": out}

    async def hooks_get_event(params: dict[str, Any]) -> dict[str, Any]:
        event_raw = _require(params, "event")
        try:
            event = HookEvent(event_raw)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"未知事件：{event_raw}") from e
        file_obj = _read_hooks_file(event)
        return {
            "event": event.value,
            "hooks": [h.model_dump() for h in file_obj.hooks],
        }

    async def hooks_set_event(params: dict[str, Any]) -> dict[str, Any]:
        """整体覆盖某事件的 hook 列表。"""
        event_raw = _require(params, "event")
        try:
            event = HookEvent(event_raw)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"未知事件：{event_raw}") from e
        hooks_raw = params.get("hooks") or []
        try:
            specs = [HookSpec.model_validate(h) for h in hooks_raw]
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"hook spec 错误：{e}") from e
        _write_hooks_file(event, HooksFile(hooks=specs))
        return {"ok": True, "event": event.value, "count": len(specs)}

    async def hooks_remove_event(params: dict[str, Any]) -> dict[str, Any]:
        event_raw = _require(params, "event")
        try:
            event = HookEvent(event_raw)
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, f"未知事件：{event_raw}") from e
        path = _hooks_path(event)
        existed = path.exists()
        if existed:
            path.unlink()
        return {"ok": True, "removed": existed}

    # ---------------- skills.files.* ----------------

    async def skills_files_list(params: dict[str, Any]) -> dict[str, Any]:
        loader = SkillsLoader(skills_dir)
        skills = loader.all()
        return {
            "items": [
                {
                    "name": s.name,
                    "description": s.frontmatter.description,
                    "triggers": s.frontmatter.triggers,
                    "tools": s.frontmatter.tools,
                    "allowed_tools": s.frontmatter.allowed_tools,
                    "path": str(s.path),
                }
                for s in skills
            ],
            "errors": loader.errors(),
            "root": str(skills_dir),
        }

    async def skills_files_show(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        loader = SkillsLoader(skills_dir)
        s = loader.get(name)
        if s is None:
            raise RpcError(INVALID_PARAMS, f"skill 不存在：{name}")
        return {
            "name": s.name,
            "description": s.frontmatter.description,
            "triggers": s.frontmatter.triggers,
            "tools": s.frontmatter.tools,
            "allowed_tools": s.frontmatter.allowed_tools,
            "metadata": s.frontmatter.metadata,
            "body": s.body,
            "path": str(s.path),
        }

    return {
        "config.summary": config_summary,
        "config.set_aliases": config_set_aliases,
        "config.set_persona_temperature": config_set_persona_temperature,
        "config.set_chat_ui": config_set_chat_ui,
        "config.set_compaction": config_set_compaction,
        "profiles.list": profiles_list,
        "profiles.show": profiles_show,
        "profiles.upsert": profiles_upsert,
        "profiles.use": profiles_use,
        "profiles.remove": profiles_remove,
        "mcp.list": mcp_list,
        "mcp.upsert": mcp_upsert,
        "mcp.remove": mcp_remove,
        "mcp.set_enabled": mcp_set_enabled,
        "hooks.list": hooks_list,
        "hooks.get_event": hooks_get_event,
        "hooks.set_event": hooks_set_event,
        "hooks.remove_event": hooks_remove_event,
        "skills.files.list": skills_files_list,
        "skills.files.show": skills_files_show,
    }


def _default_model_for_kind(kind: ProfileKind) -> str:
    from xuanji.config.profiles import DEFAULT_MODELS

    return DEFAULT_MODELS[kind]


__all__ = ["build_config_methods"]
