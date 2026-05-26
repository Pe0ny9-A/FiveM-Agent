"""IPC 子系统单测：framing / dispatcher / server 主循环。"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest

from xuanji.capability.registry import ToolRegistry
from xuanji.config import (
    ConfigStore,
    DeepSeekProfile,
)
from xuanji.fivem.scaffold import ScaffoldEngine
from xuanji.ipc.dispatcher import build_dispatcher, dispatch
from xuanji.ipc.errors import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    RpcError,
)
from xuanji.ipc.framing import (
    read_message_sync,
    write_message_sync,
)
from xuanji.ipc.server import run_stdio_server
from xuanji.knowledge import SqliteKnowledgeStore
from xuanji.memory.store.sqlite import SqliteMemoryStore

# ---------- framing ----------


def test_framing_roundtrip() -> None:
    buf = io.BytesIO()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": 1}}
    write_message_sync(buf, payload)
    buf.seek(0)
    parsed = read_message_sync(buf)
    assert parsed == payload


def test_framing_handles_unicode() -> None:
    buf = io.BytesIO()
    msg = {"jsonrpc": "2.0", "id": 2, "result": {"text": "玄玑·北斗第三星"}}
    write_message_sync(buf, msg)
    buf.seek(0)
    out = read_message_sync(buf)
    assert out is not None
    assert out["result"]["text"] == "玄玑·北斗第三星"


def test_framing_eof_returns_none() -> None:
    assert read_message_sync(io.BytesIO()) is None


def test_framing_missing_content_length_raises() -> None:
    buf = io.BytesIO(b"\r\n\r\n{}")
    with pytest.raises(ValueError, match="Content-Length"):
        read_message_sync(buf)


def test_framing_oversized_content_length_raises() -> None:
    huge = 17 * 1024 * 1024
    buf = io.BytesIO(f"Content-Length: {huge}\r\n\r\n".encode())
    with pytest.raises(ValueError, match="越界"):
        read_message_sync(buf)


def test_framing_truncated_body_raises() -> None:
    buf = io.BytesIO(b"Content-Length: 100\r\n\r\nshort")
    with pytest.raises(ValueError, match="不完整"):
        read_message_sync(buf)


# ---------- dispatcher ----------


@pytest.fixture
def runtime_methods(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> dict[str, Any]:
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "cfg"))

    cfg_path = tmp_path / "cfg" / "config.json"
    cfg = ConfigStore(path=cfg_path)
    cfg.upsert_profile(
        "test_ds",
        DeepSeekProfile(label="test", api_key="sk-test-placeholder", default_model="ds"),
        activate=True,
    )

    knowledge = SqliteKnowledgeStore(tmp_path / "data" / "knowledge.db")
    memory = SqliteMemoryStore(tmp_path / "data" / "memory.db")
    scaffold = ScaffoldEngine(
        user_presets_dir=tmp_path / "presets",
        drafts_dir=tmp_path / "drafts",
    )

    methods = build_dispatcher(
        knowledge=knowledge,
        memory=memory,
        scaffold=scaffold,
        project_root=tmp_path,
        project_namespace="testproj",
        cfg_store_factory=lambda: ConfigStore(path=cfg_path),
        tool_registry_factory=ToolRegistry,
    )
    return {
        "methods": methods,
        "knowledge": knowledge,
        "memory": memory,
        "scaffold": scaffold,
        "project_root": tmp_path,
    }


def test_dispatcher_info(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    result = asyncio.run(dispatch(methods, "info", {}))
    assert result["active_profile"] == "test_ds"
    assert result["assistant_alias"] == "姐姐"
    assert result["project"]["namespace"] == "testproj"


def test_dispatcher_unknown_method(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    with pytest.raises(RpcError) as info:
        asyncio.run(dispatch(methods, "no.such.method", {}))
    assert info.value.code == METHOD_NOT_FOUND


def test_dispatcher_missing_required_param(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    with pytest.raises(RpcError) as info:
        asyncio.run(dispatch(methods, "knowledge.search", {}))
    assert info.value.code == INVALID_PARAMS


def test_dispatcher_presets_list(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    result = asyncio.run(dispatch(methods, "presets.list", {}))
    assert "items" in result
    assert isinstance(result["items"], list)
    # builtin 至少有 6 套
    assert len(result["items"]) >= 6


def test_dispatcher_memory_write_recall(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    write_result = asyncio.run(
        dispatch(
            methods,
            "memory.write",
            {"text": "qbox 用 ox_inventory，addItem 走 exports", "summary": "qbox 库存写法"},
        ),
    )
    assert "id" in write_result

    recall = asyncio.run(
        dispatch(methods, "memory.recall", {"query": "ox_inventory addItem", "k": 5}),
    )
    assert len(recall["items"]) >= 1


def test_dispatcher_project_detect_invalid_path(runtime_methods: dict[str, Any]) -> None:
    methods = runtime_methods["methods"]
    with pytest.raises(RpcError) as info:
        asyncio.run(
            dispatch(methods, "project.detect", {"path": "definitely/not/here"}),
        )
    assert info.value.code == INVALID_PARAMS


# ---------- server 主循环 ----------


def _frame(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    write_message_sync(buf, payload)
    return buf.getvalue()


def test_server_request_response_roundtrip() -> None:
    async def echo(params: dict[str, Any]) -> dict[str, Any]:
        return {"got": params}

    methods = {"echo": echo}

    in_buf = io.BytesIO(_frame(
        {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"a": 1}},
    ))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp == {
        "jsonrpc": "2.0", "id": 1, "result": {"got": {"a": 1}},
    }


def test_server_unknown_method_returns_error() -> None:
    methods: dict[str, Any] = {}
    in_buf = io.BytesIO(_frame(
        {"jsonrpc": "2.0", "id": 7, "method": "nope", "params": {}},
    ))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp is not None
    assert resp["id"] == 7
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_server_notification_no_response() -> None:
    """没 id 的请求是通知——不回。"""
    called: list[dict[str, Any]] = []

    async def collect(params: dict[str, Any]) -> dict[str, Any]:
        called.append(params)
        return {}

    methods = {"collect": collect}
    in_buf = io.BytesIO(_frame(
        {"jsonrpc": "2.0", "method": "collect", "params": {"k": 1}},
    ))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    assert called == [{"k": 1}]
    assert out_buf.getvalue() == b""


def test_server_shutdown_request_returns_then_stops() -> None:
    """收到 shutdown → 回响应 → 退出，后续请求不处理。"""
    async def boom(params: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("不应该被调到")

    methods = {"boom": boom}
    payload = (
        _frame({"jsonrpc": "2.0", "id": 1, "method": "shutdown"})
        + _frame({"jsonrpc": "2.0", "id": 2, "method": "boom"})
    )
    in_buf = io.BytesIO(payload)
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["ok"] is True
    # 第二条不应该被处理 → out_buf 只有一条
    assert read_message_sync(out_buf) is None


def test_server_handler_exception_becomes_error_response() -> None:
    async def kaboom(params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("人为爆炸")

    methods = {"kaboom": kaboom}
    in_buf = io.BytesIO(_frame(
        {"jsonrpc": "2.0", "id": 9, "method": "kaboom", "params": {}},
    ))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp is not None
    assert resp["id"] == 9
    assert "error" in resp
    assert "人为爆炸" in resp["error"]["message"]


def test_server_invalid_jsonrpc_field_returns_error() -> None:
    """没带 jsonrpc=2.0 的请求 → INVALID_REQUEST。"""
    in_buf = io.BytesIO(_frame({"id": 1, "method": "echo", "params": {}}))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        {}, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp is not None
    assert resp["error"]["code"] != 0


def test_server_handles_chinese_payload() -> None:
    async def repeat(params: dict[str, Any]) -> dict[str, Any]:
        return {"echo": params["msg"]}

    methods = {"repeat": repeat}
    in_buf = io.BytesIO(_frame(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "repeat",
            "params": {"msg": "玄玑姐姐你好"},
        },
    ))
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()

    asyncio.run(run_stdio_server(
        methods, stdin=in_buf, stdout=out_buf, stderr=err_buf,
    ))

    out_buf.seek(0)
    resp = read_message_sync(out_buf)
    assert resp is not None
    assert resp["result"]["echo"] == "玄玑姐姐你好"


def test_framing_write_uses_utf8() -> None:
    """中文写出后再读，确保 utf-8 编码。"""
    buf = io.BytesIO()
    write_message_sync(buf, {"text": "百工坊"})
    raw = buf.getvalue()
    body = raw.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body.decode("utf-8")) == {"text": "百工坊"}
