"""Profile 探测单测。

测覆盖：
- list_models 解析 OpenAI 兼容返回
- list_models 顶层 list 兜底
- ping anthropic 200 / openai 401 错误格式
- _ensure_path 路径拼接（含 /v1 与不含）
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from xuanji.config.probe import (
    _ensure_path,
    list_models,
    ping,
)
from xuanji.config.profiles import (
    AnthropicProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    WireFormat,
)


def test_ensure_path_no_v1_in_base() -> None:
    assert _ensure_path("https://api.deepseek.com", "/v1/messages") == (
        "https://api.deepseek.com/v1/messages"
    )


def test_ensure_path_v1_in_base_strips_prefix() -> None:
    assert _ensure_path("https://api.openai.com/v1", "/v1/chat/completions") == (
        "https://api.openai.com/v1/chat/completions"
    )


def _fake_response(*, status_code: int = 200, json_payload: Any = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_payload)
    resp.text = text
    return resp


@pytest.mark.asyncio
async def test_list_models_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [
            {"id": "gpt-4o-mini", "owned_by": "openai", "created": 1},
            {"id": "claude-sonnet-4-6", "owned_by": "anthropic"},
        ]
    }
    fake_resp = _fake_response(status_code=200, json_payload=payload)

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: fake_client)

    profile = OpenAICompatibleProfile(
        label="newapi",
        api_key="sk-test-placeholder",
        default_model="gpt-4o-mini",
        base_url="https://newapi.example.com",
        wire_format=WireFormat.OPENAI,
    )
    out = await list_models(profile)
    ids = [m.id for m in out]
    assert "gpt-4o-mini" in ids
    assert "claude-sonnet-4-6" in ids
    # 排序保证稳定
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_list_models_top_level_list(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "model-a"}, {"id": "model-b"}]
    fake_resp = _fake_response(status_code=200, json_payload=payload)
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: fake_client)

    profile = OpenAIProfile(
        label="openai",
        api_key="sk-test-placeholder",
        default_model="gpt-4o-mini",
    )
    out = await list_models(profile)
    assert [m.id for m in out] == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_ping_anthropic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resp = _fake_response(status_code=200, json_payload={"id": "msg_x"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: fake_client)

    profile = AnthropicProfile(
        label="claude",
        api_key="sk-test-placeholder",
        default_model="claude-sonnet-4-6",
    )
    result = await ping(profile)
    assert result.ok is True
    assert result.status == 200
    assert result.error is None


@pytest.mark.asyncio
async def test_ping_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resp = _fake_response(
        status_code=401,
        json_payload={"error": {"message": "Invalid API key"}},
    )
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: fake_client)

    profile = OpenAIProfile(
        label="openai",
        api_key="sk-bad-placeholder",
        default_model="gpt-4o-mini",
    )
    result = await ping(profile)
    assert result.ok is False
    assert result.status == 401
    assert result.error is not None
    assert "Invalid API key" in result.error


@pytest.mark.asyncio
async def test_ping_uses_anthropic_wire_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """openai-compatible + wire_format=anthropic 应该打 /v1/messages。"""
    fake_resp = _fake_response(status_code=200, json_payload={"id": "msg_x"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: fake_client)

    profile = OpenAICompatibleProfile(
        label="newapi-claude",
        api_key="sk-test-placeholder",
        default_model="claude-sonnet-4-6",
        base_url="https://newapi.example.com",
        wire_format=WireFormat.ANTHROPIC,
    )
    await ping(profile)
    # 检查请求 URL 与认证头
    call = fake_client.post.await_args
    assert call is not None
    url = call.args[0] if call.args else call.kwargs.get("url")
    assert "/v1/messages" in url
    headers = call.kwargs["headers"]
    assert "x-api-key" in headers
    assert headers["x-api-key"] == "sk-test-placeholder"
