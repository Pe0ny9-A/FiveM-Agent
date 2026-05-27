# 玄玑 · CHANGELOG

所有重要的变更都记在这里。版本号遵守 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.2.0] — 2026-05-27

**工具自愈 + 知识库扩源 + 群英会深度协作**。这一版把内核的"长尾自治力"补齐：工具工厂能自动跨 LLM 修自己写出来的烂代码、知识库覆盖到 QBox/ESX/oxmysql/natives 全栈、sub-agent 能递归召唤同伴让长任务真正可拆。

### Added · ToolFactory 三轮自修复回路（[xuanji/tools/tool_factory.py](xuanji/tools/tool_factory.py)）

- 新方法 `repair(slug)`：当 `test()` 失败，把 broken code + pytest log 喂回 LLM，要它在原方案上改一版。
- 新方法 `autofix(slug, max_rounds=3)`：把 generate → test → (fail) repair → test 串成一条流水线，最多重试 N 轮，最后一轮仍失败就标 `failed_after_retries` 让小宝介入。
- `FactoryStatus` 持久化新增 `repair_rounds` / `repair_log` / `last_test_output` / `last_test_passed` 字段，DB 层用 `_ensure_columns(conn)` 做 PRAGMA 表结构迁移，老用户零打扰升级。
- 新 CLI：`xuanji tool autofix <slug> [--max-rounds 3]`，带 Rich Panel 显示每轮修复尝试 + 最终 pytest 输出。
- 22 个 tool factory loop 单测全绿（含 5 个新 autofix 测）。

### Added · FiveM 知识库 SkillGraph 扩源（[xuanji/knowledge/sources/seeds.py](xuanji/knowledge/sources/seeds.py)）

- 新增 4 个命名空间：`fivem.qbox@main` / `fivem.esx@1.13` / `fivem.oxmysql@2.x` / `fivem.natives@latest`。
- 27 条新 Symbol：QBox 4 个 export、ESX 6 个核心 API、oxmysql 6 个查询函数、FiveM natives 11 个高频函数（PlayerPedId / GetEntityCoords / TriggerEvent 等）。
- 8 条新 Chunk 概念卡：QBox 与 QBCore 迁移指南、框架选型对照、oxmysql 事务模式、FiveM 事件流 / 线程模型 / 坐标系。
- 让稷下生在 `lookup_symbol` / `knowledge_search` 时多框架直接命中，不再"答非所问 ESX 而代码是 QBox"。

### Added · 群英会深度协作（[xuanji/ensemble/supervisor.py](xuanji/ensemble/supervisor.py)）

- `DispatchSubagentTool` 增加 `depth` / `max_depth` / `parent_role` 三个字段，每次召唤 sub-agent 时把下一层 `dispatch_subagent`（depth+1）注入它的工具集，**让稷下生可以中途召唤百工匠落地代码**。
- `max_depth` 默认 2，达到上限 dispatch 工具自身报 ToolError 拒绝继续，避免无限递归。
- 输出新增 `depth` + `parent_role` 元信息，transcript 串得起整条链路。
- `JIXIA_ROLE` / `TIANSHU_ROLE` 的 `allowed_tools` 加 `dispatch_subagent`：稷下生查完可叫百工匠写代码、天枢令拆完计划可叫稷下生先验证某个阶段。
- 6 个 `tests/test_subagent_recursion.py` 新单测覆盖深度限制 / 元信息透出 / nested 注入。

### Added · 规则启发式语义压缩（[xuanji/neural/compaction.py](xuanji/neural/compaction.py)）

- 新增 `score_message(msg, *, later_messages)` 三维打分：含工具调用 +0.35 / 文本长度线性 0..0.30 / 关键词被后续消息引用 +0.35，归一到 0..1。
- `compact_history()` 依分数挑摘要长度——高分（≥0.7）原样保留 240 字 ★ 标记，低分（≤0.25）且无工具调用的直接丢弃，中分用短摘要 · 标记。
- `CompactionConfig` 新增 `importance_high_threshold` / `importance_low_threshold` 两个旋钮。
- 还是不调 LLM 做摘要——零依赖、零额外 token，M5+ 想升级时只换 `_summarize_pair`。
- 16 个 `tests/test_compaction.py` 单测（5 个新测覆盖打分各维度 + ★/· 标记 + 低分丢弃）。

### Fixed · 模块循环导入

- `xuanji/neural/__init__.py` 改用 `__getattr__` 懒加载 `Conductor` / `SessionCtx`，破解 `xuanji.config.store → xuanji.neural.compaction → xuanji.neural.__init__ → conductor → providers.factory` 的环路。
- 直接 `from xuanji.neural import Conductor` 仍兼容；`from xuanji.neural.compaction import …` 不再触发 conductor 导入。

### Tests

- 全套：**529 passed / 1 skipped**，ruff + mypy strict 全绿。
- 新增：22 工厂循环测、6 递归 dispatch 测、5 压缩打分测、知识库 1 个综合扩源测。

## [1.1.0] — 2026-05-27

**工作台体验三件套**：聊天活动状态栏 + 会话窗口持久化 + Profiles 可用模型检测与 Anthropic 线协议支持。这一版把 cc switch 类工具的「填了 key 不知道能不能用」痛点彻底封死。

### Added · 输入框下方活动状态栏（apps/vscode/webview/）

- 仿 Claude Code 的状态条，挂在 [ChatTab.tsx](apps/vscode/webview/src/tabs/ChatTab.tsx) 输入框正下方。
- 实时呈现最新一条 assistant 消息的工具事件（最多 6 条）：
  - 📖 `read_file` → 显示路径 + 行号范围，可点击跳转
  - ✏️ `write_file` → 显示路径，可点击
  - 📁 `list_dir` → 显示目录
  - 🔍 `ripgrep` → 显示 pattern + 路径
  - `$` `run_shell` → 显示完整命令（不可点）
- 状态指示：⏳ 运行中 / 🔒 被 Gate 拦 / ✓ 成功 / ✗ 失败 + 耗时。
- 闲置时显示「玄玑闲着 · 等小宝下个指令」。

### Added · 会话窗口持久化（apps/vscode/webview/src/chatStore.ts）

- 用 `vscode.setState/getState` 把会话列表（标题 / profile / 消息历史）持久化到 webview state，关闭 VS Code 重开仍在。
- 后端 `session_id` 重启即失效——恢复出来的会话标记 `archived=true`，小宝首次发送时自动 `chat.start` 拿新 id 接上，对话历史前端保留、不打断。
- 同步去抖（200ms）写入，避免每次 delta 都 setState。
- 新增 `hydrate()` 入口，`ChatTab` 在 hydrate 完成前不会自动建新会话——之前会一次开 2 个空会话。

### Added · Profiles 可用模型检测（参考 cc switch / OneAPI）

- 新增 `OpenAICompatibleProfile.wire_format` 字段：
  - `openai`（默认）→ POST `/v1/chat/completions`
  - `anthropic` → POST `/v1/messages`，给 NewAPI/OneAPI 转发的 Claude 端点用
- factory 自动按 wire_format 选 Provider：openai-compatible + anthropic 协议会复用 AnthropicProvider，享受 Extended Thinking / Prompt Cache。
- 新增 [xuanji/config/probe.py](xuanji/config/probe.py)：纯 httpx 实现 `list_models()` 与 `ping()`，8 秒超时，认证头按 wire_format 自动切换（`x-api-key`+`anthropic-version` vs `Authorization: Bearer`）。
- 新增两个 IPC 方法（[ipc/config_methods.py](xuanji/ipc/config_methods.py)）：
  - `profiles.list_models` —— 拉端点返回的模型清单
  - `profiles.test` —— 1 token 握手验证 api_key + wire_format 联通，返回 latency_ms / status / error
- 两者都支持「编辑中实时探测」：传 `name` 用已存的 key，传完整字段则用临时 profile，新建时填一半就能预览。

### Added · Profiles 编辑器升级（apps/vscode/webview/src/tabs/ProfilesTab.tsx）

- 选 `openai-compatible` 时新增 `wire_format` 下拉。
- `default_model` 旁边「拉取」按钮：调 `profiles.list_models` 后变成下拉框，自动挑第一个填上。
- 「🔌 测试连接」按钮：实时显示 ✓ 连通 + 延迟 + HTTP 状态码 / ✗ 错误信息。
- 列表卡片显示 wire 协议徽标。

### Tests

- 新增 `tests/test_config_probe.py` 共 7 个测：URL 拼接、`/data` vs 顶层 list 解析、anthropic/openai 200/401、wire_format=anthropic 时确实打 `/v1/messages` 且带 `x-api-key`。
- 全套：**507 passed / 1 skipped**，ruff + mypy strict 全绿。

