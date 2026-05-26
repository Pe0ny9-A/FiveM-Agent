"""FastAPI app + WebSocket 流式聊天。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from xuanji import __version__
from xuanji.config import OpenAICompatibleProfile
from xuanji.gate.bridge import HITLBridge
from xuanji.gate.policy import VerdictKind
from xuanji.knowledge.models import Source
from xuanji.memory.models import MemoryKind, MemoryScope
from xuanji.server.runtime import ServerRuntime

# ============================================================
# WebSocket HITL bridge：把"待确认"事件推前端，等前端裁决
# ============================================================


class WebSocketHITL(HITLBridge):
    """把 HITL 请求转成 WebSocket 消息，等前端回 confirm 决定。

    协议：
    - server → client: {"type": "hitl_request", "request_id": "...",
                        "tool": "...", "args": {...}, "reason": "..."}
    - client → server: {"type": "hitl_response", "request_id": "...",
                        "approve": true/false}

    超时（默认 60s）当用户拒绝。
    """

    def __init__(self, websocket: WebSocket, *, timeout_sec: float = 60.0) -> None:
        self._ws = websocket
        self._timeout = timeout_sec
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def confirm(
        self,
        *,
        tool: Any,
        args: dict[str, Any],
        reason: str,
    ) -> bool:
        import uuid

        request_id = uuid.uuid4().hex
        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        await self._ws.send_text(
            json.dumps(
                {
                    "type": "hitl_request",
                    "request_id": request_id,
                    "tool": tool.name,
                    "risk": tool.risk.value,
                    "args": args,
                    "reason": reason,
                },
                ensure_ascii=False,
            ),
        )
        try:
            return await asyncio.wait_for(fut, timeout=self._timeout)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(request_id, None)

    def deliver_response(self, request_id: str, approve: bool) -> None:
        fut = self._pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(approve)


# ============================================================
# Request/Response 模型
# ============================================================


class SearchKnowledgeRequest(BaseModel):
    query: str
    namespaces: list[str] | None = None
    k: int = 8
    hybrid: bool = False


class RecallMemoryRequest(BaseModel):
    query: str
    scopes: list[str] | None = None
    kinds: list[str] | None = None
    namespace: str | None = None
    k: int = 8


# ============================================================
# create_app
# ============================================================


def create_app(runtime: ServerRuntime | None = None) -> FastAPI:
    """创建 FastAPI 实例。

    runtime 不传时会创建默认 runtime（与 CLI chat 共享同一份数据）。
    """
    app = FastAPI(
        title="玄玑 · FiveM 智能体",
        version=__version__,
        description="天枢台暴露的 HTTP/WebSocket 服务",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 桌面端 / 本地 web 都需要，反正只在本机跑
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rt = runtime or ServerRuntime()
    app.state.runtime = rt

    # ----------------------------------------------------------------------
    # 静态首页 + 健康检查
    # ----------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        from xuanji.server.web import INDEX_HTML

        return INDEX_HTML

    # ----------------------------------------------------------------------
    # 配置 / Profile
    # ----------------------------------------------------------------------

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        cfg = rt.cfg_store.load()
        active = cfg.get_active()
        return {
            "version": __version__,
            "active_profile": cfg.active_profile,
            "persona_temperature": cfg.persona_temperature.value,
            "assistant_alias": cfg.assistant_alias,
            "user_alias": cfg.user_alias,
            "active": _profile_summary(active) if active else None,
        }

    @app.get("/api/profiles")
    async def profiles() -> dict[str, Any]:
        cfg = rt.cfg_store.load()
        return {
            "active": cfg.active_profile,
            "items": [
                {"name": name, **_profile_summary(p)}
                for name, p in cfg.profiles.items()
            ],
        }

    @app.post("/api/profiles/use/{name}")
    async def use_profile(name: str) -> dict[str, Any]:
        try:
            rt.cfg_store.use_profile(name)
        except KeyError as err:
            raise HTTPException(404, f"profile not found: {name}") from err
        return {"ok": True, "active_profile": name}

    # ----------------------------------------------------------------------
    # 知识库
    # ----------------------------------------------------------------------

    @app.get("/api/knowledge/stats")
    async def knowledge_stats() -> dict[str, Any]:
        return rt.knowledge.stats()

    @app.get("/api/knowledge/sources")
    async def knowledge_sources() -> list[dict[str, Any]]:
        return [_source_summary(s) for s in rt.knowledge.list_sources()]

    @app.post("/api/knowledge/search")
    async def knowledge_search(req: SearchKnowledgeRequest) -> list[dict[str, Any]]:
        if req.hybrid:
            hits = rt.knowledge.hybrid_search(
                req.query, namespaces=req.namespaces, k=req.k,
            )
        else:
            hits = rt.knowledge.search(req.query, namespaces=req.namespaces, k=req.k)
        return [
            {
                "namespace": h.chunk.namespace,
                "source_title": h.chunk.source_title,
                "section": h.chunk.section,
                "text": h.chunk.text,
                "score": h.score,
                "source": h.source,
                "anchor_symbol": h.matched_symbol.name if h.matched_symbol else None,
            }
            for h in hits
        ]

    # ----------------------------------------------------------------------
    # 记忆库
    # ----------------------------------------------------------------------

    @app.get("/api/memory/stats")
    async def memory_stats() -> dict[str, Any]:
        return rt.memory.stats()

    @app.post("/api/memory/recall")
    async def memory_recall(req: RecallMemoryRequest) -> list[dict[str, Any]]:
        scopes = [MemoryScope(s) for s in req.scopes] if req.scopes else None
        kinds = [MemoryKind(k) for k in req.kinds] if req.kinds else None
        ns = req.namespace if req.namespace else rt.project_namespace
        hits = rt.memory.recall(
            req.query, scopes=scopes, kinds=kinds, namespace=ns, k=req.k,
        )
        return [
            {
                "id": m.id,
                "scope": m.scope.value,
                "kind": m.kind.value,
                "namespace": m.namespace,
                "text": m.text,
                "summary": m.summary,
                "importance": m.importance,
                "hits": m.hits,
            }
            for m in hits
        ]

    # ----------------------------------------------------------------------
    # WebSocket 流式聊天
    # ----------------------------------------------------------------------

    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket) -> None:
        await ws.accept()
        cfg = rt.cfg_store.load()
        profile = cfg.get_active()
        if profile is None:
            await ws.send_text(
                json.dumps(
                    {"type": "error", "message": "没有激活的 profile，先 xuanji config add"},
                    ensure_ascii=False,
                ),
            )
            await ws.close()
            return

        hitl = WebSocketHITL(ws)
        conductor = rt.make_conductor(profile=profile, hitl_bridge=hitl)
        await ws.send_text(
            json.dumps(
                {
                    "type": "session_started",
                    "session_id": conductor.ctx.session_id,
                    "model": conductor.ctx.model,
                    "assistant_alias": conductor.ctx.assistant_alias,
                    "user_alias": conductor.ctx.user_alias,
                },
                ensure_ascii=False,
            ),
        )

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "hitl_response":
                    hitl.deliver_response(
                        msg["request_id"], bool(msg.get("approve", False)),
                    )
                    continue
                if msg.get("type") != "user_input":
                    await ws.send_text(
                        json.dumps(
                            {"type": "error", "message": f"unknown msg type: {msg.get('type')}"},
                        ),
                    )
                    continue
                user_text = (msg.get("text") or "").strip()
                if not user_text:
                    continue
                # 流式跑一轮
                async for delta in conductor.send(user_text):
                    payload = _delta_to_json(delta)
                    if payload is not None:
                        await ws.send_text(
                            json.dumps(payload, ensure_ascii=False),
                        )
        except WebSocketDisconnect:
            return
        except Exception as e:
            await ws.send_text(
                json.dumps(
                    {"type": "error", "message": f"{type(e).__name__}: {e}"},
                    ensure_ascii=False,
                ),
            )

    return app


# ============================================================
# 内部小函数
# ============================================================


def _profile_summary(profile: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": profile.label,
        "kind": profile.kind.value,
        "default_model": profile.default_model,
    }
    if isinstance(profile, OpenAICompatibleProfile):
        out["base_url"] = str(profile.base_url)
    return out


def _source_summary(s: Source) -> dict[str, Any]:
    return {
        "namespace": s.namespace,
        "title": s.title,
        "url": s.url,
        "version": s.version,
    }


def _delta_to_json(delta: Any) -> dict[str, Any] | None:
    """把 Delta 序列化成 JSON 友好 dict。

    返回 None 表示这条 delta 不需要转发（如纯 start/end 边界）。
    """
    t = delta.type
    if t == "text_delta" and delta.text:
        return {"type": "text_delta", "text": delta.text}
    if t == "tool_run_started":
        return {
            "type": "tool_run_started",
            "tool_name": delta.tool_name,
            "tool_call_id": delta.tool_call_id,
            "args": delta.args_final,
        }
    if t == "tool_run_blocked":
        return {
            "type": "tool_run_blocked",
            "tool_name": delta.tool_name,
            "reason": delta.tool_run_reason,
        }
    if t == "tool_run_done":
        return {
            "type": "tool_run_done",
            "tool_name": delta.tool_name,
            "ok": delta.tool_run_ok,
            "duration_ms": delta.tool_run_duration_ms,
            "error": delta.tool_run_error,
        }
    if t == "message_done":
        usage = delta.usage.model_dump() if delta.usage else None
        return {
            "type": "message_done",
            "stop_reason": delta.stop_reason,
            "usage": usage,
        }
    return None


# 重要：让 mypy 看见 VerdictKind 的引用（导入但未直接用，留作未来扩展）
_ = VerdictKind
