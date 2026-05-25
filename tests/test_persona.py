"""人设系统单测。验证模式选择与 system prompt 合成的核心逻辑。"""

from __future__ import annotations

from core.persona import (
    XUANJI_CORE_PROMPT,
    XUANJI_GUARDRAILS,
    PersonaMode,
    PersonaTemperature,
    build_system_prompt,
    pick_mode,
)


def test_core_prompt_has_identity() -> None:
    """核心 prompt 必须包含玄玑身份与"姐姐/小宝"称呼约定。"""
    assert "玄玑" in XUANJI_CORE_PROMPT
    assert "姐姐" in XUANJI_CORE_PROMPT
    assert "小宝" in XUANJI_CORE_PROMPT


def test_guardrails_cover_high_risk() -> None:
    """守护规则必须覆盖高危确认与不做的事。"""
    assert "高危确认" in XUANJI_GUARDRAILS
    assert "脱敏" in XUANJI_GUARDRAILS


def test_build_default() -> None:
    """默认 chat + balanced 应包含核心 prompt 与守护规则。"""
    sp = build_system_prompt()
    assert XUANJI_CORE_PROMPT in sp
    assert XUANJI_GUARDRAILS in sp
    assert "闲聊" in sp


def test_build_gate_mode_no_playful_amplifier() -> None:
    """gate 模式 + playful 温度时仍应保持中性，不被 playful 拉满。"""
    sp = build_system_prompt(
        mode=PersonaMode.GATE,
        temperature=PersonaTemperature.PLAYFUL,
    )
    assert "完全中性" in sp
    # playful 描述里应明确 gate 不受影响
    assert "gate 模式不受影响" in sp


def test_build_professional_disables_persona() -> None:
    """professional 温度应明确关闭调侃。"""
    sp = build_system_prompt(temperature=PersonaTemperature.PROFESSIONAL)
    assert "中性专业" in sp
    assert "不要出现调侃" in sp


def test_extra_fragments_appended() -> None:
    """extra_fragments 应被附加到 system prompt 末尾，供能力包/记忆回流注入。"""
    fragment = "【FiveM 上下文】当前项目使用 QBox 框架。"
    sp = build_system_prompt(extra_fragments=[fragment])
    assert sp.endswith(fragment)


def test_pick_mode_destructive_overrides_kind() -> None:
    """destructive 风险无论 task_kind 都应走 GATE。"""
    assert pick_mode("chat", risk="destructive") == PersonaMode.GATE
    assert pick_mode("code", risk="destructive") == PersonaMode.GATE
    assert pick_mode("ops", risk="destructive") == PersonaMode.GATE


def test_pick_mode_routing() -> None:
    """常见 task_kind 应路由到正确的模式。"""
    assert pick_mode("chat") == PersonaMode.CHAT
    assert pick_mode("code") == PersonaMode.DEV
    assert pick_mode("ops") == PersonaMode.OPS
    assert pick_mode("review") == PersonaMode.REVIEW
    assert pick_mode("unknown_kind") == PersonaMode.CHAT


def test_default_aliases_no_directive_appended() -> None:
    """默认 alias 时不应追加"称呼覆盖"指令段，避免冗余。"""
    sp = build_system_prompt()
    assert "称呼覆盖" not in sp
    assert "覆盖前文中所有" not in sp


def test_custom_assistant_alias_appends_directive() -> None:
    """改了玄玑自称时应追加覆盖指令并出现新称呼。"""
    sp = build_system_prompt(assistant_alias="师父")
    assert "称呼覆盖" in sp
    assert "师父" in sp
    assert "覆盖前文中所有" in sp


def test_custom_user_alias_appends_directive() -> None:
    """改了对用户的称呼时应追加覆盖指令。"""
    sp = build_system_prompt(user_alias="徒儿")
    assert "徒儿" in sp
    assert "称呼用户：徒儿" in sp


def test_alias_directive_preserves_xuanji_real_name() -> None:
    """alias 覆盖指令应明确说明玄玑这个真名不变。"""
    sp = build_system_prompt(assistant_alias="阿玑", user_alias="阿白")
    assert "玄玑这个真名不变" in sp