## [1.0.1] — 2026-05-27

**vibe coding 主动摸底 + 工作台对话 UI 修复**。1.0.0 装机后两个真实痛点的快速跟进。

### Fixed · 工作台对话 UI（apps/vscode/）

- 用户消息气泡之前用 `bg-vsaccent/90`（accent 蓝），在某些 VS Code 主题下底色透明度处理后跟背景区分不明显，看起来像"消息发出去就消失了"。
- 改成左对齐 + 顶部带角色徽标——「**小宝**」蓝色 / 「**玄玑**」绿色，用户气泡用 `bg-vsinput`，符合主流聊天软件视觉。
- 影响：[ChatTab.tsx#L328](apps/vscode/webview/src/tabs/ChatTab.tsx#L328) 的 MessageBubble 组件。

### Added · vibe coding 主动摸底（xuanji/persona/）

- 1.0.0 的 CHAT 模式 brief 只写了"闲聊 + 撒娇"，模型读完默认就只闲聊；
  小宝丢一句「熟悉一下项目」，玄玑会有思考有回复但完全不动手翻文件。
- [modes.py:41](xuanji/persona/modes.py#L41) CHAT brief 改写：动词信号（看 / 摸 /
  搞 / 试 / 跑 / 熟悉 / 检查 / 整一下）+ 名词信号（项目名 / resource 名 / 文件名）
  自动触发"动手"行为。"姐姐先扫一眼"等口头禅必须真的调工具。
- [xuanji.py:31](xuanji/persona/xuanji.py#L31) 新增「模糊指令处理原则（vibe
  coding 必读）」一整段：不反问澄清、入项目首动作有套路（list_dir 根 →
  XUANJI.md → CLAUDE.md → README.md → fxmanifest.lua → 关键入口）、闭环原则。
- 改的是原则不是关键词列表，避免下一次小宝换说法就漏掉。

### Notes

- 后端 1.0.1 / VS Code 插件 1.0.1 同步发布；
- 三件套全绿：509 单测 / 106 模块 mypy strict / ruff 零告警。

## [1.0.0] — 2026-05-26

**VS Code 插件正式版 · 现代化工作台 · 全家桶可视化配置 · 议会式群英会**。

1.0 是从 0.5 那个"状态栏 + 三栏仪表盘 + 五件套命令"的最小集，升级成一个独立、
现代化、简约高级的 React 工作台——所有 0.5 留下的承诺都在这一版兑现：多会话
聊天、可视化 Skills/MCP/Hooks 配置、随时切模型、Council 议会进度可视化、
状态栏 token / profile 实时显示、对话内点击跳转源码。零分叉地复用同一个 IPC
后端，CLI / FastAPI / VS Code 三个入口共享同一个 ServerRuntime。

### Added · 现代化 React 工作台（apps/vscode/）

- **Vite 5 + React 18 + Tailwind 3 + Zustand 4** 全新前端栈，替换 0.5 的纯
  HTML/JS 三栏仪表盘。打包产物 196KB（gzip 60KB），冷启 < 200ms。
- **侧边栏视图 + 独立 panel 双形态**：activitybar 一颗北斗图标常驻，命令
  「玄玑：打开工作台」开独立大窗。状态保留（retainContextWhenHidden）。
- **VS Code 主题原生融合**：Tailwind tokens 全量映射到 `var(--vscode-*)`，
  暗色 / 亮色 / 高对比主题一键跟随。

### Added · 多会话聊天（chat 标签）

- 左侧 44 宽 session 列表，「+ 新会话」下拉直接选 profile 启会，双击改名，
  × 关闭。每个 session 独立消息流，互不影响。
- **会话内切换 profile**：header 上 profile 按钮点开下拉，选中后 close 旧 →
  start 新，消息流注入一行「已切换到…」分隔标记。
- 流式渲染：text_delta / thinking_delta 分块累积；`<details>` 折叠思考；
  工具调用以 chip 形式插入消息流，状态色（蓝=运行中 / 黄=被拦 / 绿=成功 /
  红=失败）+ 耗时 / args 折叠。
- **司辰阁 HITL 卡**：高危操作时在消息流里插一张橙色卡，批准 / 拒绝直送
  `chat.hitl_response`，无需弹窗打断。
- 末尾用量栏：`stop=end_turn · in 1.2k · out 460`。
- **对话内 [文件名](路径#L42-51) 点击跳转**：极轻量 markdown 解析（链接 +
  ```fence```），命中链接 postMessage 触发 `xuanji.openFile` 命令，主进程
  resolve 相对路径 + setSelection + revealRange 居中显示。

### Added · 群英会议会面板（council 标签）

- 配题 + 选议员（角色 × profile_override × 侧重提示）+ 设超时 → 一键
  「召开议会」。最少 2 名议员，可任意增减。角色：稷下生 / 百工匠 / 司鉴 /
  天枢令。
- **进度卡实时刷新**：订阅 `ensemble.council_started` /
  `ensemble.councilor_started|done` / `ensemble.council_judging` /
  `ensemble.council_done`，每名议员一张状态卡，进行中 → 完成 / 失败着色。
- **裁决书展示**：议会结束后展开 Verdict——summary、chosen_path、
  consensus_points、divergence_points、risks、decided_by、耗时 + memory_id。
- 「展开议员陈词」折叠区显示每位议员的 final_text，便于复盘。

### Added · 全家桶可视化配置

| 标签 | 能做什么 |
|---|---|
| **Profiles** | 列出所有 profile + 激活态徽章 / 新增编辑 (anthropic / openai / deepseek / openai-compatible 四档) / 切换激活 / 删除。api_key password 输入；编辑时 name 锁死。|
| **Skills** | 列出 skills 目录下所有 SKILL.md，点开看 frontmatter + body。错误项分组提示。|
| **MCP** | 列出已注册 MCP server / 启用 toggle / 编辑 / 删除。stdio 模式管 command/args/cwd/env，http\|sse 模式管 url。|
| **Hooks** | 四个事件卡（PreToolUse/PostToolUse/UserPromptSubmit/Notification），每张卡支持新增 / 修改 / 移除 hook 条目（matcher / command / timeout / description），整体覆盖式保存。|

所有面板都直接调 IPC RPC，不走对话——按钮点完立即生效。

### Added · 状态栏增强

- 三段联动显示：`✨ 玄玑 · {profile} · {framework}/{inv}/{target} · ↑1.2k ↓460`
- 工具运行中切换 `$(sync~spin)` 旋转图标
- 订阅 `chat.message_done` 自动更新最近一轮 token；`chat.tool_run_started`
  / `chat.turn_done` / `chat.error` 切 busy 态
- Tooltip 五段式：profile / project 详情 / 最近 token / stop_reason 全展开

### Added · IPC 后端复用

- VS Code 插件通过 stdio JSON-RPC 接 `xuanji ipc`，零分叉复用 0.5 起就锁定
  的 22 个 RPC 方法 + 0.6 起补的 config/profiles/mcp/hooks/skills CRUD。
  插件本身零模型依赖，token 消耗都在内核侧计算。
- `chat.*` 与 `ensemble.*` notification 通过 [server.py](xuanji/ipc/server.py)
  的 Notifier 推送，[workbench.ts](apps/vscode/src/workbench.ts) 集中订阅 +
  广播给所有 webview，避免重复连接。
- `xuanji.openFile` 命令通过白名单 postMessage 桥暴露给 webview，但 webview
  只能调 `xuanji.*` 前缀命令，不能任意触发 vscode API。

### Notes

- VS Code 插件版本号同步升至 1.0.0，作为对外发布的第一个完整版本。
- Python 内核版本 1.0.0：质量门 509 单测全绿，ruff / mypy strict 零告警。
- 后续 1.1+ 计划：Tauri 桌面端跟进（共享 webview 产物）、Web 端独立部署、
  voice 语音入口适配器。

## [0.9.3] — 2026-05-26

**全家桶自配置 + 默认 DeepSeek V4 Pro + 代码强化段 + 四个真实会话 bug 修复**。

0.9.3 是从一次 DeepSeek V4 Pro 真实会话里捞出来的反馈版：四个用户实际踩到的坑
（KeyError / 复读 / ctx% 不准 / 状态栏乱跳）一次修齐，顺手把"让玄玑用自然语言
帮自己改配置"补上，再把默认路由从 Anthropic 优先改成 DeepSeek 优先——配上一段
代码工程素养强化 prompt，让 V4 Pro 在玄玑调度下输出和 Opus 4.7 / GPT-5.4 同等
纪律的代码。

### Fixed · 四个 0.9.2 真实会话 bug

- **#4 KeyError 'path'**：流式工具调用 args 截断时 `args["path"]` 直接抛
  `KeyError`，玄玑当场崩。新增 [xuanji/tools/_args.py](xuanji/tools/_args.py)
  共享的 `require_str` / `require_dict` —— 缺字段返回友好的
  `ToolResult(ok=False, error=...)` 让模型有机会重试，而不是吐 traceback。
  builtin / factory / ingest / 知识 / 元工具全量切换。
- **#3 复读**：多轮 tool loop 第二轮模型偶尔逐字复读上一轮句子。两层防护：
  - system prompt 加「多轮 tool loop 不复读」硬约束
  - [xuanji/cli.py](xuanji/cli.py) 的 `_PrefixDedup` 流式前缀去重兜底，
    本轮输出与上轮完整重叠时静默吃掉
- **#1 ctx% 不准**：状态栏 `ctx 12% (10.1k/80.0k)` 用的是 compaction 阈值
  当分母，不是真模型上下文窗口。拆成两个概念：
  - **window %** = 真上下文（按 model 的 max_tokens）
  - **compact 阈值** = `compaction.max_context_tokens`（什么时候自动折叠）
  状态栏现在两个都显示，一眼看出"还能塞多少"和"什么时候被折叠"。
- **#2 状态栏跳来跳去**：状态栏只在每轮回复后渲染一次，用户敲下一条时
  上一栏被推到屏幕中段。改成每次 `console.input()` 前都重渲染，
  状态栏永远贴在输入框正上方。

### Added · 全家桶自配置（10 个工具）

让玄玑用自然语言给自己改配置——profile / 人设温度 / 聊天 UI / compaction /
MCP / hook 全家桶都能聊出来。新模块 [xuanji/tools/config_tools.py](xuanji/tools/config_tools.py)：

| 工具 | Risk | 作用 |
|---|---|---|
| `list_profiles` | SAFE | 看所有 profile + 当前激活 |
| `switch_profile` | IO | 切换激活 profile（HITL 确认） |
| `show_active_config` | SAFE | 当前 profile / 模式 / compaction / MCP / chat_ui 一览 |
| `set_chat_ui` | IO | `show_thinking` 开关 |
| `set_compaction` | IO | `enabled` / `max_context_tokens` / `keep_recent_turns` |
| `set_persona_temperature` | IO | playful / balanced / professional |
| `set_alias` | IO | 改 user_alias / assistant_alias |
| `set_mcp_enabled` | IO | 启停某 MCP server |
| `list_hooks` | SAFE | 看一个或所有事件的 hook |
| `install_hook` | IO | 写/追加 YAML hook spec |

所有写工具都标 `RiskTag.IO`——必经司辰阁 HITL，玄玑改不了任何东西不弹确认。
小宝可以说："姐姐，把 compaction 阈值降到 60k，关掉 thinking 显示，
切到 deepseek profile"，玄玑会一条条调，每条都要小宝点一次确认。

### Changed · 默认 DeepSeek V4 Pro + 代码强化段

[xuanji/llm/router.py](xuanji/llm/router.py) `default_policies()`：

| 场景 | 0.9.2 | 0.9.3 |
|---|---|---|
| `dev` / `tool-loop` | Anthropic → OpenAI | **DeepSeek** → Anthropic → OpenAI |
| `researcher-tool-loop` | Anthropic | **DeepSeek** → Anthropic |
| `summary-bulk` | DeepSeek → Anthropic | 不变 |
| `routing-decision` | DeepSeek → Anthropic | 不变 |
| `long-context-architecture` | Anthropic → OpenAI | 不变（200k+ 仍走 Opus 1M） |
| `planning-strategic` | Anthropic → DeepSeek | 不变（规划要看远） |
| `reviewer-strict` | Anthropic → OpenAI | + DeepSeek 兜底 |

新模块 [xuanji/persona/code_strength.py](xuanji/persona/code_strength.py)：
按 `(provider, model)` 派发的代码能力强化段，由 [Conductor._system_prompt](xuanji/neural/conductor.py)
每轮注入。**只对 DeepSeek thinking 模型**（`deepseek-v4-pro` / `deepseek-v4-*` /
`deepseek-reasoner`）拼上去——Anthropic / OpenAI 自带这层素养，重复加反而干扰；
legacy `deepseek-chat` 没 thinking，也不强加。

强化段七条工程铁律（基于 V4 Pro 与 Opus 4.7 / GPT-5.4 的实际差距）：

1. 写之前先读：read_file 看一眼现状再 write_file，不许凭印象
2. 最小改动：bug 只修 bug，不引入超出需求的抽象
3. 不臆造 API：FiveM / QBCore / ox_lib 的 native / export 不确定先 lookup_symbol
4. 闭环验证：FiveM Lua 用 `luacheck` / `lua5.4 -bl` 验语法，改 fxmanifest 让小宝
   `restart <resource>` 看日志；JSON 用 `python -m json.tool` 验；玄玑自身代码
   （Python）跑 ruff / mypy / pytest 至少一项
5. 多轮 tool loop 节奏：每轮先消化上一轮结果再决定下一步
6. 不写解释 WHAT 的注释：好命名已经说清楚的不重复
7. 工具调用前先看 schema：不熟的工具先 `describe_tool`

### 质量

| | |
|---|---|
| 单测 | **466 全过**（407 → 466，+59：27 config_tools + 19 v0.9.3 回归 + 13 router/code_strength） |
| ruff | **0 告警** |
| mypy strict | **0 告警** |
| 工具数 | 静态 41（+ 10 全家桶 config_tools）+ published 动态加载 |

### 升级提示

- 装完直接 `xuanji chat`，dev 类对话默认走 DeepSeek V4 Pro（如果你配了 DeepSeek profile）。
- 没配 DeepSeek 不影响——router 自动降级到 Anthropic / OpenAI，行为完全等同 0.9.2。
- 想让玄玑改自己的配置：`xuanji chat` 里直接说 "姐姐，把 thinking 关了" 就行，
  Gate 会弹出确认面板让你点一下。

---

## [0.9.2] — 2026-05-26

**项目级 XUANJI.md 项目宪法 + CLI 对话状态栏 + 思维链开关 + 会话恢复**。

0.9.x 之前玄玑只读用户级偏好，跨项目时容易把 QBox 项目的约定带到 ESX 项目里。
0.9.2 引入**项目级 XUANJI.md**：进哪个项目就读哪个，权重高于用户级，专治"这个项目用 QBox 不是 QBCore"
反复要再说一遍的痛点。同时把 CLI 对话体验也补齐：底部状态栏一眼看到 token、上下文占用、模式、模型。

### Added · 项目级 XUANJI.md（项目宪法）

- 新模块 [xuanji/persona/project_memory.py](xuanji/persona/project_memory.py)：
  从 cwd 沿目录树最多 12 层向上找 `XUANJI.md`，命中即停。
- **优先级**：用户级先注入 → 项目级后注入（model 对靠后的 prompt 更敏感，
  自然实现"局部覆盖全局"）。
- 在 [Conductor.__init__](xuanji/neural/conductor.py#L180) 启动期采集一次缓存进 `_xuanji_md_fragments`，
  每条消息前都拼到 system prompt extras 里（位于 `static_extra` 之后、reflux 之前）。
- 默认模板会用 `detect_fivem_context` 结果填好 framework / inventory / target 字段，
  detector 失败用占位符不阻塞 init。

### Added · `xuanji project` CLI 子命令

- `xuanji project init [--overwrite]` — 在当前 cwd 写 XUANJI.md 模板
- `xuanji project show` — 打印当前项目级 + 用户级 XUANJI.md 内容
- `xuanji project path` — 列出查找路径与命中位置
- `xuanji project edit` — 用 `$EDITOR` 打开编辑（Windows 兜底 notepad）

### Added · 玄玑可调用的项目记忆工具

- `read_project_memory`（RiskTag.SAFE）— 玄玑回答前可先看项目宪法
- `init_project_memory`（RiskTag.IO）— 用户说"帮我熟悉这个项目"时玄玑可主动写

均在 [xuanji/tools/project.py](xuanji/tools/project.py)，已注入 [ServerRuntime.build_registry](xuanji/server/runtime.py)。

### Added · CLI 对话底部状态栏

每轮回复后渲染一行紧凑状态栏（[xuanji/cli.py](xuanji/cli.py) 的 `_print_status_bar`）：

```
  claude-sonnet-4-6@anthropic  ·  本轮 in 1.2k  out 567  cache 8.9k↓  ·
  累计 7.0k (in 5.0k / out 2.0k / cache 12.0k)  ·  ctx 12% (10.1k/80.0k)  ·
  3 轮  ·  8 msg  ·  chat/balanced  ·  think off  ·  default
```

- 模型 / provider / 本轮 token（in/out/cache↓↑）
- 累计 token、ctx 占用百分比（按 `compaction.max_context_tokens` 算，绿/黄/红三档）
- 轮数 / history 长度 / persona mode/temperature / `think on/off` / profile 名
- `_format_tokens` 大数字带 k/M 后缀让一行装得下
- 新增 `/stats` 斜杠命令随时拉出来看

### Added · `/think` 思维链开关 + 会话恢复

- `/think on|off` 切换思维块显示，状态落 `chat_ui.show_thinking` 跨会话保留
- 退出后写 `last_session.json` 快照，下次启动若 profile/model 一致会问要不要恢复
- `/forget` 清掉磁盘快照

### 单测

- `tests/test_project_memory.py` — 12 个：树向上查找 / 空文件视为缺失 / 用户/项目顺序 / init 拒绝覆盖 / 自定义内容 / 模板字段替换
- `tests/test_project_memory_tools.py` — 7 个：read 命中/缺失、init 创建/拒绝/覆盖/自定义

### 修复 · 循环导入

`Conductor.__init__` 通过 `xuanji.persona.project_memory` 触发了
`xuanji.config.__init__ → store → compaction → neural → conductor` 的循环。
解法：把 `from xuanji.persona.project_memory import collect_xuanji_fragments`
**移到 `__init__` 方法体内**做延迟 import（[conductor.py:183](xuanji/neural/conductor.py#L183)），
等 module 全加载完再触发，循环就断了。

### 质量

| | |
|---|---|
| 单测 | **407 全过**（379 → 407，+28：19 项目记忆 + 状态栏/思维链/会话恢复回归） |
| ruff | **0 告警** |
| mypy strict | **0 告警** |
| 工具数 | 静态 31（新增 `read_project_memory` / `init_project_memory`）+ published 动态加载 |
| CLI 命令族 | 13（新增 `project`）|

### 升级提示

- 升完后到任意 FiveM 项目根跑 `xuanji project init`，玄玑下一次进这个目录会自动读到。
- 状态栏自动出现，无需配置；想看自定义统计直接打 `/stats`。
- 用户级 XUANJI.md 默认不存在；想加全局偏好可写到
  `%APPDATA%\xuanji\XUANJI.md`（macOS / Linux 同 config_dir）。

---

## [0.9.1] — 2026-05-26

**三家 Provider 各自适配，每家发挥最强性能 + 上下文自动压缩**。

0.9.0 之前 DeepSeek 与 OpenAI 共用一个 Provider，导致 DeepSeek thinking 模型在多轮
对话第二轮报 `BadRequestError 400 — The reasoning_content in the thinking mode
must be passed back to the API`——message 编码层把 ThinkingBlock 直接丢了。
0.9.1 把三家 Provider 拆开各自专精，并把 thinking / cache / 上下文压缩做成一等公民。

### Fixed

- **DeepSeek thinking 多轮 400 报错**：`reasoning_content` 现在双向往返 —— 解析时
  抽到 ThinkingBlock，编码时写回 assistant 消息的 `reasoning_content` 字段。流式
  里也分发 `thinking_start / thinking_delta / thinking_end` 事件。
  ([xuanji/llm/providers/deepseek.py](xuanji/llm/providers/deepseek.py))

### Changed · 三家 Provider 各自分工

| Provider | 文件 | 独门特性（一等公民） |
|---|---|---|
| Anthropic | `xuanji/llm/providers/anthropic.py` | `thinking_budget=N` 自动展开为 `thinking={"type":"enabled","budget_tokens":N}` + 强制 `temperature=1`；`cache_system=True` 把 system 包成 `cache_control` ephemeral 块 |
| OpenAI | `xuanji/llm/providers/openai.py` | `_is_reasoning_model()` 识别 o1/o3/o4/gpt-5 系列，自动把 `max_tokens` 迁到 `max_completion_tokens`；`prompt_tokens_details.cached_tokens` 计入 Usage |
| DeepSeek | `xuanji/llm/providers/deepseek.py` **(新)** | `reasoning_content` 双向往返；`prompt_cache_hit_tokens` 计入 `cache_read_tokens`；流式时 thinking 段先于 text/tool 段 |

`factory.py` 路由：DeepSeekProfile → DeepSeekProvider，不再共用 OpenAIProvider。

### Added · 自动识别带缓存的模型

[Conductor](xuanji/neural/conductor.py) 每轮请求前查 `provider.capabilities(model).supports_prompt_cache`，
Anthropic 自动注入 `cache_system=True`；OpenAI / DeepSeek 是自动 prefix cache 不需要参数。

### Added · 上下文自动压缩

新模块 [xuanji/neural/compaction.py](xuanji/neural/compaction.py)：

- `CompactionConfig`：`enabled` / `max_context_tokens`（默认 80k）/
  `keep_recent_turns`（默认 4）/ `summary_per_turn_chars`
- 触发阈值后把切点之前的消息折叠成一条带 `[历史摘要]` 标记的 user 消息
- **切点必须落在 user 消息上**——不会把 `tool_call` 与 `tool_result` 劈开
- **ThinkingBlock 不进摘要**——下一轮 reasoning 模型会重新生成
- 写到 `XuanjiConfig.compaction`，小宝改 `config.json` 就能调阈值

### Added · Conductor 累积 ThinkingBlock 到 history

[xuanji/neural/conductor.py:333](xuanji/neural/conductor.py#L333) 的 `asst_blocks`
类型扩展为 `list[TextBlock | ThinkingBlock | ToolCallBlock]`，把流式 `thinking_delta`
累积进 history。这是 DeepSeek `reasoning_content` 往返的前置条件。

### 质量

| | |
|---|---|
| 单测 | **379 全过**（354 → 379，+25：13 Provider 拆分 + 8 压缩 + 4 factory 路由） |
| ruff | **0 告警**（95 源文件） |
| mypy strict | **0 告警**（95 源文件） |
| 工具数 | 静态 29 + published 动态加载（同 0.9.0） |

### 升级提示

API 没有 breaking change。`xuanji version` 应当显示 `0.9.1`。如果原来在用
DeepSeek 且遇到过多轮 400 报错，本版直接修好。

---

## [0.9.0] — 2026-05-26

**ToolFactory 闭环 — generate / test / publish / reject CLI 全打通 + published 启动期自动加载**。

0.2 起就有 `propose_tool` 写草案，但从草案到"真能用的工具"中间断了一截：玄玑写的草案
小宝得人工写代码、人工注册。0.9 把这段缺口补上——同时**死守安全核心**：玄玑只能
propose（写 JSON），后面 generate/test/publish 全是 CLI 命令，LLM 无法触发。

### Added · CLI 工厂四件套

- `xuanji tool generate <slug>` — 跑激活 profile 的 LLM 把 draft 转 staged 代码 + 单测
- `xuanji tool test <slug> [--timeout 60]` — subprocess 跑生成的 pytest，通过则 status → tested
- `xuanji tool publish <slug>` — `status==tested` 才放行，复制到 `tool_published_dir/<slug>.py`
- `xuanji tool reject <slug> --reason "..."` — 标记拒绝，代码不删但不再被 publish
- `xuanji tool status [<slug>]` — 看工厂注册表（每个 slug 走到哪一步、最后一次 pytest 输出）

### Added · published 动态加载

新模块 `xuanji/tools/published_loader.py`：

- `load_published_tools(published_dir)` 扫目录下所有 `*.py`
- 动态 import 到独立命名空间 `xuanji.tools.published.<slug>`，不污染项目 import
- 用 `inspect.getmembers` 找"在本模块直接定义"的 `Tool` 子类（避开 `from xuanji.* import Tool` 拉进来的基类）
- 必须 `cls()` 无参数实例化才接受
- **单文件失败不连坐**：一个坏工具只在 logger.warning 提示，不影响其它工具与启动

`ServerRuntime.build_registry()` 在工厂工具之后调用 `load_published_tools(tool_published_dir())`，
名字冲突走 `contextlib.suppress(ValueError)`——内置工具优先，published 同名静默跳过。

### Safety · 闭环死守玄玑不能 publish

玄玑通过 `propose_tool` 工具调用产出 `tool_drafts/<slug>.json`——这是 LLM 唯一能做的事。
`generate / test / publish / reject` 只能由小宝在 CLI 触发：

```
玄玑 LLM ──propose_tool──▶ tool_drafts/<slug>.json
                              │
                              │  小宝 review（看 rationale + schema）
                              ▼
                       xuanji tool generate <slug>     ← CLI，不在工具集
                              │  跑 LLM codegen
                              ▼
                       tool_staged/<slug>.py + test_<slug>.py
                              │
                       xuanji tool test <slug>          ← CLI，subprocess pytest
                              │  通过 → status="tested"
                              ▼
                       xuanji tool publish <slug>       ← CLI，门控 status=="tested"
                              │
                              ▼
                       tool_published/<slug>.py
                              │
                              ▼
                       下次 ServerRuntime 启动自动加载
```

### Quality

| | |
|---|---|
| 单测 | **354 全过**（337 → 354，+17 工厂闭环：状态机 + loader + 端到端） |
| ruff | 0 告警 |
| mypy | strict **93 源文件** 0 告警（+1：published_loader） |
| 工具数 | 仍 29 个静态 + 用户级 published 动态加载（不计入静态注册） |

### Fixed

- CHANGELOG.md 顶部之前有重复的 header 段，本次清掉

## [0.8.0] — 2026-05-26

**真 LanceDB 接入 + Hooks `--explain` dry-run 模式 + 内置示范 skill/hook 一键安装**。
0.7 把跨家互通打通后，0.8 把"向量库长出来 + 配置可调试 + 用户开箱即用"补齐。
**首次公开 PyPI 发版**：包名 `xuanji-fivem`（`xuanji` 已被占）。

### Added · 真 LanceDB

- `xuanji/knowledge/vector.py::LanceDBVectorStore`：full implementation
  - schema：`id TEXT, vector FixedSizeList<float32, dim>, namespace TEXT, metadata JSON_TEXT`
  - upsert 用 `merge_insert("id").when_matched_update_all().when_not_matched_insert_all()`
  - search 转 `score = 1.0 / (1.0 + dist)`（L2 距离 → 越大越相关）
  - delete / delete_namespace 走 SQL DELETE
- 新 optional extra：`pip install 'xuanji-fivem[vector]'` 启用 lancedb + pyarrow
- import 延迟到 `__init__`，没装就抛 ImportError 并给出安装提示
- `ServerRuntime` 加 `vector_backend` 参数 + 工厂方法 `_make_vector_store`，
  默认读 `XUANJI_VECTOR_BACKEND` env，ImportError 自动 fallback InMemory
- 新增 `xuanji knowledge reindex-vectors --backend lancedb` CLI 用于重建索引
- `xuanji/config/paths.py::vector_db_path()` 嵌入式数据目录（`data/vectors/`）

**关键坑**：`_ensure_table` 不能用 `list_tables()` 判存在再 create——同目录跨实例时
`list_tables()` 不立刻看见新建的表，会触发 `Table 't' already exists`。改成 try
`open_table` 失败再 create。

### Added · Hooks `--explain` dry-run

- `HookExplanation = (spec, matched: bool, reason: str, can_deny: bool)`
  事前告诉「现在这个工具调用 / 这条 user prompt 会触发哪些 hook 以及为什么」
- **只有 PreToolUse 的 `can_deny=True`**——其他事件即使匹配也只是观察
- reason 文案区分事件：tool 事件说「matcher 'X' 匹配 tool 'Y'」；
  UserPromptSubmit 说「子串 'X' 在 prompt 中存在」
- CLI 四件套（`xuanji hook` Typer group）：
  - `path` — 打印 hooks 目录
  - `list` — 按事件列全部 spec
  - `explain --event PreToolUse --tool run_shell` — 干跑分析
  - `test --event ... --tool ... --payload-json '{...}'` — 真跑一次 hook

### Added · 内置示范 skill / hook + install-samples

- 新模块 `xuanji.resources` 暴露 `SAMPLE_SKILLS_DIR / SAMPLE_HOOKS_DIR`
  与 `list_sample_skills() / list_sample_hooks()`
- 3 个 skill（`xuanji/resources/skills/`）：
  - `qbox-add-useable-item.md` — QBox CreateUseableItem + ox_inventory 注册可使用物品
  - `ox-lib-callback.md` — `lib.callback.register` / `lib.callback.await` client/server 双侧
  - `fxmanifest-audit.md` — fxmanifest.lua review checklist（mode: review / role_hint: 司鉴）
- 3 个 hook（`xuanji/resources/hooks/`）：
  - `PreToolUse.yaml` — `rm -rf /` 黑名单（python -c 内嵌脚本，跨平台）+ `.env` 写入警告
  - `PostToolUse.yaml` — run_shell 命令日志到 stderr
  - `UserPromptSubmit.yaml` — 「部署 / 生产 / QBox」substring 提示
- CLI 一键拷贝：`xuanji skill-file install-samples` / `xuanji hook install-samples`
  默认不覆盖已有文件，`--force` 强制覆盖

### Changed · 公开 PyPI 发版

- 包名：`xuanji` → `xuanji-fivem`（PyPI 上 `xuanji` 已被占）
- `xuanji/__init__.py::__version__` 改为从 `importlib.metadata` 动态读取，
  单点真源——以后改版本号只动 `pyproject.toml` 一处
- `pyproject.toml` 加完整 PyPI 元数据：homepage / repository / issues / changelog
- `docs/packaging.md` 重写：删掉「内部团队工具，绝不上 PyPI」的旧约束

### Quality

- ruff / mypy strict 全绿（**92 源文件 0 告警**）
- pytest **337 全过**（315 → 337，+9 LanceDB 真实装单测 + +4 hook explain
  + +10 resources，删 1 旧 stub 测试）
- 工具总数 **29 个**（不变；本轮无新工具，只新增 CLI 命令组）

### Design highlights

**为什么核心包不依赖 lancedb**：lancedb 含 PyArrow + Lance Rust binding，
轮询大、装慢。InMemoryVectorStore 仍是默认（零依赖、单测必备），LanceDB 作为
optional `vector` extra；调用方 ImportError 自动 fallback——按需付费。

**为什么 `--explain` 重要**：hook 配错时只能干瞪眼是 0.7 的痛点。0.8 的
`HookExplanation` 把 matcher 评估全摊开——matched 的解释「为什么命中」、
没 matched 的解释「为什么没命中」、Pre/Post/UserPrompt 的 can_deny 差异
也讲清楚。配前先 `explain` 一遍，配错的概率掉到很低。

**为什么示范资源放 `xuanji/resources/` 不是 `data/`**：`data/` 是用户运行时
目录（数据库 / 索引 / 用户配置），不应该承载源码资产。`xuanji/resources/` 走 hatch
`packages` 自动打进 wheel，`pip install` 即得，`install-samples` 命令负责拷贝
到用户的 `data/skills` 与 `data/hooks`。

---

## [0.7.0] — 2026-05-26

**互通四件套**：Subprocess Sandbox + MCP Server + Skills + Hooks。0.6 解决了
"能用别家工具 + 异构路由"，0.7 把另一半补上——"让别家也能用玄玑的工具" +
"跟 CC/Codex 互拷 skill / hook 文件而无需改格式"。

### Added · Subprocess Sandbox

opt-in 子进程隔离。Tool 基类加 `is_subprocess_safe: ClassVar[bool] = False`，
显式标 True 才进 SubprocessSandbox，否则 RoutingSandbox 回退 InProc。

- `xuanji/body/sandbox/subproc_runner.py`：从 stdin 读 `{module, qualname, args, ctx}`，
  import 工具，跑 execute，stdout 吐 ToolResult JSON
  - **Windows 上必须 `_force_utf8()` reconfigure stdin/stdout/stderr**，
    不然中文 stdout 就是 `���`
- `xuanji/body/sandbox/subprocess.py`：parent 用 `asyncio.wait_for + proc.kill()`
  兜底超时；`_utf8_env()` 注入 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`
- `RoutingSandbox(inproc=, subprocess=)` 按 flag 路由
- `RunShellTool` 标了 `is_subprocess_safe = True` 作为示范

### Added · MCP Server 端

把玄玑 26+ 工具暴露给 CC / Codex / 任意 MCP-spec-compliant 客户端。

- `xuanji/mcp/server.py::McpServer`：单消息可测入口 `process_message` + `run_stdio` loop
- 复用 `ServerRuntime.build_registry` → 工具一致性零成本
- Gate 仍生效：`risk >= EXEC` 的工具走 NoOpHITLBridge 直接 deny
  （不能让 MCP 客户端无 HITL 触发高危）
- 错码：-32700 / -32601 / -32602 / -32603 严格按 JSON-RPC 2.0 spec
- stdio 是 **NDJSON**——**不复用** `xuanji/ipc/framing.py` 的 LSP Content-Length 分帧
- `xuanji mcp-serve` 命令启动前 set_utf8_stdio()

### Added · Skills 子系统

markdown + YAML frontmatter，**直接拷自 / 拷给 Claude Code、Codex 都能用**。

- 标准字段（CC/Codex 兼容）：`name / description / triggers / tools / allowed_tools`
- 玄玑扩展：`metadata.xuanji.{mode, temperature, risk_floor, role_hint}`，
  CC/Codex 看见 ignore
- `SkillsLoader.all() / get(name) / match(query)`
  - **方法名是 `all()` 不是 `list()`**——避免在 class body 里 shadow `list[T]`
    类型注解被 mypy 当成方法引用
- 三个工具：`list_skill_files / read_skill_file / match_skill_file`，全 SAFE
- `data_dir() / "skills" / *.md` 是默认目录（`skills_dir()`）

### Added · Hooks 子系统

YAML 配置，**事件名直接复用 Claude Code**：PreToolUse / PostToolUse /
UserPromptSubmit / Notification。hook = 一条外部命令；玄玑把 payload JSON 写到
hook 的 stdin。

- exit 0：放行
- exit 2 或 stdout 打 `{"decision":"deny", "reason":"..."}`：拒绝（**仅 PreToolUse 生效**）
- 其他错误：默认 allow（**hook 故障不能锁死会话**）
- `HooksRegistry.for_event(event)` / `matching(event, tool_name=, prompt=)`
- matcher 语义：tool 事件用 fnmatch glob；UserPromptSubmit 用 substring；
  其他只接受 `*`
- Conductor 集成：PreToolUse 跑在 `tool_run_started` 之后、Gate 之前；
  PostToolUse 跑在 sandbox 之后、纯观察（错误吃掉只入 audit）

### Quality

- ruff / mypy strict 全绿（**91 源文件 0 告警**）
- pytest **315 全过**（+6 subprocess + +10 mcp server + +14 skills + +12 hooks = +42）
- 工具总数 **29 个**（26 旧 + 3 个 skill_files 三件套；mcp adapter / sub-agent
  dispatch 等动态工具不计）

### Design highlights

**为什么 Subprocess Sandbox 是 opt-in**：大多数工具是纯函数式的（read_file /
list_dir / knowledge_search），进子进程纯粹增加序列化开销。`is_subprocess_safe`
显式标记，让需要隔离的（run_shell / 未来的 LLM-generated tool）单独进，
其他保持 InProc 性能。

**为什么 MCP stdio 用 NDJSON 而不是复用 LSP 分帧**：MCP 协议规定 stdio 是 NDJSON，
混用 Content-Length 会让客户端解析挂掉。两个传输层物理隔离最稳。

**为什么 `all()` 不叫 `list()`**：在 class body 里有 `def list(self) -> list[T]`，
mypy 严格模式会把第二个 `list` 解析成方法引用而非内置类型，报 valid-type 错。
重命名是最干净的修法。

---

## [0.6.0] — 2026-05-26

**异构路由 + MCP 客户端**。让玄玑能调度多家 LLM（按任务路由）+ 能消费别家
（CC/Codex/任意 MCP server）暴露的工具。

### Added · ModelRouter 异构路由

- `xuanji/llm/router.py::ModelRouter`：按 `RoutingPolicy` 决定每轮用哪家
  - 支持维度：task_kind / complexity / ctx_size / persona_mode
  - **默认 `prefer_model=None`**——不预设偏好，按 ProfileStore 顺序取首个可用
  - fallback 链：主 provider 失败 → 切下一个 profile，audit 记 `model_route_changed`
- Conductor 接 ModelRouter，每轮起势前 route 一次，结果注入 `_send` 调用

### Added · MCP 客户端

让玄玑做"工具消费者"：连别家 MCP server，把人家的工具像本地工具一样调。

- `xuanji/mcp/protocol.py`：JSON-RPC 2.0 + initialize / tools/list / tools/call
- `xuanji/mcp/transport.py`：stdio NDJSON（spawn 子进程模式）
- `xuanji/mcp/client.py::McpClient`：握手、心跳、tools list 缓存
- `xuanji/mcp/adapter.py::McpToolAdapter`：把远程 MCP tool 包成 `xuanji.Tool`
  - 实例属性遮罩 ClassVar 的 `name / version / schema` 走 `# type: ignore[misc]`
  - 远程工具的 `risk` 默认按服务器声明，没声明就保守取 `RiskTag.IO`
- `xuanji/mcp/registry.py::McpClientHub`：管多个 MCP server 连接，按 server name 命名空间
- ConfigStore 加 `mcp_clients: list[McpClientConfig]` —— 用户配置远程 server 入口
- `xuanji mcp client list / add / remove / test` CLI

### Quality

- ruff / mypy strict 全绿
- pytest 全过（+model_router + mcp_client + mcp_config + dispatch_heterogeneous）
- ServerRuntime 启动时自动连所有配置的 MCP server，把远程工具注册到 registry

### Design highlights

**为什么默认 prefer_model=None**：硬编码偏好（比如默认 sonnet）会让没装该 provider
的小宝直接挂掉。None 让 router 按用户实际配的 profile 顺序选，"装了什么用什么"。

**为什么 MCP 客户端先于 server**：先消费再生产是对称设计——`xuanji/mcp/`
两端共享 protocol / transport，先把客户端跑通，server 端只是把 dispatcher
方向反一下，复用度极高。0.7 接 server 时基本零新代码。

---

## [0.5.0] — 2026-05-26

**IPC 子系统 + VS Code 插件**。把 ServerRuntime 暴露成 LSP 风格 stdio JSON-RPC，
做出第一个非聊天形态的玄玑前端：VS Code 状态栏 / 命令面板 / 三栏仪表盘。
顺手把 `core/` 目录正名为 `xuanji/`（包名与目录名对齐）。

### Changed · 包目录正名

- `core/` → `xuanji/`：80+ 文件批量改名
- `pyproject.toml`：`packages = ["core"]` → `packages = ["xuanji"]`
- 入口脚本：`xuanji = "core.cli:app"` → `xuanji = "xuanji.cli:app"`
- 所有 import 全量替换 `core.X` → `xuanji.X`

**Why**：包名（在 PyPI 上叫什么） vs 目录名（开发时 import 什么）必须一致——
当前包要叫 `xuanji-fivem`，目录还叫 `core` 太混乱。提前正名为以后上 registry
扫清障碍。

### Added · IPC 子系统

LSP 风格 stdio JSON-RPC，**不是新调度**——把 ServerRuntime 已有的 store /
scaffold / registry 暴露成 22 个 RPC method。CLI / FastAPI / IPC 三个入口
共享同一个内核，零分叉。

- `xuanji/ipc/framing.py`：LSP Content-Length 分帧
- `xuanji/ipc/dispatcher.py`：JSON-RPC 2.0 + method 注册表
- `xuanji/ipc/server.py`：stdio loop + ServerRuntime 桥接
- `xuanji/ipc/errors.py`：JSON-RPC 错码常量
- 22 个 RPC method 覆盖：项目识别 / 知识库 / 记忆 / 预设管理 / 工具列表 / chat 流
- `xuanji ipc` CLI 命令（启动前 set_utf8_stdio）

### Added · VS Code 插件

`apps/vscode/`：独立 npm 包，**零模型依赖**——所有调用都走 stdio IPC。

- TypeScript 5 + esbuild 打包
- 状态栏：项目识别结果（QBox + ox_inventory）实时显示
- 命令面板五件套：detect / presets / new / preset list / preset accept
- 三栏仪表盘 webview：项目身份 + 工具栈 + 自学习预设草案
- LLM 客户端（Claude Code 等）该用啥用啥；玄玑插件提供"工具栏"能力

### Added · 文档与质量

- `docs/packaging.md`：发布与分发指南
- 新增 init / doctor 命令链路
- 三件套全绿（ruff / mypy / pytest）

### Design highlights

**stdio JSON-RPC = LSP 风格 + 复用 ServerRuntime**：IPC 不是新调度，就是把
ServerRuntime 已有的 store / scaffold / registry 暴露成 22 个 RPC method。
CLI / FastAPI / IPC 三个入口共享同一个内核，零分叉。

**插件零模型依赖**：apps/vscode 不直接调 LLM——所有调用都走 stdio。LLM
客户端（Claude Code 等）该用啥用啥，玄玑插件提供项目识别 / 知识库 / 记忆 /
预设管理这些"工具栏"能力。

---

## [0.4.0] — 2026-05-26

**FiveM 专精层** · 进任意 resource 目录玄玑就开箱即懂；从预设一键起脚手架；
能从现有 resource 反向学习并自我添加预设。

### Added · FiveM 专精层

- `core/fivem/`：新子系统，不属于七大核心子系统，是"领域知识层"
  - `models.py`：Framework / InventoryKind / TargetKind / FxManifest / FiveMContext
  - `manifest.py`：fxmanifest.lua 正则解析器（声明式字段全覆盖）
  - `detector.py`：综合判断器
    - 当前是 resource → 解析自身 fxmanifest dependencies 推断 framework
    - 当前是 server bundle 根 → 扫 resources/ + server.cfg 的 ensure 列表
    - 都不是 → 优雅退化，仍尝试找子 resources
  - `scaffold.py`：6 套核心预设 + 用户预设两层加载
  - `presets.py`：内置 6 套预设
    - `qbcore-basic` / `qbox-basic` / `qbcore-job` / `qbox-job`
    - `ox-target-npc`（standalone NPC 对话）
    - `esx-basic`
  - `analyzer.py`：从 resource 抽 exports / events / API 调用频率

### Added · 自学习能力

玄玑现在能反过来"教自己"——读现有 resource → 抽规律 → 提交预设草案：

| 工具 | 类型 | 作用 |
|---|---|---|
| `detect_project` | SAFE | 给当前目录的项目身份卡 |
| `analyze_resource` | SAFE | 静态分析一个 resource 的 exports/events/API |
| `propose_preset` | IO | 提交"做这类 resource 的标准骨架"草案 |

**安全边界**（同 propose_tool 路线）：
- `propose_preset` 只产 JSON 草案到 `<data_dir>/scaffold_drafts/`
- **不会自动激活**——小宝 review 后跑 `xuanji preset accept <key>`
- 路径校验拒绝绝对路径 / `..` / Windows 盘符前缀
- 必须含 `fxmanifest.lua`（不能产出无法启动的预设）

### Added · Conductor 集成

- `Conductor.static_extra` 新参数：启动期固定注入到 system prompt 的额外片段
- `ServerRuntime` 启动时自动跑 detector，把 FiveM 项目身份卡作为 static_extra 注入
- 玄玑回答前已经知道："当前是 QBox 1.x + ox_inventory 项目"，不用每次问

### Added · CLI 子命令

- `xuanji fivem detect [path]` —— 看一个目录的项目身份卡
- `xuanji fivem presets` —— 列所有可用预设
- `xuanji fivem new <name> --preset <key>` —— 一键生成 resource 骨架
- `xuanji fivem analyze [path]` —— 静态分析现有 resource
- `xuanji preset list` —— 看玄玑提交的草案
- `xuanji preset show <key> [--body]` —— 查看草案完整内容
- `xuanji preset accept <key>` —— 激活一个草案
- `xuanji preset reject <key>` —— 拒绝并删除草案
- `xuanji preset remove <key>` —— 删除已激活的用户预设

### Internal

- `ServerRuntime` 接管 CLI chat loop 与 tool list，单源注入避免双轨维护
- 新增 `core/config/paths.py::scaffold_presets_dir / scaffold_drafts_dir`

### Quality

- ruff / mypy strict 全绿（73 源文件 0 告警）
- pytest **204 测试全过**（M3 173 → 204，+31 个 fivem 测）
- 工具总数 **26 个**（+ detect_project / analyze_resource / propose_preset）

### Design highlights

**为什么"识别"而不是"问"**：用户在 resource 目录里 `xuanji chat` 时，玄玑应该
立即知道这是什么框架。每次问一遍既冗余又容易答错。detector 在 ServerRuntime 启动时
跑一次，把 framework / inventory / target 写进 system prompt 段，玄玑后续
回答自动选对的 API。

**为什么自学习预设而不是自学习工具**：预设是模板（声明式），工具是代码（命令式）。
模板风险低（不可执行），代码风险高（任意副作用）。这次扩"自学习"扩到预设是合理的；
工具仍走 propose_tool → 人工 generate/test/publish 重路径。

---

## [0.3.0] — 2026-05-25

**M3 全家桶**：jieba / 向量检索 / 爬虫 / 群英会 / ToolFactory 自动链路 /
FastAPI 服务层 / Web 前端 / Tauri 桌面壳。一次会话推完。

### Added · 检索增强

- `core/knowledge/tokenize.py`：jieba 中文分词，写入与查询时都过一遍预处理。
  解决了 0.2.0 之前 SQLite FTS5 unicode61 把整段中文当一个 token 的问题，
  现在 `recall("可使用物品")` 能命中。
- `core/knowledge/vector.py`：向量检索抽象层
  - `Embedder` 协议 + `HashingEmbedder`（SHA-1 LSH，零依赖、确定性）
  - `VectorStore` 协议 + `InMemoryVectorStore`（线性扫描，开发用）
  - `LanceDBVectorStore` 占位（M4+ 接真包）
- `SqliteKnowledgeStore.attach_vector_index(embedder, store)` 一行挂载混合检索
- `SqliteKnowledgeStore.hybrid_search(query)`：FTS5 + 向量 RRF 融合

### Added · 自动采集

- `core/knowledge/crawler.py`：BFS 爬虫
  - sitemap.xml 解析（含嵌套 sitemap index）
  - 域名白名单 + 礼貌 rate limit + 增量 content-hash 跳过未变更
  - 不引入 Scrapy，纯 httpx + asyncio
- `core/tools/crawl.py`：`crawl_site` 工具，RiskTag.NET → 司辰阁 HITL

### Added · 群英会

- `core/ensemble/`：监督式多 Agent 协作
  - `Role`：sub-agent 人格 + 工具白名单 + 模型偏好
  - 三个内置角色：**researcher**（查文档/代码）/ **coder**（写代码）/
    **reviewer**（审查方案，**只读不写**）
  - `SubAgent`：受限 registry 的轻量 Conductor 包装，一次性任务
  - `dispatch_subagent` / `list_roles` 工具：让玄玑通过工具调用召唤子智能体

  **关键设计**：召唤 sub-agent 本身就是一次工具调用，不引入新调度机制——
  audit / gate / 流式事件全部自动覆盖。

### Added · ToolFactory 自动实现链路

- `core/tools/tool_factory.py`：四步流水线
  ```
  propose_tool (玄玑) → drafts/<slug>.json
  xuanji tool generate <slug>  ← LLM 把草案转 Python，落 staged/
  xuanji tool test <slug>      ← subprocess 跑 pytest
  xuanji tool publish <slug>   ← 通过测试后复制到 published/
  ```
  - **安全核心**：玄玑只能 `propose_tool`，generate/test/publish 都是 CLI 命令，
    LLM 没法触发；即使 generate 出错也不会污染主 registry
  - `FactoryRegistry`（SQLite）追踪每个 slug 的生命周期状态
  - codegen 用统一的代码块协议（```python:tool` + ```python:test`），
    解析失败抛 ValueError 不创建空文件

### Added · 服务层

- `core/server/`：FastAPI 服务（`uv run xuanji serve`）
  - HTTP：`/healthz` / `/api/info` / `/api/profiles[/use/{name}]` /
    `/api/knowledge/{stats,sources,search}` / `/api/memory/{stats,recall}`
  - **WebSocket `/ws/chat`**：流式聊天 + 工具事件 + HITL 双向
  - `WebSocketHITL`：把司辰阁的人工确认请求推到前端，等用户裁决
- `ServerRuntime`：CLI 与 Web 共享同一注入路径，零行为差异

### Added · Web 前端

- `core/server/web.py` 内嵌单页 HTML
  - 暗色主题，原生 WS 接 `/ws/chat`
  - 流式渲染文本气泡 + 工具事件 + HITL 弹卡
  - `GET /` 直接返回，桌面 Tauri 可直接 webview 加载
- 不引入 Next.js / React 构建链——单页 HTML 已经够用

### Added · Tauri 桌面壳

- `apps/desktop/`：Tauri 2 配置（package.json / Cargo.toml / tauri.conf.json）
  - `pnpm tauri dev` 启动时自动起 `uv run xuanji serve`
  - webview 加载 `http://127.0.0.1:8765`
  - 没装 Rust 也能用：直接 `xuanji serve` + 浏览器开同一 URL
  - 完整 README 在 `apps/desktop/README.md`

### CLI

- 新增 `xuanji serve --host --port [--reload]`

### Quality

- ruff / mypy strict 全绿（65 个源文件 0 告警）
- pytest **173 测试全过**（M3 新增 65 个：jieba 11 + vector 14 + crawler 9 + 
  ensemble/factory 19 + server 13）
- 工具总数 **23 个**（+ crawl_site / dispatch_subagent / list_roles）

### Design highlights

**为什么不真上 LanceDB**：依赖太重（含 PyArrow / Lance Rust binding），
M3 阶段用零依赖的 InMemoryVectorStore + 协议化设计先把 hybrid search 跑通；
M4+ 把实现换成 LanceDB 时调用方零改动。

**为什么 sub-agent 不流式**：sub-agent 是一次性任务，结果作为工具输出
回到主 Conductor 的 tool loop——主 conductor 才面向用户流式。
M4+ 想要 sub-agent 流到前端时再补 stream() 实装。

---

## [0.2.0] — 2026-05-25

**自演化版本**。玄玑现在能在对话中主动补知识、写记忆、沉淀技能、提案新工具——
但所有进化都受边界约束：知识库可写、记忆库可写、技能可写，**工具代码永远人工把关**。

### Added · 自演化工具集（14 个新工具）

#### 元工具（4 个，自察自管）
- `list_tools`：列出当前可用工具（带 risk 过滤）
- `describe_tool`：查看某工具的完整 JSONSchema 与描述
- `list_skills` / `read_skill`：列出和读取已学到的技能

#### 记忆工具（2 个，主动读写）
- `recall_memory`：按关键词主动召回记忆，可过滤 kind / scope
- `write_memory`：玄玑判断「这条值得记」时落库（屏蔽 working scope，importance 自动 clamp）

#### 知识 ingestion（4 个，玄玑自动补充知识库）
- `ingest_text`：直接把 markdown 文本切片入库
- `ingest_file`：从工程内文件读入并入库
- `upsert_symbol`：精准添加/更新 API 卡片
- `ingest_url`：拉网页 → HTML→md → 切片入库（**RiskTag.NET，必走司辰阁 HITL**）

#### 技能系统（3 个，procedural memory 薄壳）
- `save_skill`：把做事套路保存为技能（写到 `skills` namespace + USER scope）
- `search_skill`：按关键词搜技能
- `run_skill`：展开技能正文 + 建议工具序列，让玄玑下一轮按步骤决策

#### 工具工厂（1 个，**安全收口**）
- `propose_tool`：玄玑产出新工具 JSON 草案到 `<data_dir>/tool_drafts/`，
  **不自动 publish**——由小宝 review 后人工实现 Python 代码并注册

### Added · 内核与 CLI

- `core/knowledge/chunker.py`：markdown 切分器（按标题分节、保留代码块）
- `core/tools/ingest_url.py`：极简 HTML→markdown（不引入 BeautifulSoup）
- `core/config/paths.py` 新增 `tool_drafts_dir()`
- 人设 prompt 加「自我进化」段，引导玄玑何时调用各类进化工具
- CLI 新增子命令族：
  - `xuanji skill list / show / save / forget`
  - `xuanji tool list / drafts (--show)`

### Quality

- ruff / mypy strict 全绿
- pytest **108 个测试全过**（M2.5 新增 23 个：evolve_tools 23）
- 工具总数 **21 个**（5 原子 + 2 知识 + 4 元 + 2 记忆 + 4 ingest + 3 skill + 1 factory）

### Design notes

**为什么技能 = procedural memory 而不是新执行单元？**

传统设计会引入 `Skill` 类、注册表、组合器。但仔细看 → 技能本质就是
"做事的套路"加"建议工具序列"，这正是 procedural memory 的语义。
统一抽象避免双轨维护，且天然吃到记忆系统的 reflux / 衰减 / 命名空间隔离。

**为什么 propose_tool 不自动实现？**

让 LLM 写可执行 Python 代码并自动注册到生产 registry——这是 LLM Agent 安全的
最大风险面之一。本期采用「玄玑提案 → 落 JSON 到磁盘 → 小宝 review → 人工实现」
四步流水线。M4+ 的 ToolFactory 即便接 LLM 生成实现，也走 draft → 单测 → review →
published 严格流程，玄玑永远不能自己 publish。

---

## [0.1.0] — 2026-05-25

第一个对外可用版本。M0 + M1 + M2 三个里程碑闭环，CLI 端到端跑通"小宝问 → 玄玑用工具 → 司辰阁守门 → 工具执行 → 怀玉阁回流"完整链路。

### Added

#### LLM 抽象（M0）
- `core/llm/providers/base.py`：跨厂商统一 `Message` / `ContentBlock` / `Delta` / `LLMProvider` 协议
- `AnthropicProvider`：流式对话 + 工具调用 + tool_result 块归一化
- `OpenAIProvider`：兼顾 OpenAI / DeepSeek / openai-compatible 三种端点
- `ToolResultBlock`：跨 Provider 的工具结果块，AnthropicProvider 翻成 user+tool_result，OpenAIProvider 翻成独立 tool 消息
- 三种 Delta 工具运行事件：`tool_run_started` / `tool_run_blocked` / `tool_run_done`

#### 配置系统（M0）
- `ConfigStore` + 四种 profile kind（anthropic / openai / deepseek / openai-compatible）
- 跨平台用户目录：Windows `%APPDATA%`，macOS `~/Library/Application Support`，Linux `~/.config`
- 数据库目录用 `user_data_dir`（含 `knowledge.db` / `memory.db`）
- 玄玑对话称呼可调：`assistant_alias` / `user_alias`，CLI 框架文字（顶部 panel / 输入框）保持不变
- 人设 5 模式（chat/dev/ops/review/gate）+ 3 温度档（playful/balanced/professional）

#### 天枢台 Conductor（M0+M1+M2）
- 会话上下文 + persona mode/temperature/alias
- 多轮 tool loop（默认上限 10）：流式调用 → 累积 text+tool_calls → Gate 守门 → Sandbox 执行 → 结果回写 history → 进入下一轮
- 接 Memory：每轮 send 前 reflux top-k，注入 system prompt
- AuditLog 记录 session_start / user_input / model_request / delta_text / delta_tool_call / model_done / error

#### 百工坊 + 工造司 + 司辰阁（M0）
- `Tool` ABC + `RiskTag` 五档（safe/io/exec/net/destructive）
- `ToolRegistry` 注册器
- `InProcSandbox` 同进程沙箱 + 超时 + 异常归一
- `GateInterceptor` 横切中间件 + `DefaultPolicy`（destructive→deny / exec/net→hitl / io 工程外→hitl）
- `HITLBridge` 协议 + `NoOpHITLBridge`（无人值守一律拒绝）

#### 内置工具（M0+M1）
- 5 个原子工具：`read_file` / `write_file` / `list_dir` / `ripgrep` / `run_shell`
- 2 个知识工具：`knowledge_search` / `lookup_symbol`

#### 稷下学宫（M1）
- `Source` / `Chunk` / `Symbol` 三层数据模型
- `SqliteKnowledgeStore`：SQLite + FTS5 + 触发器同步 + bm25 排序
- 启发式 `_guess_anchor_symbol`：从查询中抓 symbol 锚点
- FiveM 种子知识库：QBCore / ox_lib / ox_inventory / cfx 关键 API 手写卡片
- 命名空间：`fivem.qbcore@1.x` / `fivem.ox_lib@3.x` / `fivem.ox_inventory@2.x` / `fivem.cfx@latest`

#### 怀玉阁（M2）
- `Memory` + `MemoryKind`（episodic/semantic/procedural）+ `MemoryScope`（working/session/project/user）
- `SqliteMemoryStore`：SQLite + FTS5 + 衰减打分（importance × decay × log(1+hits)）+ 半衰期 14 天
- `recall` 命中后自动 hits++ / last_accessed 更新
- `consolidate`：episodic 超额时按重要性截断
- `forget`：按 ids / namespace / scope 任意组合删除
- `refluxed_fragment`：把召回的 top-k 拼成 system prompt 注入段

#### CLI（M0+M1+M2）
- `xuanji info` / `chat`
- `xuanji config`：path / list / show / add / use / remove / test / alias
- `xuanji knowledge`：path / stats / list / ingest / search / symbol / clear
- `xuanji memory`：path / stats / list / write / recall / forget / consolidate
- Windows GBK 终端兼容：自动切 stdout/stderr 到 UTF-8

### Quality

- ruff 全绿（select E/F/I/B/UP/SIM/RUF；中文项目放行 RUF001/002/003）
- mypy strict 模式 0 告警，覆盖 45 个源文件
- pytest **82 个单测全过**：persona(12) / config_store(14) / llm_base(7) / conductor(7) / gate(10) / tools_builtin(7) / knowledge(11) / memory(14)

### Documentation

- `README.md` 全量更新
- `CLAUDE.md` 仓库根宪法
- 完整规划见 `~/.claude/plans/fivem-ai-agent-glowing-cake.md`

### Roadmap（M3+）

- 群英会 Ensemble：监督式 / 合议式多 Agent 协作
- Tauri 2 桌面端 + Next.js Web 前端
- LanceDB 向量检索（替换或并行 FTS5）
- 知识库爬虫与增量更新
- ToolFactory：自然语言生成新工具
- ModelRouter：多维路由 + 成本/延迟遥测
- Subprocess 沙箱档（高风险工具升级隔离）
