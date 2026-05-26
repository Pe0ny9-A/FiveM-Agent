"""init / doctor / version 三个 CLI 命令的单测。

只测纯函数核心（_do_init / _doctor_checks）和 typer CliRunner 入口的快路径。
不动用网络，不实际调用模型。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import xuanji.cli as cli_mod
from xuanji import __version__
from xuanji.cli import _do_init, _doctor_checks, app
from xuanji.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    ProfileKind,
)


@pytest.fixture(autouse=True)
def isolated_xuanji_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """让所有测试都在 tmp_path 里跑，互不干扰，也不污染真实 ~/AppData。"""
    monkeypatch.setenv("XUANJI_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XUANJI_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------- version ----------


def test_version_shows_package_version(runner: CliRunner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
    assert "xuanji" in result.stdout


# ---------- doctor ----------


def test_doctor_flags_missing_config(runner: CliRunner) -> None:
    """空目录 + 没 config → doctor 至少 1 项失败，退码 1。"""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "config.json" in result.stdout
    assert "active profile" in result.stdout


def test_doctor_passes_after_init(runner: CliRunner) -> None:
    """先用 _do_init 把 profile 落盘 + 种子导入，doctor 应全绿（exit 0）。"""
    _do_init(
        profile_name="t",
        kind=ProfileKind.ANTHROPIC,
        api_key="sk-test-placeholder",
        base_url=None,
        seed_knowledge=True,
        skip_test=True,
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "全部通过" in result.stdout


def test_doctor_checks_returns_tuples() -> None:
    """_doctor_checks 应该返回 (name, ok, detail) 三元组。"""
    checks = _doctor_checks()
    assert len(checks) >= 5
    for name, ok, detail in checks:
        assert isinstance(name, str)
        assert isinstance(ok, bool)
        assert isinstance(detail, str)


def test_doctor_python_check_passes() -> None:
    """python>=3.12 这一项必须通过——pyproject 已要求 3.12+。"""
    checks = _doctor_checks()
    py_check = next(c for c in checks if c[0] == "python>=3.12")
    assert py_check[1] is True


# ---------- init (核心 _do_init) ----------


def test_do_init_writes_anthropic_profile() -> None:
    _do_init(
        profile_name="claude",
        kind=ProfileKind.ANTHROPIC,
        api_key="sk-test-placeholder",
        base_url=None,
        seed_knowledge=False,
        skip_test=True,
    )
    cfg = ConfigStore().load()
    assert cfg.active_profile == "claude"
    p = cfg.profiles["claude"]
    assert isinstance(p, AnthropicProfile)
    assert p.api_key == "sk-test-placeholder"


def test_do_init_writes_openai_profile() -> None:
    _do_init(
        profile_name="gpt",
        kind=ProfileKind.OPENAI,
        api_key="sk-test-placeholder",
        base_url=None,
        seed_knowledge=False,
        skip_test=True,
    )
    cfg = ConfigStore().load()
    assert isinstance(cfg.profiles["gpt"], OpenAIProfile)


def test_do_init_writes_deepseek_profile() -> None:
    _do_init(
        profile_name="ds",
        kind=ProfileKind.DEEPSEEK,
        api_key="sk-test-placeholder",
        base_url=None,
        seed_knowledge=False,
        skip_test=True,
    )
    cfg = ConfigStore().load()
    assert isinstance(cfg.profiles["ds"], DeepSeekProfile)


def test_do_init_compatible_requires_base_url() -> None:
    """openai-compatible 缺 base_url 必须报错 + Exit。"""
    import typer

    with pytest.raises(typer.Exit):
        _do_init(
            profile_name="oneapi",
            kind=ProfileKind.OPENAI_COMPATIBLE,
            api_key="sk-test-placeholder",
            base_url=None,
            seed_knowledge=False,
            skip_test=True,
        )


def test_do_init_compatible_with_base_url_works() -> None:
    _do_init(
        profile_name="oneapi",
        kind=ProfileKind.OPENAI_COMPATIBLE,
        api_key="sk-test-placeholder",
        base_url="https://oneapi.example.com/v1",
        seed_knowledge=False,
        skip_test=True,
    )
    cfg = ConfigStore().load()
    p = cfg.profiles["oneapi"]
    assert isinstance(p, OpenAICompatibleProfile)
    assert str(p.base_url).startswith("https://oneapi.example.com")


def test_do_init_seeds_knowledge() -> None:
    """seed_knowledge=True 时知识库应有内容。"""
    _do_init(
        profile_name="x",
        kind=ProfileKind.ANTHROPIC,
        api_key="sk-test-placeholder",
        base_url=None,
        seed_knowledge=True,
        skip_test=True,
    )
    store = cli_mod._open_knowledge_store()
    s = store.stats()
    assert int(s["sources"]) > 0
    assert int(s["chunks"]) > 0


# ---------- init 命令入口（CliRunner 走一遍）----------


def test_init_command_via_cli(runner: CliRunner) -> None:
    """CLI 入口走通：传 --skip-test 避免实际请求。"""
    result = runner.invoke(
        app,
        [
            "init",
            "--name", "default",
            "--kind", "anthropic",
            "--api-key", "sk-test-placeholder",
            "--no-seed",
            "--skip-test",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = ConfigStore().load()
    assert cfg.active_profile == "default"
