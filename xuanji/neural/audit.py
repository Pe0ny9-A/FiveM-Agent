"""审计日志。M0 用内存版，M2 接 SQLite。"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "session_start",
    "user_input",
    "model_request",
    "delta_text",
    "delta_tool_call",
    "model_done",
    "error",
]


class AuditEvent(BaseModel):
    """单条审计事件。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str
    type: EventType
    ts: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    """append-only 内存日志。M2 替换为 SQLite 实现，接口保持不变。"""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self._events.append(event)

    def by_trace(self, trace_id: str) -> Iterator[AuditEvent]:
        return (e for e in self._events if e.trace_id == trace_id)

    def all(self) -> list[AuditEvent]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
