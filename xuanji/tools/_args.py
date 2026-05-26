"""共享参数校验工具。

模型流式 tool_call 偶尔会发出 args 残缺的调用（DeepSeek 流截断、JSON 解析回退到 {}），
之前直接 args["xxx"] 会抛 KeyError 把堆栈砸到小宝脸上；现在统一返回友好 ToolResult，
模型在下一轮自然会重提一次。
"""

from __future__ import annotations

from typing import Any

from xuanji.capability.tool import ToolResult


def require_str(
    args: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> tuple[str | None, ToolResult | None]:
    """取必填字符串。缺失或类型不对返回 ok=False ToolResult，模型会重新填。

    `allow_empty=True` 允许空串（如 write_file 的 content）；默认不允许（如 path）。
    """
    if key not in args:
        return None, ToolResult(
            ok=False,
            error=f"missing required arg: '{key}'。请重新提交并带上 {key} 字段。",
        )
    raw = args[key]
    if raw is None:
        return None, ToolResult(
            ok=False,
            error=f"arg '{key}' 不能为 null。",
        )
    if not isinstance(raw, str):
        return None, ToolResult(
            ok=False,
            error=f"arg '{key}' 必须是字符串，收到 {type(raw).__name__}。",
        )
    if not allow_empty and raw == "":
        return None, ToolResult(ok=False, error=f"arg '{key}' 不能为空字符串。")
    return raw, None


def require_dict(
    args: dict[str, Any],
    key: str,
) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """取必填 dict。"""
    if key not in args:
        return None, ToolResult(
            ok=False,
            error=f"missing required arg: '{key}'。请重新提交并带上 {key} 字段。",
        )
    raw = args[key]
    if not isinstance(raw, dict):
        return None, ToolResult(
            ok=False,
            error=f"arg '{key}' 必须是 object，收到 {type(raw).__name__}。",
        )
    return raw, None
