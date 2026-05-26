"""Hooks 子系统单测：HooksRegistry / run_hook / run_matching_hooks。

跨平台考虑：用 python -c "..." 作为 hook 命令。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from xuanji.hooks import (
    HookEvent,
    HookSpec,
    HooksRegistry,
    explain_hooks,
    run_hook,
    run_matching_hooks,
)


def _py(code: str) -> str:
    """构造一条跨平台 hook 命令：python -c '...'"""
    # 用 base64 避免引号嵌套
    import base64
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    return (
        f'{sys.executable} -c "import base64; '
        f'exec(base64.b64decode(\'{encoded}\').decode(\'utf-8\'))"'
    )


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_registry_returns_empty_for_missing_event(tmp_path: Path) -> None:
    reg = HooksRegistry(tmp_path)
    assert reg.for_event(HookEvent.PRE_TOOL_USE) == []


def test_registry_loads_yaml(tmp_path: Path) -> None:
    yaml_text = """\
hooks:
  - matcher: run_shell
    command: echo hi
    timeout: 5
  - matcher: "*"
    command: echo all
"""
    _write_yaml(tmp_path / "PreToolUse.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    specs = reg.for_event(HookEvent.PRE_TOOL_USE)
    assert len(specs) == 2
    assert specs[0].matcher == "run_shell"
    assert specs[0].timeout == 5
    assert specs[1].matcher == "*"


def test_registry_caches_by_mtime(tmp_path: Path) -> None:
    p = tmp_path / "PreToolUse.yaml"
    _write_yaml(p, "hooks:\n  - matcher: '*'\n    command: echo\n")
    reg = HooksRegistry(tmp_path)
    a = reg.for_event(HookEvent.PRE_TOOL_USE)
    b = reg.for_event(HookEvent.PRE_TOOL_USE)
    assert a == b
    # mtime 不变，应走缓存
    assert HookEvent.PRE_TOOL_USE in reg._cache


def test_registry_handles_bad_yaml(tmp_path: Path) -> None:
    """坏 YAML 不应抛——hook 故障不能锁死会话。"""
    _write_yaml(tmp_path / "PreToolUse.yaml", "hooks: [unclosed")
    reg = HooksRegistry(tmp_path)
    assert reg.for_event(HookEvent.PRE_TOOL_USE) == []


def test_matching_pre_tool_use_glob(tmp_path: Path) -> None:
    yaml_text = """\
hooks:
  - matcher: run_*
    command: echo hi
  - matcher: read_file
    command: echo r
"""
    _write_yaml(tmp_path / "PreToolUse.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    specs = reg.matching(HookEvent.PRE_TOOL_USE, tool_name="run_shell")
    assert len(specs) == 1
    assert specs[0].matcher == "run_*"


def test_matching_user_prompt_substring(tmp_path: Path) -> None:
    yaml_text = """\
hooks:
  - matcher: 部署
    command: echo deploy
  - matcher: "*"
    command: echo all
