"""按模型派发的代码能力强化 prompt。

设计动机
========
玄玑要把 Opus 4.7 / GPT-5.4 这类模型自带的「工程素养」（读前再写、最小改动、
不臆造 API、强制验证）下沉成 system prompt 段，让代码能力相对弱一点的模型
（DeepSeek V4 Pro 是首选场景）也能在玄玑这套调度下输出同等纪律的代码。

只在「写代码 / tool loop / 改 bug」这类技术对话中拼上去——闲聊不需要，
免得把 system prompt 撑爆。

接入方式
========
Conductor 拿到当前 (provider, model) 后调 `code_strength_fragment`，把返回的
段落塞进 `extra_fragments`。返回 None 表示「这模型自带能力够强，不加补丁」。
"""

from __future__ import annotations

# DeepSeek V4 Pro 的代码能力补强段。
# 基于 Opus 4.7 / GPT-5.4 在工程任务上比 V4 Pro 突出的几个差距：
# - 不读上下文就直接改：补「先读后写」
# - 写多余封装与抽象：补「最小改动」
# - 编造不存在的 API：补「不确定就查」
# - 不验证就声称完成：补「闭环验证」
# - 多轮 tool loop 时常忽略前一轮结果：补「读结果再决定」
_DEEPSEEK_V4_CODE_PROMPT = """\
【代码工程素养·V4 Pro 强化段】
1. 写之前先读：改 / 删 / 重构任何文件，先 read_file 看一眼现状再动手；
   不许凭印象直接 write_file。
2. 最小改动：bug 只修 bug，不顺手清周围代码；新功能不引入超出需求的抽象、
   feature flag、向后兼容垫片。三行重复好过一次过早抽象。
3. 不臆造 API：FiveM / QBCore / QBox / ESX / OX 的某个 native / export 不确定时，
   先 lookup_symbol 或 knowledge_search；查不到就标 [unverified]，不许编造。
4. 闭环验证：写完先跑一遍验证再交。
   - FiveM Lua（主要产出）：用 `luacheck` 或 `lua5.4 -bl` 预编译捕语法 / undefined global；
     改了 fxmanifest.lua 必须让小宝在 server console 跑 `restart <resource>` 看日志；
     client / server 双侧脚本要分别检查（`-- client/server` 头不写错）。
   - JSON 配置：用 `python -m json.tool` 或 `lua5.4 -e "json.decode(...)"` 验语法。
   - 玄玑自身代码（Python）：跑 ruff / mypy / pytest 至少一项。
   说「应该能跑」之前先真的跑一下。
5. 多轮 tool loop 节奏：每轮先消化上一轮结果（结果里写了什么、是否符合预期），
   再决定下一步。不要拿到工具结果就立刻再开一发同名工具——先想想结果说了啥。
6. 不写解释 WHAT 的注释：好命名已经说清楚的不重复；只在 WHY 不显然时
   加一行（隐藏约束、特定 bug 的 workaround）。绝不写「TODO 删除」「修复了 issue#X」这种
   会随版本腐烂的注释。
7. 工具调用前先看 schema：不熟的工具用 describe_tool 看完整参数；填空字符串
   或 null 不算"已尝试"，那是把 KeyError 抛给用户。
"""


def code_strength_fragment(provider_name: str, model: str) -> str | None:
    """按 (provider, model) 返回代码强化段，没有匹配返回 None。

    匹配优先级：精确 model id → provider 家族通配。
    """
    name = (model or "").lower().strip()
    prov = (provider_name or "").lower().strip()
    if prov == "deepseek" and (
        name == "deepseek-v4-pro"
        or name.startswith("deepseek-v4")
        or name == "deepseek-reasoner"
    ):
        return _DEEPSEEK_V4_CODE_PROMPT
    return None


__all__ = ["code_strength_fragment"]
