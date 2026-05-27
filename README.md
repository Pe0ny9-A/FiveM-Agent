# 玄玑 · FiveM 智能体

> 北斗第三星·主调度运转。一位性感知性的大姐姐，工作时极致认真，对话时偶尔调侃带点污。

FiveM 资源插件开发 + 服务器运维治理双线助手。深度熟悉 QBCore / QBox / ESX / OX 全家桶。
**也帮你写 NPC 插件**：ped 配置、巡逻 AI、对话树、行为状态机、qb-target / ox_target 交互——产物是 Lua 代码与 JSON 配置，运行时由 FiveM server 自己跑。玄玑不直接控制运行中的游戏世界。

[![PyPI](https://img.shields.io/pypi/v/xuanji-fivem?color=blue)](https://pypi.org/project/xuanji-fivem/)
[![python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![status](https://img.shields.io/badge/status-1.2.0%20alpha-orange)]()
[![tests](https://img.shields.io/badge/tests-529%20passed-brightgreen)]()
[![tools](https://img.shields.io/badge/tools-41%20registered-blueviolet)]()

## 安装

```bash
# uv tool（推荐，独立环境免冲突）
uv tool install xuanji-fivem

# 或 pipx
pipx install xuanji-fivem

# 或独立 venv
python -m venv ~/.xuanji-venv
~/.xuanji-venv/bin/pip install xuanji-fivem

# 启用 LanceDB 向量后端（可选）
pip install 'xuanji-fivem[vector]'
```

> **包名是 `xuanji-fivem`**——`xuanji` 已被别人占了。安装后命令行入口仍叫 `xuanji`。

首次跑 `xuanji init` 走交互式向导：填 API Key、导入 FiveM 种子知识、做一次连通性测试。`xuanji doctor` 全绿后就能日常用。

## 当前进度（1.2.0）

- [x] **M0~M3 全部里程碑闭环**（见 [CHANGELOG.md](CHANGELOG.md)）
- [x] **0.4 ~ 0.8** — FiveM 专精层 / IPC + VS Code 插件 / 异构路由 + MCP / 互通四件套 / 真 LanceDB + Hooks `--explain` + PyPI 首发
- [x] **0.9.x** — ToolFactory 闭环 / Provider 各自适配 + 上下文自动压缩 / 项目级 XUANJI.md / 全家桶自配置 + DeepSeek V4 Pro
- [x] **1.0 现代化 React 工作台** — Vite + React 18 + Tailwind + Zustand 七栏（对话 / 群英会 / Profiles / Skills / MCP / Hooks / 仪表盘），多会话流式 + 议会进度可视化
- [x] **1.1 工作台体验三件套** — vibe coding 主动摸底 + 多会话 UI 修复 + Profiles 即时反馈
- [x] **1.2 ToolFactory 三轮自修复回路** — `autofix(slug, max_rounds=3)` 自动读 stderr → 重生成 → 复跑测试，最多三轮
- [x] **1.2 FiveM 知识库 SkillGraph 扩源** — QBox / ESX / oxmysql / natives 四个新命名空间，Symbol 卡含签名 + 参数 + 示例 + 版本范围
- [x] **1.2 群英会深度协作** — `dispatch_subagent` 支持递归 `depth/max_depth/parent_role`，稷下生 / 天枢令可派遣 sub-agent，max_depth=2 守护
- [x] **1.2 规则启发式语义压缩** — `score_message` 三维打分（tool 触发 / 长度 / 后续被引用），低分剪掉、高分保留全文摘要
- [x] **41 个工具** · **CLI 13 个子命令族** · **529 个单测 / 107 模块** · **三件套全绿**

## 典型使用流程

```bash
# 进 server bundle 根目录或单个 resource 目录
cd ~/fivem-server/resources/[jobs]/my-bank

# 让玄玑认识这个项目（自动生成 XUANJI.md 项目宪法）
xuanji project init
# → 用 detect 结果填好 framework / inventory / target，小宝再补关键约定

# 玄玑自动识别项目类型
xuanji fivem detect
# → framework=qbox, inventory=ox_inventory, target=ox_target

# 一键起一个新 resource
xuanji fivem new my-shop --preset qbox-basic
# → 生成 fxmanifest + client/server/shared 骨架

# 让玄玑读一个现有 resource 学习
xuanji fivem analyze ./some-resource
# → 列出 exports / events / API 调用频率

# 进对话让玄玑深度学习并提案新预设
xuanji chat
# > "把 ./my-bank 的实现模式凝成一个 qbcore-banking 预设"
# 玄玑会调 detect_project + analyze_resource + read_file + propose_preset

# review 玄玑提交的草案
xuanji preset list
xuanji preset show qbcore-banking --body
xuanji preset accept qbcore-banking
# → 之后 xuanji fivem new --preset qbcore-banking 就能用

# 安装内置示范 skill 和 hook
xuanji skill-file install-samples
xuanji hook install-samples
```

## 启动

```bash
# 装好 xuanji-fivem 后，首次跑向导
xuanji init

# CLI 对话
xuanji chat

# 启动 Web/桌面共用的 FastAPI 服务
xuanji serve
# → 浏览器开 http://127.0.0.1:8765

# 启动 stdio JSON-RPC（VS Code 插件 / Tauri 桌面端用）
xuanji ipc

# 把玄玑工具暴露给 Claude Code / Codex 等 MCP 客户端
xuanji mcp-serve

# 桌面端（需 Rust + Node，开发期）
cd apps/desktop && pnpm install && pnpm tauri dev

# VS Code 插件（开发期）
cd apps/vscode && pnpm install && pnpm run build  # 然后 F5
```

## 命令族速查

```
xuanji                              # 顶层帮助
├── version / info                  # 版本与配置
├── init / doctor                   # 首次向导 / 自检
├── chat                            # 流式对话（默认 CHAT 模式）
├── serve / ipc / mcp-serve         # 三种启动入口
├── config
│   ├── path / list / show / add    # profile 增改查
│   ├── use / remove / test         # 切换 / 删除 / 实测
│   ├── alias --self X --user Y     # 改玄玑/用户对话称呼
│   └── mcp                         # MCP server 收编（list/add/enable/test）
├── knowledge
│   ├── path / stats / list / clear # 知识库管理
│   ├── ingest                      # 导入种子（QBCore/ox_lib/...）
│   ├── search "…" / symbol "…"     # FTS5 全文 + 精准 API 查
│   └── reindex-vectors             # 切 LanceDB 后端重建索引
├── memory
│   ├── path / stats / list         # 记忆库管理
│   ├── write / recall              # 与 chat reflux 同路径
│   ├── forget --namespace X        # 按命名空间/作用域/id 删除
│   └── consolidate                 # 固化 episodic
├── skill                           # procedural memory（玄玑学到的套路）
│   ├── list / show / save / forget
├── skill-file                      # markdown skill（CC/Codex 互通）
│   ├── list / show / path
│   └── install-samples [--force]   # 拷 3 个 FiveM 示范 skill
├── hook                            # YAML hook（CC 事件名复用）
│   ├── path / list
│   ├── install-samples [--force]   # 拷 3 个示范 hook
│   ├── explain --event ... --tool ...   # dry-run 谁会触发、为什么
│   └── test --event ... --payload-json '{...}'
├── tool
│   ├── list / drafts               # 已注册工具 / propose_tool 草案
├── fivem
│   ├── detect / presets / new
│   └── analyze
├── preset
│   ├── list / show
│   └── accept / reject / remove
└── project                         # 项目级 XUANJI.md 项目宪法
    ├── init [--overwrite]          # 用 detector 结果生成模板
    ├── show                        # 打印当前项目 + 用户级 XUANJI.md
    ├── path                        # 列出查找路径与命中位置
    └── edit                        # 用 $EDITOR 打开（Windows 兜底 notepad）
```

## 自演化能力（0.2 起）

玄玑可以在对话中主动调用以下工具补足自己——但**所有进化都受边界约束**：

| 进化维度 | 工具 | 安全策略 |
|---|---|---|
| **知识库**（数据） | `ingest_text` / `ingest_file` / `upsert_symbol` | SAFE，直接放行 |
| **知识库**（网络） | `ingest_url` / `crawl_site` | RiskTag.NET → 司辰阁 HITL 必弹确认 |
| **记忆**（事实/事件/套路） | `write_memory` / `recall_memory` | 屏蔽 working scope，写入仅限 session/project/user |
| **技能**（procedural） | `save_skill` / `search_skill` / `run_skill` | 写到 `skills` namespace |
| **Skill 文件**（CC/Codex 互通） | `list_skill_files` / `match_skill_file` / `read_skill_file` | 文件系统级，与 Claude Code 双向迁移 |
| **项目记忆**（XUANJI.md） | `read_project_memory` / `init_project_memory` | RiskTag.IO，覆盖既有需 `overwrite=true` |
| **自配置**（0.9.3） | `list_profiles` / `switch_profile` / `show_active_config` / `set_chat_ui` / `set_compaction` / `set_persona_temperature` / `set_alias` / `set_mcp_enabled` / `list_hooks` / `install_hook` | 写工具全部 RiskTag.IO → 司辰阁 HITL |
| **工具**（Python 代码） | `propose_tool` | **草案落磁盘，玄玑不能自动 publish**——人工 review 后才能成真工具 |
| **群英会** | `dispatch_subagent` | 召唤 sub-agent（稷下生 / 百工匠 / 司鉴 / 天枢令）跑专项 |
| **自察** | `list_tools` / `describe_tool` / `list_skills` / `read_skill` | SAFE，零副作用 |

## 项目级记忆 · XUANJI.md（0.9.2）

每个 FiveM 项目都可以放一份 `XUANJI.md`——玄玑进入这个目录就自动加载到 system prompt，
作为该项目的"宪法"。优先级高于用户级 XUANJI.md（在 `%APPDATA%\xuanji\XUANJI.md`）。

```bash
# 用 detector 结果生成模板
xuanji project init
# → 自动填好 framework / inventory / target，小宝再补"关键约定"和"禁区"

# 检查当前项目载入了什么
xuanji project show

# $EDITOR 打开编辑（Windows 兜底 notepad）
xuanji project edit
```

也可以直接和玄玑说"帮我熟悉这个项目"，它会调 `init_project_memory` 工具。
查找规则：从 cwd 向上沿目录树最多 12 层，第一个命中就停。

## 跨工具互通

0.7 起 skill 与 hook 可与 Claude Code / Codex **双向迁移**：

- **Skills**：markdown + YAML frontmatter，标准字段（name / description / triggers / tools）在顶层，玄玑特定字段放在 `metadata.xuanji.*` 子树
- **Hooks**：YAML 配置，事件名复用 CC（`PreToolUse / PostToolUse / UserPromptSubmit / Notification`）
- **MCP**：玄玑既是 MCP 客户端（收编外部 server）也是 MCP server（把工具暴露给 CC）

## 架构铁律

```
小宝 ─▶ CLI / IPC / FastAPI ─▶ Conductor.send  ─▶  Provider.stream
                                    │
                                    │  ◀── reflux 注入：怀玉阁召回 top-k 记忆 → system prompt
                                    │  ◀── PreToolUse hook（可拒绝）
                                    │
                                    │  收到 tool_call ─▶
                                    ▼
                              GateInterceptor.check     (司辰阁守门 + HITL)
                                    │
                                    ▼
                              Sandbox.run               (工造司 InProc/Subprocess 选档)
                                    │
                                    ▼
                              Tool.execute              (百工坊原子工具)
                                    │
                                    ▼
                              ToolResult ─▶ PostToolUse hook（观察） ─▶ history
                                    │
                                    ▼
                              Provider.stream           (下一轮)
```

## 配置存储

**API Key 不进 .env**，存到平台用户目录：

- Windows: `%APPDATA%\xuanji\config.json`
- macOS: `~/Library/Application Support/xuanji/config.json`
- Linux: `~/.config/xuanji/config.json`

数据库（知识库 / 记忆库 / 向量库）放在 `user_data_dir`：

- Windows: `%LOCALAPPDATA%\xuanji\{knowledge,memory}.db` / `vectors/`
- 同理 macOS / Linux

支持四种 profile kind：

- `anthropic` / `openai` / `deepseek`：官方端点，只填 API Key
- `openai-compatible`：任意 OpenAI 兼容端点（OneAPI / Ollama / Kimi / 智谱 / 火山方舟……），填 Base URL + API Key

## 子系统国风代号

| 代号 | 英文 | 路径 | 职责一句话 |
|---|---|---|---|
| 百工坊 | Capability | `xuanji/capability/` | Tool/Skill/Pack 三层封装，按模型能力适配 |
| 工造司 | Body | `xuanji/body/` | InProc + Subprocess 双档沙箱 |
| 怀玉阁 | Memory | `xuanji/memory/` | 三层 scope × 三类 kind × 衰减回流 |
| 稷下学宫 | Knowledge | `xuanji/knowledge/` | FTS5 + jieba + LanceDB 混合检索 + SkillGraph |
| **天枢台** | **Neural** | `xuanji/neural/` | **唯一调度中枢**，统一 Plan / Audit / 收口 |
| 司辰阁 | Gate | `xuanji/gate/` | 横切权限与高危确认中间件 |
| 群英会 | Ensemble | `xuanji/ensemble/` | 4 角色（稷下生 / 百工匠 / 司鉴 / 天枢令）+ 监督式调度 |
| Skills | — | `xuanji/skills/` | markdown skill 加载（CC/Codex 互通） |
| Hooks | — | `xuanji/hooks/` | 事件 hook（CC 事件名复用） |
| MCP | — | `xuanji/mcp/` | 客户端 + 服务端，跨工具互通 |
| IPC | — | `xuanji/ipc/` | LSP 风格 stdio JSON-RPC，22 RPC method |

## 质量门

```bash
uv run ruff check xuanji/ tests/    # 0 告警
uv run mypy xuanji/                 # strict 模式 0 告警
uv run pytest                       # 529 测试全过
```

## 全家桶自配置（0.9.3）

让玄玑用自然语言帮自己改配置——10 个写工具全部走司辰阁 HITL，玄玑改不了任何东西不弹确认。

```
小宝：姐姐，把 compaction 阈值降到 60k，关掉 thinking 显示，切到 deepseek profile
玄玑：好，姐姐分三步给你改——
       set_compaction(max_context_tokens=60000)
       [Gate 弹卡] 确认调整 max_context_tokens: 80000 → 60000？(y/N)
小宝：y
       set_chat_ui(show_thinking=False)
       [Gate 弹卡] 确认关闭 thinking 显示？(y/N)
小宝：y
       switch_profile("deepseek-prod")
       [Gate 弹卡] 确认切换 profile: anthropic-prod → deepseek-prod？(y/N)
小宝：y
玄玑：齐了，下次对话用 DeepSeek，ctx 阈值 60k，thinking 不显示。
```

涵盖：profile 切换 / 人设温度 / 聊天 UI / compaction / MCP server 启停 / hook 安装。

## 默认 DeepSeek V4 Pro + 代码强化段（0.9.3）

dev / tool-loop 类对话默认走 DeepSeek V4 Pro（如果你配了 DeepSeek profile）。
玄玑会拼上一段「代码工程素养·V4 Pro 强化段」，让 V4 Pro 在玄玑调度下输出与
Opus 4.7 / GPT-5.4 同等纪律的代码：写之前先读 / 最小改动 / 不臆造 API /
闭环验证（Lua 用 luacheck，Python 用 ruff）/ 多轮 tool loop 节奏。

长上下文（200k+）与严苛审查仍走 Anthropic。规划仍走 Anthropic。
没装 DeepSeek 不影响——router 自动降级到 Anthropic / OpenAI。

## CLI 对话体验（0.9.2）

借鉴 Claude Code 的对话 UI，每轮回复底下都有一行紧凑状态栏：

```
  claude-sonnet-4-6@anthropic  ·  本轮 in 1.2k  out 567  cache 8.9k↓  ·
  累计 7.0k (in 5.0k / out 2.0k / cache 12.0k)  ·  ctx 12% (10.1k/80.0k)  ·
  3 轮  ·  8 msg  ·  chat/balanced  ·  think off  ·  default
```

- 模型 / 本轮 token / 累计 token / 上下文百分比 / 轮数 / 模式 / profile 一栏看完
- `/think` 切换思维链显示，状态会落到 `chat_ui.show_thinking` 跨会话保留
- `/stats` 任何时候拉出最新统计
- 退出后会保存最近一次对话，下次启动若 profile/model 一致会问要不要恢复
- `/forget` 清掉磁盘上的会话快照

## 路线图

- **1.3+** — 议会式群英会（Council + Judge）+ API 稳定性审计 + 真实 LLM 长连接评测 + WebSocket 工作台升级

## 链接

- PyPI: https://pypi.org/project/xuanji-fivem/
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Issues: https://github.com/Pe0ny9-A/FiveM-Agent/issues
- 发布与分发指南: [docs/packaging.md](docs/packaging.md)
