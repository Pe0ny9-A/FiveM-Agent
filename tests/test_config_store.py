"""配置存储单测。验证 profile 增删改查、激活切换、JSON 持久化。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.config import (
    AnthropicProfile,
    ConfigStore,
    DeepSeekProfile,
    OpenAICompatibleProfile,
    OpenAIProfile,
    ProfileKind,
    XuanjiConfig,
)
from xuanji.persona.modes import PersonaTemperature


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    return ConfigStore(path=tmp_path / "config.json")


def test_load_returns_empty_when_missing(store: ConfigStore) -> None:
    cfg = store.load()
    assert cfg.profiles == {}
    assert cfg.active_profile is None


def test_save_then_load_roundtrip(store: ConfigStore) -> None:
    cfg = XuanjiConfig(
        active_profile="ds",
        persona_temperature=PersonaTemperature.PLAYFUL,
        profiles={
            "ds": DeepSeekProfile(
                label="DeepSeek 官方",
                api_key="sk-ds-test-placeholder",
                default_model="deepseek-chat",
            ),
        },
    )
    store.save(cfg)
    loaded = store.load()
    assert loaded.active_profile == "ds"
    assert loaded.persona_temperature == PersonaTemperature.PLAYFUL
    p = loaded.profiles["ds"]
    assert isinstance(p, DeepSeekProfile)
    assert p.api_key == "sk-ds-test-placeholder"


def test_discriminator_picks_correct_subclass(store: ConfigStore) -> None:
    """JSON 反序列化应根据 kind 字段挑对子类。"""
    cfg = XuanjiConfig(
        profiles={
            "anth": AnthropicProfile(label="claude", api_key="sk-a", default_model="claude-x"),
            "oai": OpenAIProfile(label="gpt", api_key="sk-o", default_model="gpt-x"),
            "ds": DeepSeekProfile(label="ds", api_key="sk-d", default_model="ds-x"),
            "compat": OpenAICompatibleProfile(
                label="oneapi",
                api_key="sk-c",
                default_model="any-x",
                base_url="https://oneapi.example.com/v1",  # type: ignore[arg-type]
            ),
        },
    )
    store.save(cfg)
    loaded = store.load()
    assert isinstance(loaded.profiles["anth"], AnthropicProfile)
    assert isinstance(loaded.profiles["oai"], OpenAIProfile)
    assert isinstance(loaded.profiles["ds"], DeepSeekProfile)
    assert isinstance(loaded.profiles["compat"], OpenAICompatibleProfile)


def test_upsert_first_profile_auto_activates(store: ConfigStore) -> None:
    """第一个 profile 应自动激活，即便没显式要求。"""
    p = AnthropicProfile(label="c", api_key="sk-x", default_model="claude-sonnet-4-6")
    store.upsert_profile("first", p)
    assert store.load().active_profile == "first"


def test_upsert_with_activate_switches(store: ConfigStore) -> None:
    p1 = AnthropicProfile(label="a", api_key="sk-1", default_model="x")
    p2 = OpenAIProfile(label="b", api_key="sk-2", default_model="y")
    store.upsert_profile("p1", p1)
    store.upsert_profile("p2", p2, activate=True)
    assert store.load().active_profile == "p2"


def test_remove_active_falls_back_to_another(store: ConfigStore) -> None:
    """删除当前激活的 profile，应自动 fallback 到剩余的某个。"""
    store.upsert_profile(
        "p1", AnthropicProfile(label="a", api_key="sk-1", default_model="x")
    )
    store.upsert_profile(
        "p2", OpenAIProfile(label="b", api_key="sk-2", default_model="y"), activate=True
    )
    assert store.remove_profile("p2") is True
    cfg = store.load()
    assert "p2" not in cfg.profiles
    assert cfg.active_profile == "p1"


def test_remove_last_profile_clears_active(store: ConfigStore) -> None:
    store.upsert_profile(
        "only", AnthropicProfile(label="a", api_key="sk-1", default_model="x")
    )
    store.remove_profile("only")
    assert store.load().active_profile is None


def test_use_unknown_raises(store: ConfigStore) -> None:
    with pytest.raises(KeyError):
        store.use_profile("ghost")


def test_get_active_returns_none_when_unset(store: ConfigStore) -> None:
    cfg = store.load()
    assert cfg.get_active() is None


def test_kind_field_default_aligned_with_class() -> None:
    """每种 profile 的 kind 默认值必须与其类型对齐。"""
    assert AnthropicProfile(label="x", api_key="x", default_model="x").kind == ProfileKind.ANTHROPIC
    assert OpenAIProfile(label="x", api_key="x", default_model="x").kind == ProfileKind.OPENAI
    assert DeepSeekProfile(label="x", api_key="x", default_model="x").kind == ProfileKind.DEEPSEEK
    compat = OpenAICompatibleProfile(
        label="x",
        api_key="x",
        default_model="x",
        base_url="https://example.com/v1",  # type: ignore[arg-type]
    )
    assert compat.kind == ProfileKind.OPENAI_COMPATIBLE


def test_default_aliases_are_jiejie_xiaobao(store: ConfigStore) -> None:
    """空配置默认应用『姐姐』『小宝』。"""
    cfg = store.load()
    assert cfg.assistant_alias == "姐姐"
    assert cfg.user_alias == "小宝"


def test_set_aliases_partial_update(store: ConfigStore) -> None:
    """set_aliases 任一参数为 None 表示不改该项。"""
    store.set_aliases(assistant_alias="师父")
    cfg = store.load()
    assert cfg.assistant_alias == "师父"
    assert cfg.user_alias == "小宝"  # 未传，保持默认

    store.set_aliases(user_alias="徒儿")
    cfg = store.load()
    assert cfg.assistant_alias == "师父"  # 上次写入，仍保留
    assert cfg.user_alias == "徒儿"


def test_aliases_persist_across_load_save(store: ConfigStore) -> None:
    """alias 应该能 JSON 往返。"""
    store.set_aliases(user_alias="阿白", assistant_alias="阿玑")
    fresh = ConfigStore(path=store.path).load()
    assert fresh.user_alias == "阿白"
    assert fresh.assistant_alias == "阿玑"


def test_aliases_reject_empty_string() -> None:
    """alias 必须非空，避免 prompt 注入空白。"""
    import pytest as _pytest
    from pydantic import ValidationError as _VE

    with _pytest.raises(_VE):
        XuanjiConfig(assistant_alias="")
    with _pytest.raises(_VE):
        XuanjiConfig(user_alias="")
