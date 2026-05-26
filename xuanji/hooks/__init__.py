"""Hooks 子系统：YAML + Pre/PostToolUse / UserPromptSubmit / Notification。

事件名复用 Claude Code 习惯，文件可在两边迁移：
- PreToolUse：工具调用前，hook 可拒绝（exit_code=2 或 JSON {"decision":"deny"}）
- PostToolUse：工具调用后，hook 看到 result，纯观察用
- UserPromptSubmit：用户输入提交时
- Notification：玄玑主动通知时（HITL 弹窗、长任务进度等）

hook = 一个外部命令。玄玑把事件 payload JSON 写到 hook 的 stdin，等 hook 退出。
- exit 0：放行
- exit 2 或 JSON {"decision":"deny", "reason": "..."}：拒绝（仅 PreToolUse 生效）
- 其他：视作错误，走默认 allow（避免 hook 故障锁死整个会话）

YAML 格式：
    hooks:
      - matcher: "run_shell"          # tool_name 等于或 glob；UserPromptSubmit 下是子串
        command: "python -m my_audit" # 完整 shell 命令
        timeout: 10                    # 秒，默认 30
        run_in_project_root: true      # 默认 true
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class HookEvent(StrEnum):
    """与 Claude Code 一致的事件名。"""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    NOTIFICATION = "Notification"


class HookSpec(BaseModel):
    """单条 hook 定义。"""

    matcher: str = "*"
    """tool_name glob 或 prompt 子串（按事件类型决定语义）"""

    command: str
    """完整 shell 命令"""

    timeout: float = 30.0
    """秒"""

    run_in_project_root: bool = True

    description: str = ""


class HooksFile(BaseModel):
    """单个 event yaml 文件。"""

    hooks: list[HookSpec] = Field(default_factory=list)


@dataclass
class HookResult:
    """单条 hook 的执行结果。"""

    spec: HookSpec
    exit_code: int
    stdout: str
    stderr: str
    decision: str | None = None
    """从 hook stdout 解析出的 decision（"deny" / "allow"）。"""

    reason: str | None = None
    """deny 时的原因。"""

    error: str | None = None
    """命令执行本身失败（超时 / 启动失败）"""

    @property
    def denied(self) -> bool:
        """PreToolUse 下是否要拒绝调用。

        触发拒绝的两种方式：
        1. exit code == 2
        2. stdout 是 JSON {"decision": "deny", "reason": "..."}
        """
        if self.error:
            return False
        if self.exit_code == 2:
            return True
        return self.decision == "deny"


class HooksRegistry:
    """扫 hooks 目录，按事件返回 spec 列表。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[HookEvent, tuple[float, list[HookSpec]]] = {}

    def for_event(self, event: HookEvent) -> list[HookSpec]:
        """返回某事件的全部 hook spec，文件不存在则空列表。"""
        path = self.root / f"{event.value}.yaml"
        if not path.exists():
            self._cache.pop(event, None)
            return []
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
        cached = self._cache.get(event)
        if cached and cached[0] == mtime:
            return list(cached[1])
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            file_obj = HooksFile.model_validate(data)
        except (yaml.YAMLError, ValueError):
            return []
        self._cache[event] = (mtime, file_obj.hooks)
        return list(file_obj.hooks)

    def matching(
        self,
        event: HookEvent,
        *,
        tool_name: str | None = None,
        prompt: str | None = None,
    ) -> list[HookSpec]:
        """返回 matcher 命中的 spec 子集。"""
        out: list[HookSpec] = []
        for spec in self.for_event(event):
            if event in (HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE):
                if tool_name is None:
                    continue
                if spec.matcher == "*" or fnmatch.fnmatchcase(tool_name, spec.matcher):
                    out.append(spec)
            elif event == HookEvent.USER_PROMPT_SUBMIT:
                if prompt is None:
                    continue
                if spec.matcher == "*" or spec.matcher.lower() in prompt.lower():
                    out.append(spec)
            else:
                if spec.matcher == "*":
                    out.append(spec)
        return out


