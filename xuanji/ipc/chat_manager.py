"""IPC 多会话聊天调度器。

职责：
- 给每个 session_id 维护一个 Conductor + 一个后台跑 send 的 task
- 把 Delta 翻译成 chat.* notification 推给客户端（与 Web WS 协议同源）
- HITL 请求挂 future，等客户端 chat.hitl_response 回来 set_result
- chat.cancel 时取消 task；session 结束 / 客户端断时全部清理

线程模型：单事件循环。所有方法 async 调用，互相之间靠 Lock 保护字典。
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from xuanji.gate.bridge import HITLBridge
from xuanji.ipc.errors import INVALID_PARAMS, NOT_INITIALIZED, RpcError
from xuanji.ipc.notifier import Notifier
from xuanji.neural.conductor import Conductor
from xuanji.server.runtime import ServerRuntime


class _IpcHITLBridge(HITLBridge):
    """每个会话一个：把 HITL 请求转成 chat.hitl_request 通知，等回包。"""

    def __init__(
        self,
        *,
        session_id: str,
        notifier: Notifier,
        timeout_sec: float = 120.0,
    ) -> None:
        self._session_id = session_id
        self._notifier = notifier
        self._timeout = timeout_sec
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def confirm(
        self,
        *,
        tool: Any,
        args: dict[str, Any],
        reason: str,
    ) -> bool:
        request_id = uuid.uuid4().hex
        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        await self._notifier.notify(
            "chat.hitl_request",
            {
                "session_id": self._session_id,
                "request_id": request_id,
                "tool": tool.name,
                "risk": tool.risk.value,
                "args": args,
                "reason": reason,
            },
        )
        try:
            return await asyncio.wait_for(fut, timeout=self._timeout)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(request_id, None)

    def deliver(self, request_id: str, approve: bool) -> bool:
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approve)
        return True


class _Session:
    def __init__(
        self,
        *,
        session_id: str,
        conductor: Conductor,
        bridge: _IpcHITLBridge,
    ) -> None:
        self.id = session_id
        self.conductor = conductor
        self.bridge = bridge
        self.task: asyncio.Task[None] | None = None
        self.created_at = asyncio.get_event_loop().time()


class IpcChatManager:
    """IPC 流式聊天会话管理。

    暴露给 dispatcher 的四个动作：
    - start(profile_name?)        新建 session，返回 session_id
    - send(session_id, text)       触发 conductor.send 并 stream 通知（不阻塞 RPC）
    - cancel(session_id)           取消正在跑的 send
    - hitl_response(session_id, request_id, approve)
    """

    def __init__(
        self,
        *,
        runtime: ServerRuntime,
        notifier: Notifier,
        registry_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._rt = runtime
        self._notifier = notifier
        self._registry_factory = registry_factory or runtime.build_registry
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        profile_name: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        cfg = self._rt.cfg_store.load()
        if profile_name:
            try:
                profile = cfg.profiles[profile_name]
            except KeyError as e:
                raise RpcError(
                    INVALID_PARAMS, f"profile 不存在：{profile_name}",
                ) from e
        else:
            active = cfg.get_active()
            if active is None:
                raise RpcError(NOT_INITIALIZED, "没有激活的 profile")
            profile = active

        session_id = uuid.uuid4().hex
        bridge = _IpcHITLBridge(session_id=session_id, notifier=self._notifier)
        # 复用 ServerRuntime.make_conductor，保证 hooks/compaction/memory 等
        # 一切配置都跟 CLI / FastAPI 一致
        conductor = self._rt.make_conductor(
            profile=profile,
            hitl_bridge=bridge,
            registry=self._registry_factory(),
        )
        session = _Session(
            session_id=session_id, conductor=conductor, bridge=bridge,
        )
        async with self._lock:
            self._sessions[session_id] = session
        return {
            "session_id": session_id,
            "model": conductor.ctx.model,
            "provider": conductor.ctx.provider.name,
            "assistant_alias": conductor.ctx.assistant_alias,
            "user_alias": conductor.ctx.user_alias,
            "mode": conductor.ctx.mode.value,
            "profile_name": profile_name or cfg.active_profile,
        }

    async def send(self, *, session_id: str, text: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.task is not None and not session.task.done():
            raise RpcError(
                INVALID_PARAMS,
                "上一轮还没结束，先 chat.cancel 或等完成",
            )
        text = (text or "").strip()
        if not text:
            raise RpcError(INVALID_PARAMS, "text 为空")

        async def _run() -> None:
            try:
                async for delta in session.conductor.send(text):
                    payload = _delta_to_payload(session_id, delta)
                    if payload is not None:
                        method, params = payload
                        await self._notifier.notify(method, params)
                # 一轮跑完了，发个 turn_done 让前端知道可以重新允许发送
                await self._notifier.notify(
                    "chat.turn_done",
                    {"session_id": session_id},
                )
            except asyncio.CancelledError:
                await self._notifier.notify(
                    "chat.turn_cancelled",
                    {"session_id": session_id},
                )
                raise
            except Exception as e:
                await self._notifier.notify(
                    "chat.error",
                    {
                        "session_id": session_id,
                        "message": f"{type(e).__name__}: {e}",
                    },
                )

        session.task = asyncio.create_task(_run(), name=f"chat-{session_id[:8]}")
        return {"ok": True, "session_id": session_id}

    async def cancel(self, *, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.task is None or session.task.done():
            return {"ok": True, "cancelled": False}
        session.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await session.task
        return {"ok": True, "cancelled": True}

    async def hitl_response(
        self,
        *,
        session_id: str,
        request_id: str,
        approve: bool,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        ok = session.bridge.deliver(request_id, approve)
        return {"ok": ok}

    async def close(self, *, session_id: str) -> dict[str, Any]:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return {"ok": True, "closed": False}
        if session.task is not None and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await session.task
        return {"ok": True, "closed": True}

    async def list_sessions(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "session_id": s.id,
                    "model": s.conductor.ctx.model,
                    "provider": s.conductor.ctx.provider.name,
                    "running": s.task is not None and not s.task.done(),
                }
                for s in self._sessions.values()
            ],
        }

    def _get(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise RpcError(INVALID_PARAMS, f"session 不存在：{session_id}")
        return session


def _delta_to_payload(
    session_id: str,
    delta: Any,
) -> tuple[str, dict[str, Any]] | None:
    """Delta → (notification_method, params)。

    与 FastAPI WebSocket 协议同源——event 类型重命名加 chat. 前缀。
    返回 None 表示这条 delta 不需要推送（如 text_start / text_end 边界）。
    """
    t = delta.type
    if t == "text_delta" and delta.text:
        return "chat.text_delta", {
            "session_id": session_id,
            "text": delta.text,
        }
    if t == "thinking_delta" and delta.text:
        return "chat.thinking_delta", {
            "session_id": session_id,
            "text": delta.text,
        }
    if t == "tool_run_started":
        return "chat.tool_run_started", {
            "session_id": session_id,
            "tool_name": delta.tool_name,
            "tool_call_id": delta.tool_call_id,
            "args": delta.args_final,
        }
    if t == "tool_run_blocked":
        return "chat.tool_run_blocked", {
            "session_id": session_id,
            "tool_name": delta.tool_name,
            "reason": delta.tool_run_reason,
        }
    if t == "tool_run_done":
        return "chat.tool_run_done", {
            "session_id": session_id,
            "tool_name": delta.tool_name,
            "ok": delta.tool_run_ok,
            "duration_ms": delta.tool_run_duration_ms,
            "error": delta.tool_run_error,
        }
    if t == "message_done":
        usage = delta.usage.model_dump() if delta.usage else None
        return "chat.message_done", {
            "session_id": session_id,
            "stop_reason": delta.stop_reason,
            "usage": usage,
        }
    return None


__all__ = ["IpcChatManager"]
