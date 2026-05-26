# 玄玑 · CHANGELOG

所有重要的变更都记在这里。版本号遵守 [SemVer](https://semver.org/lang/zh-CN/)。

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
