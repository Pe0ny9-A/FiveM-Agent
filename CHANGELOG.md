# 玄玑 · CHANGELOG

所有重要的变更都记在这里。版本号遵守 [SemVer](https://semver.org/lang/zh-CN/)。

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
