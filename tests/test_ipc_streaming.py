"""IPC 多会话流式 / config CRUD 单测。

不验证完整 conductor 流——那已经在 test_chat_session 覆盖。这里只确认：
- IpcChatManager 启动/取消/HITL 桥能跟 notifier 正确联动
- _delta_to_payload 翻译表完备
- build_config_methods 暴露的 RPC 行为正确（profiles/mcp/hooks/skills）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from xuanji.config import ConfigStore, DeepSeekProfile
from xuanji.ipc.chat_manager import _delta_to_payload, _IpcHITLBridge
from xuanji.ipc.config_methods import build_config_methods
from xuanji.ipc.errors import RpcError
from xuanji.ipc.notifier import CapturingNotifier, NoOpNotifier
from xuanji.llm.providers.base import Delta, Usage

# ============================================================
# _delta_to_payload 翻译表
# ============================================================


def test_delta_translator_text_delta() -> None:
    out = _delta_to_payload("sid", Delta(type="text_delta", text="hi"))
    assert out is not None
    method, params = out
    assert method == "chat.text_delta"
    assert params == {"session_id": "sid", "text": "hi"}


def test_delta_translator_thinking_delta() -> None:
    out = _delta_to_payload("sid", Delta(type="thinking_delta", text="思考"))
    assert out is not None
    method, _ = out
    assert method == "chat.thinking_delta"


def test_delta_translator_tool_run_started() -> None:
    delta = Delta(
        type="tool_run_started",
        tool_name="read_file",
        tool_call_id="t1",
        args_final={"path": "x"},
    )
    out = _delta_to_payload("sid", delta)
    assert out is not None
    method, params = out
    assert method == "chat.tool_run_started"
    assert params["tool_name"] == "read_file"
    assert params["args"] == {"path": "x"}


def test_delta_translator_tool_run_blocked() -> None:
    out = _delta_to_payload(
        "sid",
        Delta(
            type="tool_run_blocked",
            tool_name="run_shell",
            tool_run_reason="HITL 拒绝",
        ),
    )
    assert out is not None
    method, params = out
    assert method == "chat.tool_run_blocked"
    assert params["reason"] == "HITL 拒绝"


def test_delta_translator_tool_run_done() -> None:
    out = _delta_to_payload(
        "sid",
        Delta(
            type="tool_run_done",
            tool_name="read_file",
            tool_run_ok=True,
            tool_run_duration_ms=42,
        ),
    )
    assert out is not None
    method, params = out
    assert method == "chat.tool_run_done"
    assert params["ok"] is True
    assert params["duration_ms"] == 42


def test_delta_translator_message_done() -> None:
    out = _delta_to_payload(
        "sid",
        Delta(
            type="message_done",
            stop_reason="end_turn",
            usage=Usage(input_tokens=100, output_tokens=20),
        ),
    )
    assert out is not None
    method, params = out
    assert method == "chat.message_done"
    assert params["stop_reason"] == "end_turn"
    assert params["usage"]["input_tokens"] == 100


def test_delta_translator_text_start_returns_none() -> None:
    """边界事件不需要推。"""
    assert _delta_to_payload("s", Delta(type="text_start")) is None
    assert _delta_to_payload("s", Delta(type="text_end")) is None


# ============================================================
# _IpcHITLBridge：confirm 等 deliver 设置 future
# ============================================================


@pytest.mark.asyncio
async def test_hitl_bridge_round_trip() -> None:
    notifier = CapturingNotifier()
    bridge = _IpcHITLBridge(
        session_id="s1", notifier=notifier, timeout_sec=5.0,
    )

    # 假 tool —— 只需要 .name 和 .risk
    class FakeTool:
        name = "run_shell"

        class _Risk:
            value = "exec"
        risk = _Risk()

    async def respond_after_delay() -> None:
        # 等通知发完才能 deliver
        await asyncio.sleep(0.05)
        # 取出最后一条 hitl_request 的 request_id
        method, params = notifier.events[-1]
        assert method == "chat.hitl_request"
        assert params["session_id"] == "s1"
        assert params["tool"] == "run_shell"
        bridge.deliver(params["request_id"], approve=True)

    responder = asyncio.create_task(respond_after_delay())
    try:
        ok = await bridge.confirm(
            tool=FakeTool(),
            args={"cmd": "ls"},
            reason="exec 风险",
        )
    finally:
        await responder
    assert ok is True


@pytest.mark.asyncio
async def test_hitl_bridge_timeout_returns_false() -> None:
    """没人 deliver → 超时返回 False（不抛）。"""
    notifier = NoOpNotifier()
    bridge = _IpcHITLBridge(
        session_id="s1", notifier=notifier, timeout_sec=0.05,
    )

    class FakeTool:
        name = "x"

        class _Risk:
            value = "io"
        risk = _Risk()

    ok = await bridge.confirm(tool=FakeTool(), args={}, reason="r")
    assert ok is False


def test_hitl_bridge_deliver_unknown_request_returns_false() -> None:
    bridge = _IpcHITLBridge(
        session_id="s1", notifier=NoOpNotifier(),
    )
    assert bridge.deliver("not-a-real-id", True) is False


# ============================================================
# build_config_methods 核心 RPC
# ============================================================


@pytest.fixture
def cfg_methods(tmp_path: Path) -> dict[str, Any]:
    cfg_path = tmp_path / "config.json"
    store = ConfigStore(path=cfg_path)
    store.upsert_profile(
        "ds_test",
        DeepSeekProfile(
            label="t", api_key="sk-test-placeholder", default_model="ds",
        ),
        activate=True,
    )
    methods = build_config_methods(
        cfg_store_factory=lambda: ConfigStore(path=cfg_path),
        hooks_dir=tmp_path / "hooks",
        skills_dir=tmp_path / "skills",
    )
    return {"methods": methods, "tmp": tmp_path, "cfg_path": cfg_path}


def test_config_summary(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(methods["config.summary"]({}))
    assert out["active_profile"] == "ds_test"
    assert out["assistant_alias"] == "姐姐"
    assert "compaction" in out


def test_config_set_aliases(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(
        methods["config.set_aliases"](
            {"user_alias": "宝子", "assistant_alias": "玄玑"},
        ),
    )
    assert out["ok"]
    summary = asyncio.run(methods["config.summary"]({}))
    assert summary["user_alias"] == "宝子"
    assert summary["assistant_alias"] == "玄玑"


def test_profiles_list_hides_api_key(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(methods["profiles.list"]({}))
    assert out["active"] == "ds_test"
    item = out["items"][0]
    assert "api_key" not in item


def test_profiles_show_returns_api_key_set_flag(
    cfg_methods: dict[str, Any],
) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(methods["profiles.show"]({"name": "ds_test"}))
    assert out["api_key_set"] is True
    assert "api_key" not in out


def test_profiles_upsert_anthropic(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(
        methods["profiles.upsert"](
            {
                "name": "claude_main",
                "kind": "anthropic",
                "api_key": "sk-test-placeholder",
                "default_model": "claude-opus-4-7",
            },
        ),
    )
    assert out["ok"]
    listed = asyncio.run(methods["profiles.list"]({}))
    names = [p["name"] for p in listed["items"]]
    assert "claude_main" in names


def test_profiles_upsert_openai_compat_requires_base_url(
    cfg_methods: dict[str, Any],
) -> None:
    methods = cfg_methods["methods"]
    with pytest.raises(RpcError, match="base_url"):
        asyncio.run(
            methods["profiles.upsert"](
                {
                    "name": "kimi",
                    "kind": "openai-compatible",
                    "api_key": "sk-test-placeholder",
                },
            ),
        )


def test_profiles_use_unknown_raises(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    with pytest.raises(RpcError):
        asyncio.run(methods["profiles.use"]({"name": "ghost"}))


def test_mcp_upsert_remove(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    asyncio.run(
        methods["mcp.upsert"](
            {
                "name": "fs",
                "transport": "stdio",
                "command": "npx",
                "args": ["@modelcontextprotocol/server-filesystem"],
                "enabled": True,
            },
        ),
    )
    out = asyncio.run(methods["mcp.list"]({}))
    assert any(s["name"] == "fs" for s in out["items"])
    set_out = asyncio.run(
        methods["mcp.set_enabled"]({"name": "fs", "enabled": False}),
    )
    assert set_out["ok"]
    removed = asyncio.run(methods["mcp.remove"]({"name": "fs"}))
    assert removed["ok"]


def test_hooks_set_get_remove(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    asyncio.run(
        methods["hooks.set_event"](
            {
                "event": "PreToolUse",
                "hooks": [
                    {
                        "matcher": "run_shell",
                        "command": "python -m my_audit",
                        "timeout": 10,
                    },
                ],
            },
        ),
    )
    out = asyncio.run(methods["hooks.get_event"]({"event": "PreToolUse"}))
    assert len(out["hooks"]) == 1
    assert out["hooks"][0]["matcher"] == "run_shell"

    listed = asyncio.run(methods["hooks.list"]({}))
    assert len(listed["events"]["PreToolUse"]) == 1
    assert listed["events"]["PostToolUse"] == []

    rm = asyncio.run(methods["hooks.remove_event"]({"event": "PreToolUse"}))
    assert rm["ok"]
    assert rm["removed"]


def test_hooks_unknown_event(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    with pytest.raises(RpcError, match="未知事件"):
        asyncio.run(methods["hooks.get_event"]({"event": "NotARealEvent"}))


def test_skills_files_list_empty_dir(cfg_methods: dict[str, Any]) -> None:
    methods = cfg_methods["methods"]
    out = asyncio.run(methods["skills.files.list"]({}))
    assert out["items"] == []
    # errors 可以是 dict 或 list 都算空
    assert not out["errors"]


# ============================================================
# Notifier 协议
# ============================================================


@pytest.mark.asyncio
async def test_capturing_notifier_records() -> None:
    n = CapturingNotifier()
    await n.notify("foo", {"x": 1})
    await n.notify("bar", {"y": 2})
    assert n.events == [("foo", {"x": 1}), ("bar", {"y": 2})]


@pytest.mark.asyncio
async def test_noop_notifier_silent() -> None:
    n = NoOpNotifier()
    await n.notify("foo", {})