"""
    _write_yaml(tmp_path / "UserPromptSubmit.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    specs = reg.matching(HookEvent.USER_PROMPT_SUBMIT, prompt="把这个部署到生产")
    matchers = {s.matcher for s in specs}
    assert "部署" in matchers
    assert "*" in matchers


@pytest.mark.asyncio
async def test_run_hook_success(tmp_path: Path) -> None:
    spec = HookSpec(matcher="*", command=_py("print('ok')"), timeout=10)
    res = await run_hook(spec, {"foo": "bar"}, cwd=tmp_path)
    assert res.exit_code == 0
    assert "ok" in res.stdout


@pytest.mark.asyncio
async def test_run_hook_exit_2_means_deny(tmp_path: Path) -> None:
    spec = HookSpec(
        matcher="*",
        command=_py("import sys; sys.exit(2)"),
        timeout=10,
    )
    res = await run_hook(spec, {}, cwd=tmp_path)
    assert res.exit_code == 2
    assert res.denied


@pytest.mark.asyncio
async def test_run_hook_json_decision_deny(tmp_path: Path) -> None:
    spec = HookSpec(
        matcher="*",
        command=_py('import json; print(json.dumps({"decision":"deny","reason":"test"}))'),
        timeout=10,
    )
    res = await run_hook(spec, {}, cwd=tmp_path)
    assert res.exit_code == 0
    assert res.decision == "deny"
    assert res.reason == "test"
    assert res.denied


@pytest.mark.asyncio
async def test_run_hook_timeout(tmp_path: Path) -> None:
    spec = HookSpec(
        matcher="*",
        command=_py("import time; time.sleep(5)"),
        timeout=0.5,
    )
    res = await run_hook(spec, {}, cwd=tmp_path)
    assert res.error is not None
    assert "超时" in res.error
    assert not res.denied  # error 状态不算 deny


@pytest.mark.asyncio
async def test_run_hook_receives_payload_via_stdin(tmp_path: Path) -> None:
    code = "import sys, json; d = json.load(sys.stdin); print(d['tool'])"
    spec = HookSpec(matcher="*", command=_py(code), timeout=10)
    res = await run_hook(spec, {"tool": "run_shell"}, cwd=tmp_path)
    assert "run_shell" in res.stdout


@pytest.mark.asyncio
async def test_run_matching_hooks_runs_all_in_order(tmp_path: Path) -> None:
    yaml_text = (
        "hooks:\n"
        f"  - matcher: run_shell\n"
        f"    command: {json.dumps(_py('print(1)'))}\n"
        f"  - matcher: '*'\n"
        f"    command: {json.dumps(_py('print(2)'))}\n"
    )
    _write_yaml(tmp_path / "PreToolUse.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    results = await run_matching_hooks(
        reg,
        HookEvent.PRE_TOOL_USE,
        {"tool": "run_shell"},
        cwd=tmp_path,
        tool_name="run_shell",
    )
    assert len(results) == 2
    assert "1" in results[0].stdout
    assert "2" in results[1].stdout


# ---- explain_hooks（dry-run）----


def test_explain_returns_empty_when_no_hooks(tmp_path: Path) -> None:
    reg = HooksRegistry(tmp_path)
    assert explain_hooks(reg, HookEvent.PRE_TOOL_USE, tool_name="run_shell") == []


def test_explain_pre_tool_use_match_and_miss(tmp_path: Path) -> None:
    yaml_text = """\
hooks:
  - matcher: run_*
    command: echo a
  - matcher: read_file
    command: echo b
"""
    _write_yaml(tmp_path / "PreToolUse.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    explanations = explain_hooks(reg, HookEvent.PRE_TOOL_USE, tool_name="run_shell")
    assert len(explanations) == 2

    by_matcher = {e.spec.matcher: e for e in explanations}
    assert by_matcher["run_*"].matched is True
    assert "命中" in by_matcher["run_*"].reason
    assert by_matcher["run_*"].can_deny is True

    assert by_matcher["read_file"].matched is False
    assert "不匹配" in by_matcher["read_file"].reason
    assert by_matcher["read_file"].can_deny is True


def test_explain_post_tool_use_cannot_deny(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "PostToolUse.yaml",
        "hooks:\n  - matcher: '*'\n    command: echo p\n",
    )
    reg = HooksRegistry(tmp_path)
    explanations = explain_hooks(reg, HookEvent.POST_TOOL_USE, tool_name="run_shell")
    assert len(explanations) == 1
    assert explanations[0].matched is True
    assert explanations[0].can_deny is False


def test_explain_user_prompt_substring_match(tmp_path: Path) -> None:
    yaml_text = """\
hooks:
  - matcher: 部署
    command: echo deploy
  - matcher: SECRET
    command: echo block
"""
    _write_yaml(tmp_path / "UserPromptSubmit.yaml", yaml_text)
    reg = HooksRegistry(tmp_path)
    explanations = explain_hooks(
        reg, HookEvent.USER_PROMPT_SUBMIT, prompt="把这个部署到生产",
    )
    by_matcher = {e.spec.matcher: e for e in explanations}
    assert by_matcher["部署"].matched is True
    assert by_matcher["部署"].can_deny is False
    assert by_matcher["SECRET"].matched is False
