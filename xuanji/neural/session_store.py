"""CLI chat 会话快照。

把 `Conductor.ctx.history` 序列化成 JSON 落盘到 `data_dir/chat_sessions/last.json`，
重启 CLI 时可询问小宝是否继续上一次的对话。

设计取舍：
- **只存 history，不存 audit / memory**：history 是模型上下文的全部输入；audit/memory 各有自己的持久化路径，混存会乱套。
- **快照随写随保存**：每完成一轮 conductor.send 后立即写入。崩溃也最多丢一句。
- **profile + model 校验**：恢复前比对 profile/model，不一致就警告，避免把
  Anthropic 思维链丢回 OpenAI 端点引发 400。
- **token 估算 + 时间戳**：让恢复对话框能展示"X 分钟前 / N 轮 / ~Y tokens"。

不在范围：多会话管理、tag、检索、命名（M5+ 再说）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from xuanji.config.paths import chat_session_last_path
from xuanji.llm.providers.base import Message
from xuanji.neural.compaction import estimate_tokens


class ChatSessionSnapshot(BaseModel):
    """一份可恢复的对话快照。"""

    version: int = 1
    saved_at: float = Field(default_factory=time.time)
    profile_name: str
    provider: str
    model: str
    history: list[Message]

    @property
    def turn_count(self) -> int:
        """估算"轮数"——以 user 消息为锚。"""
        return sum(1 for m in self.history if m.role == "user")

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.history)

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.saved_at)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def save_last_session(snapshot: ChatSessionSnapshot) -> None:
    """把会话快照写到 last.json（原子）。"""
    _atomic_write_json(
        chat_session_last_path(),
        snapshot.model_dump(mode="json"),
    )


def load_last_session() -> ChatSessionSnapshot | None:
    """读取 last.json。文件不存在或损坏时返回 None。"""
    path = chat_session_last_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ChatSessionSnapshot.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        # 损坏的快照不是致命错误——直接当不存在
        return None


def clear_last_session() -> bool:
    """删除 last.json。返回是否真的删了文件。"""
    path = chat_session_last_path()
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def format_age(seconds: float) -> str:
    """把秒数渲染成"X 分钟前"风格。"""
    if seconds < 60:
        return f"{int(seconds)} 秒前"
    if seconds < 3600:
        return f"{int(seconds / 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds / 3600)} 小时前"
    return f"{int(seconds / 86400)} 天前"


__all__ = [
    "ChatSessionSnapshot",
    "clear_last_session",
    "format_age",
    "load_last_session",
    "save_last_session",
]
