# 玄玑 · CHANGELOG

所有重要的变更都记在这里。版本号遵守 [SemVer](https://semver.org/lang/zh-CN/)。

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
