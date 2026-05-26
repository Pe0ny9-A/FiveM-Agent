"""策略与裁决。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from xuanji.capability.tool import RiskTag, Tool, ToolCtx


class VerdictKind(StrEnum):
    PASS = "pass"  # 直接放行
    HITL = "hitl"  # 需要用户人工确认
    DENY = "deny"  # 直接拒绝（不询问用户）


class Verdict(BaseModel):
    """策略裁决。"""

    kind: VerdictKind
    reason: str = ""

    @classmethod
    def pass_(cls, reason: str = "") -> Verdict:
        return cls(kind=VerdictKind.PASS, reason=reason)

    @classmethod
    def hitl(cls, reason: str) -> Verdict:
        return cls(kind=VerdictKind.HITL, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> Verdict:
        return cls(kind=VerdictKind.DENY, reason=reason)


class Policy(Protocol):
    """策略协议。"""

    def evaluate(self, tool: Tool, args: dict[str, Any], ctx: ToolCtx) -> Verdict: ...


class DefaultPolicy:
    """M0 默认策略（硬编码）。

    规则：
    - DESTRUCTIVE → DENY 永远拒绝
    - EXEC / NET → HITL 必须确认
    - IO → 写入工程外目录走 HITL，工程内通过
    - SAFE → PASS 直接放行

    后续 M2 阶段升级为 OPA-lite YAML 策略。
    """

    def evaluate(self, tool: Tool, args: dict[str, Any], ctx: ToolCtx) -> Verdict:
        if tool.risk == RiskTag.DESTRUCTIVE:
            return Verdict.deny(f"{tool.name} 标记为 destructive，禁止自动执行")

        if tool.risk == RiskTag.EXEC:
            cmd = args.get("command", "")
            return Verdict.hitl(f"将执行命令：{cmd}")

        if tool.risk == RiskTag.NET:
            url = args.get("url", "")
            return Verdict.hitl(f"将访问网络：{url}")

        if tool.risk == RiskTag.IO:
            target = args.get("path") or args.get("file")
            if not target:
                return Verdict.pass_()
            target_path = Path(str(target))
            if not target_path.is_absolute():
                target_path = (ctx.project_root / target_path).resolve()
            if ctx.is_inside_project(target_path):
                return Verdict.pass_(f"写入工程内：{target_path}")
            return Verdict.hitl(f"将写入工程外路径：{target_path}")

        return Verdict.pass_()
