"""天枢台 · 唯一执行调度中枢。

M0 雏形职责（线性版）：
- 持有当前会话上下文（messages + persona mode/temperature + provider/model）
- send() 方法接收用户输入 → 合成 system prompt → 委派给 Provider 流式输出
- 所有事件落到 Audit（M0 用内存日志，M2 接 SQLite）

M1+ 演进：
- Plan: 把任务拆成 DAG 节点（ToolCall / AgentCall / Branch）
- Gate: 在 dispatch 路径上插入横切中间件
- Capability: 注入工具与能力包
- Rollback: 基于 Audit 回放
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xuanji.neural.audit import AuditEvent, AuditLog

if TYPE_CHECKING:
    from xuanji.neural.conductor import Conductor, SessionCtx

__all__ = ["AuditEvent", "AuditLog", "Conductor", "SessionCtx"]


def __getattr__(name: str) -> Any:
    if name in {"Conductor", "SessionCtx"}:
        from xuanji.neural import conductor as _conductor
        return getattr(_conductor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
