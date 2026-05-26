# 玄玑 · FiveM 智能体

> 北斗第三星·主调度运转。一位性感知性的大姐姐，工作时极致认真，对话时偶尔调侃带点污。

FiveM 资源插件开发 + 服务器运维治理双线助手。深度熟悉 QBCore / QBox / ESX / OX 全家桶。
**也帮你写 NPC 插件**：ped 配置、巡逻 AI、对话树、行为状态机、qb-target / ox_target 交互——产物是 Lua 代码与 JSON 配置，运行时由 FiveM server 自己跑。玄玑不直接控制运行中的游戏世界。

[![PyPI](https://img.shields.io/pypi/v/xuanji-fivem?color=blue)](https://pypi.org/project/xuanji-fivem/)
[![python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![status](https://img.shields.io/badge/status-0.8.0%20alpha-orange)]()
[![tests](https://img.shields.io/badge/tests-337%20passed-brightgreen)]()
[![tools](https://img.shields.io/badge/tools-29%20registered-blueviolet)]()

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

## 当前进度（0.8.0）

- [x] **M0~M3 全部里程碑闭环**（见 [CHANGELOG.md](CHANGELOG.md)）
- [x] **0.4 FiveM 专精层** — 项目识别 / 6 套预设 / 静态分析 / 自学习预设
- [x] **0.5 IPC + VS Code 插件** — LSP 风格 stdio JSON-RPC，22 RPC method，零模型依赖插件
- [x] **0.6 异构路由 + MCP 客户端** — ModelRouter 跨厂商挑选 + 收编外部 MCP server 工具
- [x] **0.7 互通四件套** — Subprocess Sandbox / MCP Server / Skills / Hooks，与 Claude Code/Codex 双向迁移
- [x] **0.8 真 LanceDB + Hooks `--explain` + 内置示范 skill/hook + 公开 PyPI 首发**
- [x] **29 个工具** · **CLI 12 个子命令族** · **337 个单测** · **三件套全绿（92 源文件 0 告警）**

## 典型使用流程

```bash
# 进 server bundle 根目录或单个 resource 目录
cd ~/fivem-server/resources/[jobs]/my-bank

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
└── preset
    ├── list / show
    └── accept / reject / remove
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
| **工具**（Python 代码） | `propose_tool` | **草案落磁盘，玄玑不能自动 publish**——人工 review 后才能成真工具 |
| **群英会** | `dispatch_subagent` | 召唤 sub-agent（稷下生 / 百工匠 / 司鉴 / 天枢令）跑专项 |
| **自察** | `list_tools` / `describe_tool` / `list_skills` / `read_skill` | SAFE，零副作用 |

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
uv run ruff check xuanji/ tests/    # 92 源文件 0 告警
uv run mypy xuanji/                 # strict 模式 0 告警
uv run pytest                       # 337 测试全过
```

## 路线图

- **0.9** — 工具工厂闭环（generate / test / publish CLI 全打通 + published 自动加载）
- **1.0** — M4 完结：议会式群英会（Council + Judge）+ API 稳定性审计

## 链接

- PyPI: https://pypi.org/project/xuanji-fivem/
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Issues: https://github.com/Pe0ny9-A/FiveM-Agent/issues
- 发布与分发指南: [docs/packaging.md](docs/packaging.md)
