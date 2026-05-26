"""FastAPI 服务层单测。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
)
from core.knowledge.models import Chunk
from core.llm.providers.base import (
    AssistantMessage,
    Delta,
    LLMProvider,
    Message,
    ModelCapabilities,
)
from core.memory.models import Memory, MemoryKind, MemoryScope
from core.server.app import create_app
from core.server.runtime import ServerRuntime


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ServerRuntime:
    """隔离环境的 runtime——XUANJI_DATA_HOME / XUANJI_CONFIG_HOME 都临时化。"""
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "cfg"))
    cfg = ConfigStore(path=tmp_path / "cfg" / "config.json")
    cfg.upsert_profile(
        "test_ds",
        DeepSeekProfile(
            label="test", api_key="sk-test-placeholder", default_model="ds",
        ),
        activate=True,
    )
    return ServerRuntime(cfg_store=cfg, project_namespace="testproj")


def test_healthz(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_index_returns_html(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert "玄玑" in r.text
    assert "ws/chat" in r.text


def test_info_endpoint(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/api/info")
    assert r.status_code == 200
    data = r.json()
    assert data["active_profile"] == "test_ds"
    assert data["active"]["kind"] == "deepseek"


def test_profiles_endpoint(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/api/profiles")
    data = r.json()
    assert data["active"] == "test_ds"
    assert any(p["name"] == "test_ds" for p in data["items"])


def test_use_profile_unknown_returns_404(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.post("/api/profiles/use/ghost")
    assert r.status_code == 404


def test_use_profile_switch(runtime: ServerRuntime) -> None:
    """加第二个 profile 后切换。"""
    runtime.cfg_store.upsert_profile(
        "test_anth",
        AnthropicProfile(label="t", api_key="x", default_model="claude-x"),
    )
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.post("/api/profiles/use/test_anth")
    assert r.status_code == 200
    assert r.json()["active_profile"] == "test_anth"


def test_knowledge_search(runtime: ServerRuntime) -> None:
    runtime.knowledge.upsert_chunks(
        [
            Chunk(
                id="ns@1:c#0",
                namespace="ns@1",
                source_title="T",
                text="QBCore CreateUseableItem 用法示例",
            ),
        ],
    )
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.post(
            "/api/knowledge/search",
            json={"query": "CreateUseableItem", "k": 5},
        )
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) == 1
    assert "CreateUseableItem" in hits[0]["text"]


def test_knowledge_search_hybrid(runtime: ServerRuntime) -> None:
    """hybrid 路径应可用（即使没真挂向量索引也降级到 fts）。"""
    runtime.knowledge.upsert_chunks(
        [Chunk(id="a:c#0", namespace="a", source_title="T", text="alpha keyword")],
    )
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.post(
            "/api/knowledge/search",
            json={"query": "alpha", "hybrid": True, "k": 3},
        )
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) >= 1


def test_knowledge_stats(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/api/knowledge/stats")
    assert r.status_code == 200
    assert "chunks" in r.json()


def test_memory_recall(runtime: ServerRuntime) -> None:
    runtime.memory.write(
        Memory(
            scope=MemoryScope.PROJECT, kind=MemoryKind.SEMANTIC,
            namespace="testproj", text="alpha is important",
        ),
    )
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.post(
            "/api/memory/recall",
            json={"query": "alpha"},
        )
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) == 1
    assert "alpha" in hits[0]["text"]


def test_memory_stats(runtime: ServerRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        r = client.get("/api/memory/stats")
    assert r.status_code == 200


# ============================================================
# WebSocket 流式
# ============================================================


class _StreamProvider(LLMProvider):
    """注入静态 Delta 流的 provider。"""

    name = "fake"

    def __init__(self, deltas: list[Delta]) -> None:
        self._deltas = deltas

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            name=model, provider="fake",
            context_window=128_000, max_output_tokens=4096,
        )

    async def chat(self, **kw: Any) -> AssistantMessage:
        raise NotImplementedError

    async def stream(
        self, *, model: str, messages: Sequence[Message],
        system: str | None = None, **kw: Any,
    ) -> AsyncIterator[Delta]:
        for d in self._deltas:
            yield d


def test_websocket_chat_streams_text(
    runtime: ServerRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：客户端发 user_input → 服务端流式推 text_delta + message_done。"""
    deltas = [
        Delta(type="text_delta", index=0, text="姐姐"),
        Delta(type="text_delta", index=0, text="收到。"),
        Delta(type="message_done", stop_reason="end_turn"),
    ]
    monkeypatch.setattr(
        "core.neural.conductor.build_provider",
        lambda _p: _StreamProvider(deltas),
    )

    app = create_app(runtime)
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        # 第一条应该是 session_started
        session = ws.receive_json()
        assert session["type"] == "session_started"

        ws.send_json({"type": "user_input", "text": "你好"})

        collected_text = ""
        done = False
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "text_delta":
                collected_text += msg["text"]
            elif msg["type"] == "message_done":
                done = True
                break
    assert "姐姐" in collected_text
    assert "收到。" in collected_text
    assert done


def test_websocket_chat_no_active_profile(tmp_path: Path) -> None:
    """没有 active profile 时应推 error 并关闭连接。"""
    cfg = ConfigStore(path=tmp_path / "config.json")
    rt = ServerRuntime(cfg_store=cfg, project_namespace="x")
    app = create_app(rt)
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "profile" in msg["message"]
