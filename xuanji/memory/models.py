"""记忆数据模型。"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryKind(StrEnum):
    EPISODIC = "episodic"  # 时间序列上的事件，如"小宝在 X 时说了 Y"
    SEMANTIC = "semantic"  # 事实卡片，如"项目用 QBox 而非 QBCore"
    PROCEDURAL = "procedural"  # 解题套路、工作流


class MemoryScope(StrEnum):
    WORKING = "working"  # 当前进程，重启即失（M2 用进程内 dict）
    SESSION = "session"  # 单次 chat 会话内
    PROJECT = "project"  # 一个项目目录共享
    USER = "user"  # 跨项目用户偏好（M3+ 启用）


class Memory(BaseModel):
    """单条记忆。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: MemoryScope
    kind: MemoryKind
    namespace: str = "default"  # session_id / project_id / user_id
    text: str  # 记忆主体（中文/英文都行）
    summary: str | None = None  # 可选的一句话摘要
    importance: float = 0.5  # 0~1，写入时由调用方评估
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    hits: int = 0  # 被召回次数

    def display(self) -> str:
        """便利方法：返回适合塞 system prompt 的紧凑形式。"""
        head = self.summary or self.text
        if len(head) > 200:
            head = head[:200] + "…"
        return head
