# 玄玑 · FiveM 智能体

> 北斗第三星·主调度运转。一位性感知性的大姐姐，工作时极致认真，对话时偶尔调侃带点污。

FiveM 资源插件开发 + 服务器运维治理双线助手。深度熟悉 QBCore / QBox / ESX / OX 全家桶。
**也帮你写 NPC 插件**：ped 配置、巡逻 AI、对话树、行为状态机、qb-target / ox_target 交互——产物是 Lua 代码与 JSON 配置，运行时由 FiveM server 自己跑。玄玑不直接控制运行中的游戏世界。

[![python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![status](https://img.shields.io/badge/status-0.1.0%20alpha-orange)]()
[![tests](https://img.shields.io/badge/tests-82%20passed-brightgreen)]()

## 当前进度（0.1.0 · M0+M1+M2 已闭环）

- [x] **M0 骨架**：项目结构、uv、ruff、mypy strict、pytest
- [x] **LLM 抽象**：统一消息/内容块/Delta，跨厂商无差别
- [x] **三家 Provider**：Anthropic / OpenAI / DeepSeek 都可用，并支持任意 OpenAI 兼容端点
- [x] **配置系统**：跨平台 JSON 配置 + 四种 profile kind
- [x] **玄玑人设**：5 模式（chat/dev/ops/review/gate）× 3 温度（playful/balanced/professional）+ 双向可调称呼
- [x] **天枢台 Conductor**：唯一调度入口 + 多轮 tool loop
- [x] **百工坊**：Tool/Skill/Pack 三层抽象 + RiskTag 五档
- [x] **司辰阁**：横切 Gate 中间件 + DefaultPolicy + HITLBridge
- [x] **工造司**：InProcSandbox 同进程沙箱
- [x] **5 个原子工具**：read_file / write_file / list_dir / ripgrep / run_shell
- [x] **稷下学宫**：SQLite FTS5 + SkillGraph + QBCore/ox_lib/ox_inventory/cfx 种子库
- [x] **2 个知识工具**：knowledge_search / lookup_symbol
- [x] **怀玉阁**：SQLite + 三层 scope（working/session/project/user 接口）+ 三类 kind（episodic/semantic/procedural）+ 衰减打分 + Reflux 自动注入
- [x] **CLI**：`info` / `chat` / `config (×7)` / `knowledge (×6)` / `memory (×6)`
- [x] **质量门**：ruff/mypy strict/pytest 三件套全绿，**82 个单测**

**未做（M3+ 待续）**：群英会 Ensemble 多 Agent 协作、Tauri 桌面端、Web 前端、向量检索（LanceDB）、爬虫与文档增量更新、合议式仲裁、ToolFactory。

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
│   ├── path                        # 配置文件路径
│   ├── list / show / add           # profile 增改查
│   ├── use / remove                # 切换 / 删除
│   ├── alias --self X --user Y     # 改玄玑/用户对话称呼
│   └── test                        # 实测 profile 可用
├── knowledge
│   ├── path / stats / list         # 知识库路径与统计
│   ├── ingest                      # 导入种子（默认 QBCore/ox_lib...）
│   ├── search "…"                  # FTS5 全文检索
│   ├── symbol "…"                  # 精准查 API 卡片
│   └── clear <namespace>           # 清空命名空间
└── memory
    ├── path / stats / list         # 记忆库路径与统计
    ├── write "…" -k semantic       # 手动写入记忆
    ├── recall "…"                  # 与 chat reflux 同路径
    ├── forget --namespace X        # 按命名空间/作用域/id 删除
    └── consolidate                 # 固化 episodic
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
