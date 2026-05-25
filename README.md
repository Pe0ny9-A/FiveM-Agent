# 玄玑 · FiveM 智能体

> 北斗第三星·主调度运转。一位性感知性的大姐姐，工作时极致认真，对话时偶尔调侃带点污。

FiveM 资源插件开发 + 服务器运维治理双线助手。深度熟悉 QBCore / QBox / ESX / OX 全家桶。
**也帮你写 NPC 插件**：ped 配置、巡逻 AI、对话树、行为状态机、qb-target / ox_target 交互——产物是 Lua 代码与 JSON 配置，运行时由 FiveM server 自己跑。玄玑不直接控制运行中的游戏世界。

[![python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![status](https://img.shields.io/badge/status-0.2.0%20alpha-orange)]()
[![tests](https://img.shields.io/badge/tests-108%20passed-brightgreen)]()
[![tools](https://img.shields.io/badge/tools-21%20registered-blueviolet)]()

## 当前进度（0.2.0 · 自演化能力闭环）

- [x] **M0 骨架**：项目结构、uv、ruff、mypy strict、pytest
- [x] **LLM 抽象**：统一消息/内容块/Delta，跨厂商无差别
- [x] **三家 Provider**：Anthropic / OpenAI / DeepSeek 都可用，并支持任意 OpenAI 兼容端点
- [x] **配置系统**：跨平台 JSON 配置 + 四种 profile kind
- [x] **玄玑人设**：5 模式（chat/dev/ops/review/gate）× 3 温度 + 双向可调称呼 + 自演化导引
- [x] **天枢台 Conductor**：唯一调度入口 + 多轮 tool loop + reflux 自动注入
- [x] **百工坊**：Tool/Registry + RiskTag 五档
- [x] **司辰阁**：横切 Gate 中间件 + DefaultPolicy + HITLBridge
- [x] **工造司**：InProcSandbox 同进程沙箱
- [x] **稷下学宫**：SQLite FTS5 + SkillGraph + 含 NPC 模板的 5 套种子库
- [x] **怀玉阁**：SQLite + 三层 scope × 三类 kind + 衰减打分 + Reflux
- [x] **自演化能力**（0.2.0 新）：知识 ingestion + 记忆主动读写 + 技能系统 + 工具提案
- [x] **21 个工具**：5 原子 + 2 知识 + 4 元 + 2 记忆 + 4 ingest + 3 skill + 1 factory
- [x] **CLI**：`info` / `chat` / `config` / `knowledge` / `memory` / `skill` / `tool`
- [x] **质量门**：ruff/mypy strict/pytest 三件套全绿，**108 个单测**

**未做（M3+ 待续）**：群英会 Ensemble 多 Agent 协作、Tauri 桌面端、Web 前端、向量检索（LanceDB）、爬虫与文档增量更新、合议式仲裁、ToolFactory 自动实现链路、jieba 中文分词。

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
