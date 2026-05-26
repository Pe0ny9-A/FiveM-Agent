"""人设系统。玄玑的灵魂在这里。"""

from core.persona.modes import (
    DEFAULT_ASSISTANT_ALIAS,
    DEFAULT_USER_ALIAS,
    PersonaMode,
    PersonaTemperature,
    build_system_prompt,
    pick_mode,
)
from core.persona.xuanji import XUANJI_CORE_PROMPT, XUANJI_GUARDRAILS

__all__ = [
    "DEFAULT_ASSISTANT_ALIAS",
    "DEFAULT_USER_ALIAS",
    "XUANJI_CORE_PROMPT",
    "XUANJI_GUARDRAILS",
    "PersonaMode",
    "PersonaTemperature",
    "build_system_prompt",
    "pick_mode",
]
