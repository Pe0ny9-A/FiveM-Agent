# 玄玑 · VS Code 插件

把玄玑（FiveM 智能体）作为 stdio 后端跑起来，VS Code 里就能用。

## 两种使用模式

### 模式 A · 用户装好的 xuanji 包（推荐）

适合：日常用，不改 xuanji 内核。

```bash
# 1. 全局或独立环境装 xuanji
uv tool install xuanji          # 推荐
# 或：pipx install xuanji
# 或：python -m venv ~/.xuanji-venv && ~/.xuanji-venv/bin/pip install xuanji

# 2. 首次配置
xuanji init     # 跟提示填 API Key、导入种子
xuanji doctor   # 验证全绿
```

VS Code 里装上玄玑插件，**啥都不必配**——插件会自动找到 PATH 上的 `xuanji` 命令。

### 模式 B · 仓库开发模式

适合：在玄玑代码上做内核开发。

```bash
cd f:/FiveM-Agent
uv sync --extra dev

cd apps/vscode
pnpm install
pnpm run build
# 在 VS Code 里 F5 → "Run Extension"
```

`.vscode/settings.json` 里：

```json
{
  "xuanji.useUv": true,
  "xuanji.workdir": "f:/FiveM-Agent"
}
```

## 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `xuanji.pythonPath` | `""` | 解释器路径。优先级：本设置 → `.venv` → PATH 上的 `xuanji` → `py`/`python3` |
| `xuanji.backendArgs` | `["-m", "xuanji.cli", "ipc"]` | 后端启动参数。装好包时插件优先用 `xuanji ipc` 简写 |
| `xuanji.workdir` | `""` | 后端工作目录。装包模式留空即可 |
| `xuanji.useUv` | `false` | 用 `uv run` 启动。仓库开发期开 |

## 命令面板

按 `Ctrl+Shift+P` 输入 "玄玑"：

- **检测当前项目** — 跑 detector，更新状态栏
- **分析这个 resource** — 列 exports / events / 高频 API
- **从预设新建 resource** — 选预设、填名字、生成
- **在知识库搜索…** — 混合检索
- **把选中保存为记忆** — 当前编辑器选中文本入怀玉阁
- **打开仪表盘** — 三栏 webview（项目身份 / 预设草案 / 技能）
- **重启后端** — pythonPath 改了用这个

## 状态栏

右下角 `$(sparkle) 玄玑 · QBox / ox_inventory / ox_target` 这种格式。
点击打开仪表盘。

## 排错

- **后端起不来**：看输出面板「玄玑 Backend」。
  - 装包模式：先在终端跑一遍 `xuanji doctor` 看缺什么；常见是 PATH 找不到 `xuanji`（重开终端 / IDE）
  - 开发模式：检查 `xuanji.workdir` 是否指对仓库根、`uv` 是否在 PATH
- **状态栏显示 `(error) 玄玑`**：执行 `玄玑：重启后端`。
- **stdout 里出现日志污染协议**：CLI 那边日志走 `stderr`，如果你魔改了 `xuanji.cli ipc` 入口，注意别 `print` 到 stdout。

## 协议

后端是 LSP 风格 stdio JSON-RPC：

```
Content-Length: <len>\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"...","params":{...}}
```

完整方法表见 `xuanji/ipc/dispatcher.py`。
