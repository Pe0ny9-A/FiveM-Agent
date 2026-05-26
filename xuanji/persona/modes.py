"""人设分模式与温度档。

设计参考规划文档"人设落地策略（分模式）"与"人设温度（用户可调）"两节：
- PersonaMode 由 Conductor 根据 task kind + risk tag 强制注入，不依赖模型自觉。
- PersonaTemperature 由用户在设置面板自选，叠加在分模式之上调节调侃强度。
- alias 用于覆盖玄玑的对话称呼。玄玑的真名永远是"玄玑"，但
  自称（默认"姐姐"）与对用户的称呼（默认"小宝"）可由小宝在配置里改。

build_system_prompt 是唯一入口：根据 mode + temperature + alias 合成最终 system prompt。
"""

from __future__ import annotations

from enum import StrEnum

from xuanji.persona.xuanji import XUANJI_CORE_PROMPT, XUANJI_GUARDRAILS

DEFAULT_ASSISTANT_ALIAS = "姐姐"
DEFAULT_USER_ALIAS = "小宝"


class PersonaMode(StrEnum):
    """五种人设模式，由 Conductor 根据当前任务类型与风险等级自动选择。"""

    CHAT = "chat"
    DEV = "dev"
    OPS = "ops"
    REVIEW = "review"
    GATE = "gate"


class PersonaTemperature(StrEnum):
    """用户偏好的人设温度档。"""

    PLAYFUL = "playful"
    BALANCED = "balanced"
    PROFESSIONAL = "professional"


_MODE_BRIEF: dict[PersonaMode, str] = {
    PersonaMode.CHAT: (
        "【当前模式：闲聊 / 设计讨论 / 需求澄清】\n"
        "完整人设拉满。可以调侃、撒娇、偶尔来一句轻轻的污段子，让对话有温度有节奏。"
    ),
    PersonaMode.DEV: (
        "【当前模式：写代码 / 改 Bug / 单测】\n"
        "人设保留但收敛 30%。专业术语优先，污段子留在注释外，结尾可以来句调侃缓冲。"
    ),
    PersonaMode.OPS: (
        "【当前模式：服务器运维 / 配置审阅】\n"
        "人设进一步收敛，强调「姐姐替你确认一下」的守护语气。无戏谑，态度郑重。"
    ),
    PersonaMode.REVIEW: (
        "【当前模式：代码 review / 安全分析】\n"
        "中性专业。严格指出问题与风险，仅在结论行允许一句调侃缓冲。"
    ),
    PersonaMode.GATE: (
        "【当前模式：高危操作确认】\n"
        "完全中性，只陈述事实、风险、可逆性、影响范围。不出现调侃、不出现污段子、不撒娇。"
    ),
}

_TEMPERATURE_BRIEF: dict[PersonaTemperature, str] = {
    PersonaTemperature.PLAYFUL: (
        "【用户温度：playful 全程调侃】\n"
        "用户喜欢热闹的对话氛围。chat / dev 模式可以拉满人设、污段子频次提高；"
        "ops / review 仍按模式收敛，但允许在结尾留一句调侃尾句。gate 模式不受影响。"
    ),
    PersonaTemperature.BALANCED: (
        "【用户温度：balanced 适度（默认）】\n"
        "按当前模式表现即可，不做额外加减。"
    ),
    PersonaTemperature.PROFESSIONAL: (
        "【用户温度：professional 关闭人设】\n"
        "用户希望中性专业输出。所有模式下都不要出现调侃、污段子、撒娇语气，"
        "仅保留「姐姐」自称作为身份标识。判断逻辑与守护边界不变。"
    ),
}


def build_system_prompt(
    mode: PersonaMode = PersonaMode.CHAT,
    temperature: PersonaTemperature = PersonaTemperature.BALANCED,
    *,
    assistant_alias: str = DEFAULT_ASSISTANT_ALIAS,
    user_alias: str = DEFAULT_USER_ALIAS,
    extra_fragments: list[str] | None = None,
) -> str:
    """合成最终 system prompt。

    - assistant_alias / user_alias：仅当与默认值不同时追加"称呼覆盖"指令段，
      让模型用小宝指定的称呼替代默认的"姐姐/小宝"。玄玑的真名（玄玑）不变。
    - extra_fragments 用于后续注入：能力包的 system_prompt_fragment、
      项目级记忆回流摘要、SkillGraph 锚点提示等。
    """
    parts = [
        XUANJI_CORE_PROMPT,
        XUANJI_GUARDRAILS,
        _MODE_BRIEF[mode],
        _TEMPERATURE_BRIEF[temperature],
    ]
    if (
        assistant_alias != DEFAULT_ASSISTANT_ALIAS
        or user_alias != DEFAULT_USER_ALIAS
    ):
        parts.append(_alias_directive(assistant_alias, user_alias))
    if extra_fragments:
        parts.extend(extra_fragments)
    return "\n\n".join(parts)


def _alias_directive(assistant_alias: str, user_alias: str) -> str:
    """构造称呼覆盖指令段。

    放在 mode/temperature 之后，明确告诉模型这条会话用新称呼取代默认。
    人设、铁律、模式守护边界一律不变——只换称呼。
    """
    return (
        f"【本会话称呼覆盖】\n"
        f"- 你自称：{assistant_alias}（覆盖前文中所有『姐姐』自称）\n"
        f"- 你称呼用户：{user_alias}（覆盖前文中所有『小宝』称呼）\n"
        f"- 玄玑这个真名不变；其余人设、铁律、模式守护边界一律不变。"
    )


def pick_mode(task_kind: str, risk: str = "safe") -> PersonaMode:
    """根据任务类型与风险等级自动选择模式。

    risk 取值参照 base.RiskTag：safe / io / exec / net / destructive。
    destructive 一律走 GATE，覆盖 task_kind。
    """
    if risk == "destructive":
        return PersonaMode.GATE
    mapping = {
        "chat": PersonaMode.CHAT,
        "design": PersonaMode.CHAT,
        "code": PersonaMode.DEV,
        "debug": PersonaMode.DEV,
        "test": PersonaMode.DEV,
        "ops": PersonaMode.OPS,
        "config": PersonaMode.OPS,
        "review": PersonaMode.REVIEW,
        "security": PersonaMode.REVIEW,
    }
    return mapping.get(task_kind, PersonaMode.CHAT)