async def run_hook(spec: HookSpec, payload: dict[str, Any], *, cwd: Path) -> HookResult:
    """跑单条 hook，把 payload 写到 stdin。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = await asyncio.create_subprocess_shell(
            spec.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if spec.run_in_project_root else None,
            env=env,
        )
    except OSError as e:
        return HookResult(
            spec=spec, exit_code=-1, stdout="", stderr="", error=f"启动失败：{e}",
        )
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(payload_bytes),
            timeout=spec.timeout,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return HookResult(
            spec=spec, exit_code=-1, stdout="", stderr="",
            error=f"hook 执行超时（{spec.timeout}s）",
        )
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    decision: str | None = None
    reason: str | None = None
    text = stdout.strip()
    if text and text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                decision = obj.get("decision") if isinstance(obj.get("decision"), str) else None
                reason = obj.get("reason") if isinstance(obj.get("reason"), str) else None
        except json.JSONDecodeError:
            pass
    return HookResult(
        spec=spec,
        exit_code=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        decision=decision,
        reason=reason,
    )


async def run_matching_hooks(
    registry: HooksRegistry,
    event: HookEvent,
    payload: dict[str, Any],
    *,
    cwd: Path,
    tool_name: str | None = None,
    prompt: str | None = None,
) -> list[HookResult]:
    """跑所有命中 matcher 的 hook，按声明顺序串行（语义清晰）。"""
    specs = registry.matching(event, tool_name=tool_name, prompt=prompt)
    results: list[HookResult] = []
    for spec in specs:
        results.append(await run_hook(spec, payload, cwd=cwd))
    return results


@dataclass
class HookExplanation:
    """单条 hook 的 dry-run 解释——「假如真的跑会发生什么」。"""

    spec: HookSpec
    """命中的 hook spec。"""

    matched: bool
    """是否会被触发。"""

    reason: str
    """为什么命中 / 不命中——matcher 类型 + 命中规则。"""

    can_deny: bool
    """这个事件下，hook 拒绝是否有效（仅 PreToolUse 拒绝会真正阻断调用）。"""


def explain_hooks(
    registry: HooksRegistry,
    event: HookEvent,
    *,
    tool_name: str | None = None,
    prompt: str | None = None,
) -> list[HookExplanation]:
    """dry-run：返回当前事件下「会跑什么 / 为什么会跑 / 拒绝是否有效」。

    与 `run_matching_hooks` 不同——这函数 **不启动子进程**，纯静态。
    用于：
    1. CLI `xuanji hook explain --event PreToolUse --tool run_shell` 排查
    2. 写新 hook 时确认 matcher 写对了
    3. 集成测试不执行 hook 也能断言注册
    """
    out: list[HookExplanation] = []
    can_deny = event == HookEvent.PRE_TOOL_USE
    all_specs = registry.for_event(event)
    matching = registry.matching(event, tool_name=tool_name, prompt=prompt)
    matching_ids = {id(s) for s in matching}
    for spec in all_specs:
        is_match = id(spec) in matching_ids
        if event in (HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE):
            target = tool_name or "<未给出 tool_name>"
            if is_match:
                rule = "*" if spec.matcher == "*" else f"glob {spec.matcher!r}"
                reason = f"tool {target!r} 命中 {rule}"
            else:
                reason = f"matcher {spec.matcher!r} 不匹配 tool {target!r}"
        elif event == HookEvent.USER_PROMPT_SUBMIT:
            target = prompt or "<未给出 prompt>"
            if is_match:
                rule = "*" if spec.matcher == "*" else f"子串 {spec.matcher!r}"
                reason = f"prompt 命中 {rule}"
            else:
                reason = f"matcher {spec.matcher!r} 不在 prompt 里"
        else:
            reason = "Notification 事件只识别 matcher='*'"
        out.append(
            HookExplanation(spec=spec, matched=is_match, reason=reason, can_deny=can_deny),
        )
    return out


__all__ = [
    "HookEvent",
    "HookExplanation",
    "HookResult",
    "HookSpec",
    "HooksFile",
    "HooksRegistry",
    "explain_hooks",
    "run_hook",
    "run_matching_hooks",
]
