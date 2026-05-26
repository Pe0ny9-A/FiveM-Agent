"""Reflux：把召回的记忆合成 system prompt 的注入段。

Conductor 在每轮 send 前调用 reflux_recall + refluxed_fragment，把命中的
top-k 记忆拼成一段中性文本，作为 extra_fragments 传给 build_system_prompt。
"""

from __future__ import annotations

from xuanji.memory.models import Memory


def refluxed_fragment(memories: list[Memory]) -> str | None:
    """合成"过往记忆回流"段。空列表返回 None。"""
    if not memories:
        return None
    lines = ["【过往记忆回流（仅供参考，与当前对话冲突时以小宝最新表达为准）】"]
    for i, m in enumerate(memories, 1):
        scope_kind = f"[{m.scope.value}/{m.kind.value}]"
        lines.append(f"{i}. {scope_kind} {m.display()}")
    return "\n".join(lines)
