# 玄玑 · FiveM 智能体

> 北斗第三星·主调度运转。一位性感知性的大姐姐，工作时极致认真，对话时偶尔调侃带点污。

FiveM 资源插件开发 + 服务器运维治理双线助手。深度熟悉 QBCore / QBox / ESX / OX 全家桶。
**也帮你写 NPC 插件**：ped 配置、巡逻 AI、对话树、行为状态机、qb-target / ox_target 交互——产物是 Lua 代码与 JSON 配置，运行时由 FiveM server 自己跑。玄玑不直接控制运行中的游戏世界。

[![python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![status](https://img.shields.io/badge/status-0.4.0%20alpha-orange)]()
[![tests](https://img.shields.io/badge/tests-204%20passed-brightgreen)]()
[![tools](https://img.shields.io/badge/tools-26%20registered-blueviolet)]()

## 当前进度（0.4.0 · FiveM 专精层）

- [x] **M0~M3 全部里程碑闭环**（见 CHANGELOG）
- [x] **0.4 FiveM 专精层** ✨
  - 项目识别器：进 resource 目录自动 detect QBCore/QBox/ESX/OX
  - 6 套 scaffold 预设 + 一键 `xuanji fivem new <name>`
  - resource 静态分析器：抽 exports / events / API 调用
  - **自学习预设**：玄玑读现有 resource → 提交预设草案 → 小宝 review → 激活
- [x] **26 个工具** · **CLI 10 个子命令族** · **204 个单测** · **三件套全绿**

## 0.4.0 典型使用流程

```bash
# 进 server bundle 根目录或单个 resource 目录
cd ~/fivem-server/resources/[jobs]/my-bank

# 玄玑自动识别项目类型
uv run xuanji fivem detect
# → framework=qbox, inventory=ox_inventory, target=ox_target

# 一键起一个新 resource
uv run xuanji fivem new my-shop --preset qbox-basic
# → 生成 fxmanifest + client/server/shared 骨架

# 让玄玑读一个现有 resource 学习
uv run xuanji fivem analyze ./some-resource
# → 列出 exports / events / API 调用频率

# 进对话让玄玑深度学习并提案新预设
uv run xuanji chat
# > "把 ./my-bank 的实现模式凝成一个 qbcore-banking 预设"
# 玄玑会调 detect_project + analyze_resource + read_file + propose_preset

# review 玄玑提交的草案
uv run xuanji preset list
uv run xuanji preset show qbcore-banking --body
uv run xuanji preset accept qbcore-banking
# → 之后 xuanji fivem new --preset qbcore-banking 就能用
```

## 启动

```bash
# 装依赖
uv sync --extra dev

# 加 profile
uv run xuanji config add ds --kind deepseek

# 导入 FiveM 种子知识
uv run xuanji knowledge ingest

# CLI 对话
uv run xuanji chat

# 启动 Web/桌面共用的 FastAPI 服务
uv run xuanji serve
# → 浏览器开 http://127.0.0.1:8765

# 桌面端（需 Rust + Node）
cd apps/desktop && pnpm install && pnpm tauri dev
```

## 启动

```bash
# 装依赖
uv sync --extra dev

# 加一个 profile（DeepSeek 官方为例，会交互问 API Key）
uv run xuanji config add ds --kind deepseek

# 导入 FiveM 种子知识（QBCore + ox_lib + ox_inventory + cfx）
uv run xuanji knowledge ingest

# 进入对话
uv run xuanji chat
```

## 命令族速查

```
xuanji                              # 顶层帮助
├── info                            # 当前激活配置概览
├── chat                            # 流式对话（默认 CHAT 模式）
├── config
│   ├── path / list / show / add    # profile 增改查
│   ├── use / remove / test         # 切换 / 删除 / 实测
│   └── alias --self X --user Y     # 改玄玑/用户对话称呼
├── knowledge
│   ├── path / stats / list / clear # 知识库管理
│   ├── ingest                      # 导入种子（QBCore/ox_lib/...）
│   ├── search "…"                  # FTS5 全文检索
│   └── symbol "…"                  # 精准查 API 卡片
├── memory
│   ├── path / stats / list         # 记忆库管理
│   ├── write / recall              # 与 chat reflux 同路径
│   ├── forget --namespace X        # 按命名空间/作用域/id 删除
│   └── consolidate                 # 固化 episodic
├── skill                           # 0.2.0 新
│   ├── list / show                 # 列出 / 查看技能
│   ├── save                        # 手动保存技能（与 save_skill 同路径）
│   └── forget                      # 删除技能
└── tool                            # 0.2.0 新
    ├── list                        # 列出已注册的全部工具
    └── drafts [--show <slug>]      # 查看 propose_tool 提交的草案
```

## 自演化能力（0.2.0）

玄玑可以在对话中主动调用以下工具补足自己——但**所有进化都受边界约束**：

| 进化维度 | 工具 | 安全策略 |
|---|---|---|
| **知识库**（数据） | `ingest_text` / `ingest_file` / `upsert_symbol` | SAFE，直接放行 |
| **知识库（网络）** | `ingest_url` | RiskTag.NET → 司辰阁 HITL 必弹确认 |
| **记忆**（事实/事件/套路） | `write_memory` / `recall_memory` | 屏蔽 working scope，写入仅限 session/project/user |
| **技能**（procedural） | `save_skill` / `search_skill` / `run_skill` | 写到 `skills` namespace，可读可改可删 |
| **工具**（Python 代码） | `propose_tool` | **草案落磁盘，玄玑不能自动 publish**——人工 review 后才能成真工具 |
| **自察** | `list_tools` / `describe_tool` / `list_skills` / `read_skill` | SAFE，零副作用 |

### 典型自演化场景

```
用户：QBox 怎么做电池系统？
玄玑：→ knowledge_search "QBox 电池系统"  # 没结果
     → ingest_url "https://docs.qbox.re/..."  # 司辰阁弹窗，用户确认
     → 拉到文档后 knowledge_search 能命中了
     → 给出方案
     → save_skill "QBox 电池系统标准实现 5 步"  # 沉淀套路
     → write_memory "本项目电池系统用 X 方案，importance=0.8"
```

## 架构铁律

```
小宝 ─▶ CLI ─▶ Conductor.send  ─▶  Provider.stream
                  │
                  │       ◀───  reflux 注入：怀玉阁召回 top-k 记忆 → system prompt
                  │
                  │  收到 tool_call ─▶
                  ▼
            GateInterceptor.check   (司辰阁守门)
                  │
                  ▼
            Sandbox.run             (工造司同进程沙箱)
                  │
                  ▼
            Tool.execute            (百工坊原子工具/知识工具)
                  │
                  ▼
            ToolResult ─▶ 写回 history role=tool
                  │
                  ▼
            Provider.stream         (下一轮，模型读到工具结果)
```

## 配置存储

**API Key 不进 .env**，存到平台用户目录：
- Windows: `%APPDATA%\xuanji\config.json`
- macOS: `~/Library/Application Support/xuanji/config.json`
- Linux: `~/.config/xuanji/config.json`

数据库（知识库 / 记忆库）放在 `user_data_dir`：
- Windows: `%LOCALAPPDATA%\xuanji\knowledge.db` / `memory.db`

支持四种 profile kind：
- `anthropic` / `openai` / `deepseek`：官方端点，只填 API Key
- `openai-compatible`：任意 OpenAI 兼容端点（OneAPI / Ollama / Kimi / 智谱 / 火山方舟……），填 Base URL + API Key

## 子系统国风代号

| 代号 | 英文 | 路径 | 职责一句话 |
|---|---|---|---|
| 百工坊 | Capability | `core/capability/` | Tool/Skill/Pack 三层封装，按模型能力适配 |
| 工造司 | Body | `core/body/` | 工具的运行时与沙箱（M0 仅 InProc） |
| 怀玉阁 | Memory | `core/memory/` | 三层 scope × 三类 kind × 衰减回流 |
| 稷下学宫 | Knowledge | `core/knowledge/` | FTS5 全文检索 + SkillGraph 锚点 |
| **天枢台** | **Neural** | `core/neural/` | **唯一调度中枢**，统一 Plan / Audit / 收口 |
| 司辰阁 | Gate | `core/gate/` | 横切权限与高危确认中间件 |
| 群英会 | Ensemble | `core/ensemble/` | 多 Agent 协作（M3+ 启用） |

## 质量门

```bash
uv run ruff check core/ tests/    # 全绿
uv run mypy core/                 # strict 模式 0 告警
uv run pytest                     # 82 测试全过
```
