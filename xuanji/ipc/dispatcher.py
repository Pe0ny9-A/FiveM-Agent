"""RPC 方法集合 + 分发器。

每个方法签名都是 async（params: dict） -> dict。
分发器把方法名映射到 handler，捕异常翻成 RpcError。

公开方法（VS Code 插件用得到的）：
- info                              当前激活配置 + 项目身份卡
- project.detect                    跑 detector
- project.analyze                   静态分析一个 resource
- project.scaffold                  从预设生成 resource
- presets.list / drafts / show / accept / reject / remove
- knowledge.search / symbol
- memory.recall / write / list / forget
- skill.list / search / show
- tools.list / call
- chat.start / send / cancel / hitl_response / close / list  （流式，需要 notifier）
- ensemble.council                  议会式群英会（流式，需要 notifier）

chat.* 与 ensemble.* 必须由 build_dispatcher_with_notifier 构造，
普通 build_dispatcher 不带流式能力（CLI 单测里用足够）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from xuanji.capability.registry import ToolRegistry
from xuanji.capability.tool import ToolCtx
from xuanji.fivem import detect_fivem_context, summarize_for_prompt
from xuanji.fivem.analyzer import analyze_resource
from xuanji.fivem.scaffold import ScaffoldEngine
from xuanji.gate.interceptor import GateRefusal
from xuanji.ipc.errors import (
    GATE_REFUSAL,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    NOT_INITIALIZED,
    TOOL_ERROR,
    RpcError,
)
from xuanji.knowledge import SqliteKnowledgeStore
from xuanji.memory.models import MemoryKind, MemoryScope
from xuanji.memory.store.sqlite import SqliteMemoryStore
from xuanji.tools.skills import SKILLS_NAMESPACE

RpcMethod = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _resolve_path(raw: str | None, project_root: Path) -> Path:
    """解析相对路径——空时取 project_root。"""
    if not raw:
        return project_root
    p = Path(raw)
    if not p.is_absolute():
        p = project_root / p
    return p


def _require(params: dict[str, Any], key: str) -> Any:
    if key not in params:
        raise RpcError(INVALID_PARAMS, f"缺少参数：{key}")
    return params[key]


def build_dispatcher(
    *,
    knowledge: SqliteKnowledgeStore,
    memory: SqliteMemoryStore,
    scaffold: ScaffoldEngine,
    project_root: Path,
    project_namespace: str,
    cfg_store_factory: Callable[[], Any],
    tool_registry_factory: Callable[[], ToolRegistry],
) -> dict[str, RpcMethod]:
    """构造方法表。所有依赖通过参数注入便于单测。"""

    async def info(params: dict[str, Any]) -> dict[str, Any]:
        from xuanji.config import OpenAICompatibleProfile
        from xuanji.config.profiles import OFFICIAL_BASE_URLS

        cfg = cfg_store_factory().load()
        active = cfg.get_active()
        active_block: dict[str, Any] | None = None
        if active is not None:
            base_url = (
                str(active.base_url)
                if isinstance(active, OpenAICompatibleProfile)
                else OFFICIAL_BASE_URLS.get(active.kind, "")
            )
            active_block = {
                "label": active.label,
                "kind": active.kind.value,
                "default_model": active.default_model,
                "base_url": base_url,
            }
        ctx = detect_fivem_context(project_root)
        return {
            "version": _xuanji_version(),
            "active_profile": cfg.active_profile,
            "assistant_alias": cfg.assistant_alias,
            "user_alias": cfg.user_alias,
            "active": active_block,
            "project": {
                "root": str(project_root),
                "namespace": project_namespace,
                "is_fivem_resource": ctx.is_fivem_resource,
                "framework": ctx.framework.value,
                "framework_confidence": round(ctx.framework_confidence, 2),
                "inventory": ctx.inventory.value,
                "target": ctx.target.value,
                "summary": summarize_for_prompt(ctx),
            },
        }

    # ---------------- project ----------------

    async def project_detect(params: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_path(params.get("path"), project_root)
        if not path.exists():
            raise RpcError(INVALID_PARAMS, f"路径不存在：{path}")
        ctx = detect_fivem_context(path)
        return {
            "is_fivem_resource": ctx.is_fivem_resource,
            "framework": ctx.framework.value,
            "framework_confidence": round(ctx.framework_confidence, 2),
            "inventory": ctx.inventory.value,
            "target": ctx.target.value,
            "manifest": (
                ctx.manifest.model_dump(exclude={"raw"}) if ctx.manifest else None
            ),
            "sub_resources": [str(p) for p in ctx.detected_resources[:30]],
            "notes": ctx.notes,
            "summary": summarize_for_prompt(ctx),
        }

    async def project_analyze(params: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_path(_require(params, "path"), project_root)
        if not path.exists():
            raise RpcError(INVALID_PARAMS, f"路径不存在：{path}")
        analysis = analyze_resource(path)
        return {
            "resource_path": str(analysis.resource_path),
            "is_fivem_resource": analysis.context.is_fivem_resource,
            "framework": analysis.context.framework.value,
            "inventory": analysis.context.inventory.value,
            "target": analysis.context.target.value,
            "files_scanned": analysis.files_scanned,
            "exports": analysis.exports,
            "events_registered": analysis.events_registered,
            "events_triggered": analysis.events_triggered,
            "callbacks": analysis.callbacks,
            "top_api_calls": analysis.framework_api_calls,
            "notes": analysis.notes,
        }

    async def project_scaffold(params: dict[str, Any]) -> dict[str, Any]:
        preset = _require(params, "preset")
        name = _require(params, "name")
        target_raw = params.get("target") or "."
        target_dir = _resolve_path(target_raw, project_root) / name
        try:
            result = scaffold.generate(
                preset,
                target_dir,
                resource_name=name,
                author=params.get("author", ""),
                description=params.get("description", ""),
                version=params.get("version", "1.0.0"),
                overwrite=bool(params.get("overwrite", False)),
            )
        except KeyError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e
        return {
            "target_dir": str(result.target_dir),
            "preset": result.preset,
            "files_written": [str(p) for p in result.files_written],
            "files_skipped": [str(p) for p in result.files_skipped],
        }

    # ---------------- presets ----------------

    async def presets_list(params: dict[str, Any]) -> dict[str, Any]:
        return {"items": scaffold.list_presets()}

    async def presets_drafts(params: dict[str, Any]) -> dict[str, Any]:
        items = []
        for d in scaffold.list_drafts():
            items.append(
                {
                    "key": d.key,
                    "label": d.label,
                    "description": d.description,
                    "framework": d.framework.value,
                    "inventory": d.inventory.value,
                    "target": d.target.value,
                    "files_count": len(d.files),
                    "metadata": d.metadata,
                },
            )
        return {"items": items}

    async def presets_show(params: dict[str, Any]) -> dict[str, Any]:
        key = _require(params, "key")
        # 先看草案
        draft = scaffold.get_draft(key)
        if draft is None:
            try:
                draft = scaffold.get(key)
            except KeyError as e:
                raise RpcError(INVALID_PARAMS, str(e)) from e
        return {
            "key": draft.key,
            "label": draft.label,
            "description": draft.description,
            "framework": draft.framework.value,
            "inventory": draft.inventory.value,
            "target": draft.target.value,
            "source": draft.source,
            "files": [
                {"path": f.path, "content": f.content} for f in draft.files
            ],
            "metadata": draft.metadata,
        }

    async def presets_accept(params: dict[str, Any]) -> dict[str, Any]:
        key = _require(params, "key")
        try:
            target = scaffold.accept_draft(key)
        except FileNotFoundError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e
        return {"path": str(target)}

    async def presets_reject(params: dict[str, Any]) -> dict[str, Any]:
        key = _require(params, "key")
        ok = scaffold.reject_draft(key)
        return {"removed": ok}

    async def presets_remove(params: dict[str, Any]) -> dict[str, Any]:
        key = _require(params, "key")
        ok = scaffold.remove_user_preset(key)
        return {"removed": ok}

    # ---------------- knowledge ----------------

    async def knowledge_search(params: dict[str, Any]) -> dict[str, Any]:
        query = _require(params, "query")
        k = int(params.get("k", 8))
        namespaces = params.get("namespaces")
        hybrid = bool(params.get("hybrid", False))
        if hybrid:
            hits = knowledge.hybrid_search(query, namespaces=namespaces, k=k)
        else:
            hits = knowledge.search(query, namespaces=namespaces, k=k)
        return {
            "items": [
                {
                    "namespace": h.chunk.namespace,
                    "source_title": h.chunk.source_title,
                    "section": h.chunk.section,
                    "text": h.chunk.text,
                    "score": h.score,
                    "source": h.source,
                    "anchor_symbol": (
                        h.matched_symbol.name if h.matched_symbol else None
                    ),
                }
                for h in hits
            ],
        }

    async def knowledge_symbol(params: dict[str, Any]) -> dict[str, Any]:
        name = _require(params, "name")
        namespaces = params.get("namespaces")
        syms = knowledge.lookup_symbol(name, namespaces=namespaces)
        return {
            "items": [s.model_dump() for s in syms],
        }

    async def knowledge_symbols_by_prefix(
        params: dict[str, Any],
    ) -> dict[str, Any]:
        prefix = str(params.get("prefix", "")).strip()
        if not prefix:
            return {"items": []}
        namespaces = params.get("namespaces")
        kinds = params.get("kinds")
        limit = int(params.get("limit", 30))
        syms = knowledge.search_symbols_by_prefix(
            prefix,
            namespaces=namespaces,
            kinds=kinds,
            limit=limit,
        )
        return {
            "items": [s.model_dump() for s in syms],
        }

    # ---------------- memory ----------------

    async def memory_recall(params: dict[str, Any]) -> dict[str, Any]:
        query = _require(params, "query")
        k = int(params.get("k", 8))
        ns = params.get("namespace") or project_namespace
        kinds_in = params.get("kinds") or []
        kinds = [MemoryKind(s) for s in kinds_in] if kinds_in else None
        scopes_in = params.get("scopes") or []
        scopes = [MemoryScope(s) for s in scopes_in] if scopes_in else None
        hits = memory.recall(query, scopes=scopes, kinds=kinds, namespace=ns, k=k)
        return {
            "items": [
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
            ],
        }

    async def memory_write(params: dict[str, Any]) -> dict[str, Any]:
        from xuanji.memory.models import Memory

        text = _require(params, "text")
        kind_str = params.get("kind", "semantic")
        scope_str = params.get("scope", "project")
        ns = params.get("namespace") or project_namespace
        importance = max(0.0, min(1.0, float(params.get("importance", 0.6))))
        m = Memory(
            scope=MemoryScope(scope_str),
            kind=MemoryKind(kind_str),
            namespace=ns,
            text=text,
            summary=params.get("summary"),
            importance=importance,
            tags=list(params.get("tags") or []),
        )
        saved = memory.write(m)
        return {
            "id": saved.id,
            "scope": saved.scope.value,
            "kind": saved.kind.value,
            "namespace": saved.namespace,
            "importance": saved.importance,
        }

    async def memory_list(params: dict[str, Any]) -> dict[str, Any]:
        ns = params.get("namespace") or project_namespace
        limit = int(params.get("limit", 50))
        items = memory.list_by_namespace(ns, limit=limit)
        return {
            "items": [
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
                for m in items
            ],
        }

    async def memory_forget(params: dict[str, Any]) -> dict[str, Any]:
        ids = params.get("ids")
        ns = params.get("namespace")
        scope_str = params.get("scope")
        scope = MemoryScope(scope_str) if scope_str else None
        n = memory.forget(ids=ids, namespace=ns, scope=scope)
        return {"removed": n}

    # ---------------- skill ----------------

    async def skill_list(params: dict[str, Any]) -> dict[str, Any]:
        ns = params.get("namespace") or SKILLS_NAMESPACE
        limit = int(params.get("limit", 100))
        items = memory.list_by_namespace(
            ns, kinds=[MemoryKind.PROCEDURAL], limit=limit,
        )
        return {
            "items": [
                {
                    "id": m.id,
                    "summary": m.summary or m.text[:100],
                    "tags": m.tags,
                    "tools_used": m.metadata.get("tools_used", []),
                    "importance": m.importance,
                    "hits": m.hits,
                }
                for m in items
            ],
        }

    async def skill_search(params: dict[str, Any]) -> dict[str, Any]:
        query = _require(params, "query")
        ns = params.get("namespace") or SKILLS_NAMESPACE
        k = int(params.get("k", 5))
        hits = memory.recall(
            query, kinds=[MemoryKind.PROCEDURAL], namespace=ns, k=k,
        )
        return {
            "items": [
                {
                    "id": m.id,
                    "summary": m.summary or m.text[:100],
                    "tags": m.tags,
                    "importance": m.importance,
                    "hits": m.hits,
                }
                for m in hits
            ],
        }

    async def skill_show(params: dict[str, Any]) -> dict[str, Any]:
        key = _require(params, "id")
        m = memory.get(key)
        if m is None:
            for cand in memory.list_by_namespace(
                SKILLS_NAMESPACE, kinds=[MemoryKind.PROCEDURAL], limit=200,
            ):
                if cand.id.startswith(key):
                    m = cand
                    break
        if m is None or m.kind != MemoryKind.PROCEDURAL:
            raise RpcError(INVALID_PARAMS, f"找不到技能：{key}")
        return {
            "id": m.id,
            "summary": m.summary,
            "text": m.text,
            "tags": m.tags,
            "tools_used": m.metadata.get("tools_used", []),
            "namespace": m.namespace,
        }

    # ---------------- tools ----------------

    async def tools_list(params: dict[str, Any]) -> dict[str, Any]:
        registry = tool_registry_factory()
        return {
            "items": [
                {
                    "name": t.name,
                    "risk": t.risk.value,
                    "description": (t.description or "").strip()[:200],
                }
                for t in registry.all()
            ],
        }

    async def tools_call(params: dict[str, Any]) -> dict[str, Any]:
        """直接调一个工具（VS Code 插件没必要走整个 chat loop 时用）。"""
        from xuanji.body.sandbox import InProcSandbox
        from xuanji.gate.bridge import NoOpHITLBridge
        from xuanji.gate.interceptor import GateInterceptor

        registry = tool_registry_factory()
        name = _require(params, "name")
        args = params.get("args", {}) or {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "args 必须是 object")

        tool = registry.get(name)
        if tool is None:
            raise RpcError(METHOD_NOT_FOUND, f"工具不存在：{name}")

        ctx = ToolCtx(
            project_root=project_root,
            session_id="ipc",
            trace_id="ipc",
        )
        gate = GateInterceptor(bridge=NoOpHITLBridge())
        try:
            await gate.check(tool, args, ctx)
        except GateRefusal as e:
            raise RpcError(GATE_REFUSAL, e.verdict.reason) from e

        sandbox = InProcSandbox()
        result = await sandbox.run(tool, args, ctx)
        if not result.ok:
            raise RpcError(TOOL_ERROR, result.error or "tool failed")
        return {
            "ok": True,
            "output": result.output,
            "duration_ms": result.duration_ms,
            "extra": result.extra,
        }

    return {
        "info": info,
        "project.detect": project_detect,
        "project.analyze": project_analyze,
        "project.scaffold": project_scaffold,
        "presets.list": presets_list,
        "presets.drafts": presets_drafts,
        "presets.show": presets_show,
        "presets.accept": presets_accept,
        "presets.reject": presets_reject,
        "presets.remove": presets_remove,
        "knowledge.search": knowledge_search,
        "knowledge.symbol": knowledge_symbol,
        "knowledge.symbols_by_prefix": knowledge_symbols_by_prefix,
        "memory.recall": memory_recall,
        "memory.write": memory_write,
        "memory.list": memory_list,
        "memory.forget": memory_forget,
        "skill.list": skill_list,
        "skill.search": skill_search,
        "skill.show": skill_show,
        "tools.list": tools_list,
        "tools.call": tools_call,
    }


def _xuanji_version() -> str:
    from xuanji import __version__

    return __version__


# ============================================================
# 带 notifier 的方法表（chat.* / ensemble.*）
# ============================================================


def build_streaming_methods(
    *,
    runtime: Any,
    notifier: Any,
) -> dict[str, RpcMethod]:
    """构造需要 notifier 的流式方法（chat.* / ensemble.*）。

    单独拆出来是为了让 build_dispatcher 单测不依赖 ServerRuntime。
    """
    from xuanji.ipc.chat_manager import IpcChatManager

    chat = IpcChatManager(runtime=runtime, notifier=notifier)

    async def chat_start(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.start(
            profile_name=params.get("profile"),
            mode=params.get("mode"),
        )

    async def chat_send(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.send(
            session_id=_require(params, "session_id"),
            text=_require(params, "text"),
        )

    async def chat_cancel(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.cancel(session_id=_require(params, "session_id"))

    async def chat_hitl_response(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.hitl_response(
            session_id=_require(params, "session_id"),
            request_id=_require(params, "request_id"),
            approve=bool(params.get("approve", False)),
        )

    async def chat_close(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.close(session_id=_require(params, "session_id"))

    async def chat_list(params: dict[str, Any]) -> dict[str, Any]:
        return await chat.list_sessions()

    # ---------------- ensemble.* ----------------

    async def ensemble_council(params: dict[str, Any]) -> dict[str, Any]:
        """跑一次议会，进度通过 notifier 推送 ensemble.* 通知，最终返回 verdict。"""
        from xuanji.ensemble.council import (
            CouncilEngine,
            CouncilorSpec,
            CouncilSpec,
            JudgeSpec,
        )

        question = _require(params, "question")
        councilors_raw = params.get("councilors") or []
        if not isinstance(councilors_raw, list) or len(councilors_raw) < 2:
            raise RpcError(INVALID_PARAMS, "councilors 至少 2 个")

        councilors: list[CouncilorSpec] = []
        for raw in councilors_raw:
            if not isinstance(raw, dict):
                raise RpcError(INVALID_PARAMS, "councilor 必须是 object")
            try:
                councilors.append(CouncilorSpec(**raw))
            except (TypeError, ValueError) as e:
                raise RpcError(INVALID_PARAMS, f"councilor 参数非法：{e}") from e

        judge_raw = params.get("judge") or {}
        try:
            judge_spec = JudgeSpec(**judge_raw)
        except (TypeError, ValueError) as e:
            raise RpcError(INVALID_PARAMS, f"judge 参数非法：{e}") from e

        deadline = float(params.get("deadline_seconds", 120.0))

        cfg = runtime.cfg_store.load()
        if not cfg.profiles:
            raise RpcError(NOT_INITIALIZED, "没有配置任何 profile")
        active = cfg.get_active()
        if active is None:
            raise RpcError(NOT_INITIALIZED, "没有激活的 profile")

        request_id = params.get("request_id") or ""

        async def on_progress(event: str, payload: dict[str, Any]) -> None:
            await notifier.notify(
                f"ensemble.{event}",
                {"request_id": request_id, **payload},
            )

        engine = CouncilEngine(
            profiles=cfg.profiles,
            default_profile=active,
            active_profile_name=cfg.active_profile,
            master_registry=runtime.build_registry(),
            project_root=runtime.project_root,
            memory=runtime.memory,
        )
        spec = CouncilSpec(
            question=question,
            councilors=councilors,
            judge=judge_spec,
            deadline_seconds=deadline,
        )
        outcome = await engine.convene(spec, on_progress=on_progress)
        return {
            "request_id": request_id,
            "question": outcome.question,
            "elapsed_seconds": outcome.elapsed_seconds,
            "memory_id": outcome.memory_id,
            "councilors": [
                {
                    "role": o.role,
                    "profile_name": o.profile_name,
                    "model": o.model,
                    "final_text": o.final_text,
                    "iterations": o.iterations,
                    "tool_calls_made": o.tool_calls_made,
                    "truncated": o.truncated,
                    "error": o.error,
                }
                for o in outcome.councilors
            ],
            "verdict": outcome.verdict.model_dump(),
        }

    return {
        "chat.start": chat_start,
        "chat.send": chat_send,
        "chat.cancel": chat_cancel,
        "chat.hitl_response": chat_hitl_response,
        "chat.close": chat_close,
        "chat.list": chat_list,
        "ensemble.council": ensemble_council,
    }


def build_full_dispatcher(
    *,
    runtime: Any,
    notifier: Any,
) -> dict[str, RpcMethod]:
    """完整方法表（含流式）——VS Code 插件 1.0 起用这个。"""
    from xuanji.config import ConfigStore, hooks_dir, skills_dir
    from xuanji.ipc.config_methods import build_config_methods

    methods = build_dispatcher(
        knowledge=runtime.knowledge,
        memory=runtime.memory,
        scaffold=runtime.scaffold_engine,
        project_root=runtime.project_root,
        project_namespace=runtime.project_namespace,
        cfg_store_factory=ConfigStore,
        tool_registry_factory=runtime.build_registry,
    )
    methods.update(build_streaming_methods(runtime=runtime, notifier=notifier))
    methods.update(
        build_config_methods(
            cfg_store_factory=ConfigStore,
            hooks_dir=hooks_dir(),
            skills_dir=skills_dir(),
        ),
    )
    return methods


# 异步分发（暴露给 server.py 用）
async def dispatch(
    methods: dict[str, RpcMethod],
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    handler = methods.get(method)
    if handler is None:
        raise RpcError(METHOD_NOT_FOUND, f"未知方法：{method}")
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params 必须是 object")
    try:
        return await handler(params)
    except RpcError:
        raise
    except (KeyError, ValueError, TypeError) as e:
        raise RpcError(INVALID_PARAMS, f"{type(e).__name__}: {e}") from e
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise RpcError(
            INTERNAL_ERROR, f"{type(e).__name__}: {e}",
        ) from e


__all__ = [
    "NOT_INITIALIZED",
    "RpcMethod",
    "build_dispatcher",
    "build_full_dispatcher",
    "build_streaming_methods",
    "dispatch",
]
