"""MCP server config 持久化 + registry 健康汇总测试。

不连真子进程——验证 ConfigStore 增删 / enable / disable 接口正确。
McpClientRegistry.connect_all 用 stub 命令验证失败汇总不抛。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.config.store import ConfigStore
from xuanji.mcp.registry import McpClientRegistry, McpServerConfig


@pytest.fixture
def cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把配置文件改到 tmp_path，避免污染用户目录。"""
    p = tmp_path / "config.json"
    monkeypatch.setattr(
        "xuanji.config.store.config_file_path", lambda: p,
    )
    return p


def test_upsert_and_remove_mcp_server(cfg_path: Path) -> None:
    store = ConfigStore()
    cfg = McpServerConfig(
        name="fs", command="python", args=["-m", "fake_mcp"], enabled=True,
    )
    store.upsert_mcp_server(cfg)
    loaded = store.load()
    assert len(loaded.mcp_servers) == 1
    assert loaded.mcp_servers[0].name == "fs"

    # upsert 同名应更新而非新增
    cfg2 = McpServerConfig(name="fs", command="node", args=["server.js"])
    store.upsert_mcp_server(cfg2)
    loaded2 = store.load()
    assert len(loaded2.mcp_servers) == 1
    assert loaded2.mcp_servers[0].command == "node"

    # remove
    store.remove_mcp_server("fs")
    loaded3 = store.load()
    assert loaded3.mcp_servers == []


def test_set_mcp_enabled(cfg_path: Path) -> None:
    store = ConfigStore()
    store.upsert_mcp_server(
        McpServerConfig(name="fs", command="python", args=[], enabled=True),
    )
    store.set_mcp_enabled("fs", enabled=False)
    loaded = store.load()
    assert loaded.mcp_servers[0].enabled is False


def test_set_mcp_enabled_unknown_name_returns_false(cfg_path: Path) -> None:
    """未知 server 名 set_mcp_enabled 返回 False，不抛。"""
    store = ConfigStore()
    assert store.set_mcp_enabled("ghost", enabled=True) is False


def test_remove_mcp_server_unknown_returns_false(cfg_path: Path) -> None:
    store = ConfigStore()
    assert store.remove_mcp_server("ghost") is False


@pytest.mark.asyncio
async def test_registry_connect_all_handles_failures(tmp_path: Path) -> None:
    """连不上的 server 应在 health_summary 里报错而不抛。"""
    cfg = McpServerConfig(
        name="bad",
        command="this-command-doesnt-exist-zxqq",
        args=[],
        enabled=True,
    )
    registry = McpClientRegistry([cfg])
    await registry.connect_all(connect_timeout=2.0)
    summary = registry.health_summary()
    assert "bad" in summary
    assert "error" in summary["bad"].lower() or "fail" in summary["bad"].lower() or "未" in summary["bad"]
    await registry.close_all()


@pytest.mark.asyncio
async def test_registry_skips_disabled() -> None:
    """enabled=False 的 server 不应尝试连接。"""
    cfg = McpServerConfig(
        name="disabled",
        command="anything",
        args=[],
        enabled=False,
    )
    registry = McpClientRegistry([cfg])
    await registry.connect_all(connect_timeout=2.0)
    summary = registry.health_summary()
    # 不应出现在 summary
    assert "disabled" not in summary or "skipped" in summary.get("disabled", "").lower()
    await registry.close_all()
