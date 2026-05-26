"""CLI chat 会话快照 + ChatUIConfig 单测。

不依赖真实 API key——只测纯结构与 round-trip。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from xuanji.config.store import ChatUIConfig, ConfigStore, XuanjiConfig
from xuanji.llm.providers.base import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from xuanji.neural.session_store import (
    ChatSessionSnapshot,
    clear_last_session,
    format_age,
    load_last_session,
    save_last_session,
)


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "cfg"))


# ----------------- ChatUIConfig -----------------

def test_chat_ui_default_show_thinking_false() -> None:
    cfg = ChatUIConfig()
    assert cfg.show_thinking is False


def test_xuanji_config_round_trip_persists_show_thinking(tmp_path: Path) -> None:
    """配置文件读写一轮后 show_thinking 不丢。"""
    store = ConfigStore()
    cfg = XuanjiConfig()
    cfg.chat_ui.show_thinking = True
    store.save(cfg)

    cfg2 = store.load()
    assert cfg2.chat_ui.show_thinking is True


# ----------------- SessionSnapshot -----------------


def test_snapshot_roundtrip_preserves_blocks() -> None:
    history = [
        Message(role="user", content="QBCore 怎么加物品"),
        Message(
            role="assistant",
            content=[
                ThinkingBlock(text="先查一下"),
                TextBlock(text="QBCore.Functions.CreateUseableItem"),
                ToolCallBlock(id="t1", name="read_file", args={"path": "a.lua"}),
            ],
        ),
        Message(
            role="tool",
            content=[ToolResultBlock(tool_call_id="t1", output="ok")],
        ),
    ]
    snap = ChatSessionSnapshot(
        profile_name="my-ds",
        provider="deepseek",
        model="deepseek-v4-pro",
        history=history,
    )
    save_last_session(snap)

    loaded = load_last_session()
    assert loaded is not None
    assert loaded.profile_name == "my-ds"
    assert loaded.provider == "deepseek"
    assert loaded.model == "deepseek-v4-pro"
    assert len(loaded.history) == 3

    # ThinkingBlock 必须保留——否则下一轮 DeepSeek 就 400 了
    asst = loaded.history[1]
    assert isinstance(asst.content, list)
    assert any(isinstance(b, ThinkingBlock) and b.text == "先查一下" for b in asst.content)
    # ToolCallBlock args 也要保留
    assert any(
        isinstance(b, ToolCallBlock) and b.args == {"path": "a.lua"} for b in asst.content
    )


def test_snapshot_turn_count_counts_user_messages() -> None:
    snap = ChatSessionSnapshot(
        profile_name="x", provider="anthropic", model="claude-sonnet-4-6",
        history=[
            Message(role="user", content="一"),
            Message(role="assistant", content="一答"),
            Message(role="user", content="二"),
            Message(role="assistant", content="二答"),
        ],
    )
    assert snap.turn_count == 2


def test_load_returns_none_when_no_file() -> None:
    assert load_last_session() is None


def test_load_returns_none_on_corrupt_file() -> None:
    from xuanji.config.paths import chat_session_last_path
    p = chat_session_last_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    assert load_last_session() is None


def test_clear_last_session_removes_file() -> None:
    snap = ChatSessionSnapshot(
        profile_name="x", provider="anthropic", model="claude-sonnet-4-6",
        history=[Message(role="user", content="hi")],
    )
    save_last_session(snap)
    assert load_last_session() is not None
    assert clear_last_session() is True
    assert load_last_session() is None
    # 再删一次返回 False（不存在）
    assert clear_last_session() is False


def test_format_age_buckets() -> None:
    assert "秒前" in format_age(30)
    assert "分钟前" in format_age(120)
    assert "小时前" in format_age(7200)
    assert "天前" in format_age(86400 * 3)


def test_snapshot_age_seconds_is_non_negative() -> None:
    snap = ChatSessionSnapshot(
        profile_name="x", provider="anthropic", model="claude-sonnet-4-6",
        history=[Message(role="user", content="hi")],
        saved_at=time.time() - 10.0,
    )
    assert snap.age_seconds >= 9.0
