"""Profile 健康探测：拉取可用模型列表 + 简单握手测试。

参照 cc switch / OneAPI 的玩法：
- list_models()  GET {base_url}/models（OpenAI 兼容）或 {base_url}/v1/models
                 Anthropic 协议端点也有 /v1/models（2024+ 已上线）
- ping()         按 wire_format 各自轻量调用一次：
                   * openai      → POST /v1/chat/completions（max_tokens=1）
                   * anthropic   → POST /v1/messages（max_tokens=1）
                 失败把 status + error.message 抛出来给前端展示。

不依赖 SDK，直接用 httpx 异步客户端，避免 SDK 在 base_url 上做隐藏改写。
所有调用都带 8 秒超时，避免前端 spinner 卡死。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from xuanji.config.profiles import (
    OFFICIAL_BASE_URLS,
    AnthropicProfile,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    Profile,
    ProfileKind,
    WireFormat,
)

_TIMEOUT = 8.0


@dataclass
class ModelInfo:
    id: str
    owned_by: str | None = None
    created: int | None = None


@dataclass
class ProbeResult:
    ok: bool
    latency_ms: int
    error: str | None = None
    status: int | None = None


def _resolve(profile: Profile) -> tuple[str, WireFormat]:
    """从 profile 拿出 (base_url, wire_format)。"""
    if isinstance(profile, OpenAICompatibleProfile):
        return str(profile.base_url).rstrip("/"), profile.wire_format
    if isinstance(profile, AnthropicProfile):
        return OFFICIAL_BASE_URLS[ProfileKind.ANTHROPIC].rstrip("/"), WireFormat.ANTHROPIC
    if isinstance(profile, OpenAIProfile):
        return OFFICIAL_BASE_URLS[ProfileKind.OPENAI].rstrip("/"), WireFormat.OPENAI
    if isinstance(profile, DeepSeekProfile):
        return OFFICIAL_BASE_URLS[ProfileKind.DEEPSEEK].rstrip("/"), WireFormat.OPENAI
    raise ValueError(f"未知 profile 类型：{type(profile).__name__}")


def _models_url(base: str, wire: WireFormat) -> str:
    """构造 /models 端点 URL，兼容 base 已含 /v1 与未含 /v1 两种写法。"""
    if base.endswith("/v1"):
        return base + "/models"
    # OpenAI 端点 base 通常是 https://api.openai.com/v1，DeepSeek 是 https://api.deepseek.com
    # NewAPI 转发常见 base = https://newapi.example.com（无 /v1），所以补上
    return base + "/v1/models"


def _auth_headers(api_key: str, wire: WireFormat) -> dict[str, str]:
    if wire is WireFormat.ANTHROPIC:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


async def list_models(profile: Profile) -> list[ModelInfo]:
    """GET /models 拉取可用模型。失败抛 RuntimeError。"""
    base, wire = _resolve(profile)
    url = _models_url(base, wire)
    headers = _auth_headers(profile.api_key, wire)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise RuntimeError(f"网络错误：{e}") from e
    if resp.status_code != 200:
        raise RuntimeError(_format_http_error(resp))

    try:
        payload = resp.json()
    except ValueError as e:
        raise RuntimeError(f"返回不是 JSON：{e}") from e

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        # 有的中转把模型直接放在顶层 list
        if isinstance(payload, list):
            items = payload
        else:
            raise RuntimeError("返回结构不识别（缺 data 字段）")

    out: list[ModelInfo] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = it.get("id") or it.get("name")
        if not mid:
            continue
        out.append(
            ModelInfo(
                id=str(mid),
                owned_by=str(it["owned_by"]) if "owned_by" in it else None,
                created=int(it["created"]) if isinstance(it.get("created"), int) else None,
            )
        )
    out.sort(key=lambda m: m.id)
    return out


async def ping(profile: Profile, *, model: str | None = None) -> ProbeResult:
    """轻量握手：发 1 token 调用，验证 api_key + wire_format 联通。"""
    base, wire = _resolve(profile)
    headers = _auth_headers(profile.api_key, wire)
    test_model = model or profile.default_model
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if wire is WireFormat.ANTHROPIC:
                url = _ensure_path(base, "/v1/messages")
                body = {
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                }
            else:
                url = _ensure_path(base, "/v1/chat/completions")
                body = {
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                }
            resp = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        return ProbeResult(
            ok=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=f"网络错误：{e}",
        )

    latency = int((time.perf_counter() - started) * 1000)
    if resp.status_code in (200, 201):
        return ProbeResult(ok=True, latency_ms=latency, status=resp.status_code)
    return ProbeResult(
        ok=False,
        latency_ms=latency,
        status=resp.status_code,
        error=_format_http_error(resp),
    )


def _ensure_path(base: str, suffix: str) -> str:
    """拼出完整端点。

    base 可能是 https://api.openai.com/v1 (含 /v1)
    或      https://api.deepseek.com    (无 /v1)；suffix 形如 /v1/messages。
    base 已含 /v1 时去掉 suffix 的前导 /v1。
    """
    if base.endswith("/v1") and suffix.startswith("/v1/"):
        return base + suffix[len("/v1") :]
    return base + suffix


def _format_http_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        msg = (
            (data.get("error") or {}).get("message")
            if isinstance(data, dict)
            else None
        ) or (data.get("message") if isinstance(data, dict) else None)
        if msg:
            return f"HTTP {resp.status_code}: {msg}"
    except ValueError:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:200]}"
