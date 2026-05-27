"""议会裁决器 Judge · 把多份 Councilor 输出合成一份结构化裁决书。

为什么单独一个文件？
- Judge 用旗舰模型（默认 anthropic 上 Opus），人格独立——既不是 Supervisor 也不是某个 Councilor
- system prompt 固化在这里，不暴露给 role 系统避免被混淆
- 输出 schema 固定（Verdict），下游写记忆 / 推 IPC / 给 UI 都用同一份

容错：
- LLM 偶尔返回 markdown 包裹的 JSON、或前后带解释——做容错抽取
- 解析失败时 fallback 成一份「summary 含原文」的最小 Verdict，议会仍能闭环
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from xuanji.config.profiles import Profile
from xuanji.llm.providers.base import LLMProvider, Message
from xuanji.llm.providers.factory import build_provider

if TYPE_CHECKING:
    from xuanji.ensemble.council import CouncilorOutcome


_JUDGE_SYSTEM_PROMPT = (
    "你是玄玑议会的『裁决者』，独立于所有 Councilor 之上。"
    "你刚刚收到议会就同一议题的多份独立答复，每份来自不同身份/不同模型的 Councilor。"
    "你的任务：在不偏袒任何一方的前提下，输出一份结构化裁决书。\n"
    "\n"
    "守则：\n"
    "1. 不要复读 Councilor 的原文——做综合，不做摘录。\n"
    "2. 共识点（consensus_points）：多数 Councilor 都认可、可放心采纳的判断。\n"
    "3. 分歧点（divergence_points）：有明显分歧时，写清楚『谁主张什么、各自的理由』。\n"
    "4. 选择路径（chosen_path）：如果议题是在多个方案间二选一/多选一，给出你的选择；"
    "若各方案都不可取或议题不是选择题，置 null。\n"
    "5. 风险（risks）：你额外看到的、Councilor 未充分讨论但需要小宝知道的隐患。\n"
    "6. summary 一段话写明结论。中性专业语气，不调侃。\n"
    "\n"
    "输出格式：严格的 JSON，不要 markdown 包裹、不要前后解释。Schema：\n"
    "{\n"
    '  "summary": "string",\n'
    '  "chosen_path": "string or null",\n'
    '  "consensus_points": ["string", ...],\n'
    '  "divergence_points": ["string", ...],\n'
    '  "risks": ["string", ...]\n'
    "}\n"
)


class Verdict(BaseModel):
    """裁决书。议会的最终产物。"""

    summary: str
    """一段话：议会得出什么结论。"""

    chosen_path: str | None = None
    """选了哪个方案；议题非选择题或全部不可取时为 null。"""

    consensus_points: list[str] = Field(default_factory=list)
    """各 Councilor 的共识点。"""

    divergence_points: list[str] = Field(default_factory=list)
    """分歧点 + 各方原因。"""

    risks: list[str] = Field(default_factory=list)
    """Judge 看到的额外风险。"""

    decided_by: str
    """裁决用的 model id。"""

    councilors: list[str] = Field(default_factory=list)
    """参与的 Councilor 的 model id 列表（带 role 前缀）。"""

    decided_at: float
    """Unix 时间戳。"""


class Judge:
    """议会裁决器。一次性使用——构造时绑定 (profile, model)。"""

    def __init__(self, *, profile: Profile, model: str) -> None:
        self.profile = profile
        self.model = model
        self.provider: LLMProvider = build_provider(profile)

    async def judge(
        self,
        *,
        question: str,
        outcomes: list[CouncilorOutcome],
    ) -> Verdict:
        """读多份 Councilor 输出，输出 Verdict。"""
        user_prompt = self._build_user_prompt(question, outcomes)

        resp = await self.provider.chat(
            model=self.model,
            messages=[Message(role="user", content=user_prompt)],
            system=_JUDGE_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.3,
        )

        raw = resp.text.strip()
        parsed = _safe_parse_verdict_json(raw)

        decided_at = time.time()
        councilor_ids = [
            f"{o.role}/{o.profile_name}/{o.model}" for o in outcomes
        ]

        if parsed is None:
            return Verdict(
                summary=(
                    "[Judge 解析失败，原文如下]\n" + raw[:1500]
                    if raw
                    else "[Judge 未返回任何文本]"
                ),
                chosen_path=None,
                consensus_points=[],
                divergence_points=[],
                risks=["Judge 输出未通过 JSON 解析，建议人工复核"],
                decided_by=self.model,
                councilors=councilor_ids,
                decided_at=decided_at,
            )

        try:
            return Verdict(
                summary=str(parsed.get("summary", "")).strip()
                or "[Judge 未给出 summary]",
                chosen_path=(
                    str(parsed["chosen_path"]).strip()
                    if parsed.get("chosen_path") not in (None, "", "null")
                    else None
                ),
                consensus_points=_as_str_list(parsed.get("consensus_points")),
                divergence_points=_as_str_list(parsed.get("divergence_points")),
                risks=_as_str_list(parsed.get("risks")),
                decided_by=self.model,
                councilors=councilor_ids,
                decided_at=decided_at,
            )
        except ValidationError as e:
            return Verdict(
                summary=f"[Verdict 字段校验失败：{e}]",
                chosen_path=None,
                consensus_points=[],
                divergence_points=[],
                risks=["Verdict 字段校验失败，建议人工复核"],
                decided_by=self.model,
                councilors=councilor_ids,
                decided_at=decided_at,
            )

    def _build_user_prompt(
        self,
        question: str,
        outcomes: list[CouncilorOutcome],
    ) -> str:
        lines: list[str] = [
            f"【议题】\n{question}\n",
            f"【Councilor 数量】{len(outcomes)}\n",
        ]
        for i, o in enumerate(outcomes, start=1):
            header = (
                f"--- Councilor #{i} · 身份={o.role} · "
                f"profile={o.profile_name} · model={o.model} ---"
            )
            lines.append(header)
            if o.error:
                lines.append(f"[该 Councilor 失败：{o.error}]")
            elif o.truncated:
                lines.append("[该 Councilor 触顶未收敛，输出可能不完整]")
                lines.append(o.final_text or "[空]")
            else:
                lines.append(o.final_text or "[空]")
            lines.append("")
        lines.append(
            "请按 system 中描述的 JSON 格式输出裁决书。",
        )
        return "\n".join(lines)


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _safe_parse_verdict_json(raw: str) -> dict[str, object] | None:
    """LLM 偶尔会用 markdown 包 JSON / 前后带解释。这里做几层兜底。"""
    if not raw:
        return None
    candidates: list[str] = []
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(raw)
    obj_match = _JSON_OBJECT_RE.search(raw)
    if obj_match:
        candidates.append(obj_match.group(0))

    for c in candidates:
        try:
            data = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
        elif item is not None:
            out.append(str(item))
    return out


__all__ = ["Judge", "Verdict"]
