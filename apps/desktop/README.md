# 玄玑桌面端

Tauri 2 壳 + 嵌入 Web 前端。后端共享同一 Python 内核（`uv run xuanji serve` 起的 FastAPI）。

## 架构

```
┌────────────────────────────────────┐
│  Tauri 主进程（Rust）               │  ← 系统托盘 / 原生权限弹窗
│   └── webview ──────────┐          │
│        ↓                │          │
│  http://127.0.0.1:8765  │          │
└─────────────────────────┼──────────┘
                          ↓
              uv run xuanji serve
              （由 beforeDevCommand 自动启动）
                          │
                          ↓
              FastAPI + WebSocket
                          │
                          ↓
              Conductor + 21 个工具 + 知识/记忆库
```

桌面端只是一层壳——所有逻辑（Conductor / 工具系统 / 司辰阁 / 怀玉阁 / 稷下学宫）
都在 Python 后端跑。这样一份代码同时服务 Web 与桌面，未来加 iOS / Android 也是装个 webview 就行。

## 前置要求

- **Rust toolchain**：`rustup` + Rust 1.75+。Windows 上还需 MSVC build tools 或 GNU。
- **Node.js + pnpm**（或 npm）：跑 Tauri CLI 用。
- **uv**：Python 后端用。

## 跑

```bash
# 第一次：装 Tauri CLI
cd apps/desktop
pnpm install   # 或 npm install

# 开发模式（自动起 Python 后端 + Tauri webview）
pnpm tauri dev

# 打包 .exe / .app / .deb / .rpm
pnpm tauri build
```

打包产物在 `src-tauri/target/release/bundle/`。

## 工作流

`tauri dev` 会按 [tauri.conf.json](src-tauri/tauri.conf.json) 里的 `build.beforeDevCommand`
先起 `uv run xuanji serve --port 8765`，再打开 webview 指向 `http://127.0.0.1:8765`。

## 没装 Rust 也想用？

直接 `uv run xuanji serve` 后浏览器开 http://127.0.0.1:8765 也行——
桌面壳只是把这同一个页面包装成应用窗口，逻辑零差异。

## 图标

`src-tauri/icons/` 留空。打 release 前需要小宝放几张图（见 Tauri 文档：
icon.png / icon.ico / icon.icns 各一份）或运行：

```bash
pnpm tauri icon path/to/source.png
```

## 后续扩展点（M4+）

- 用 `#[tauri::command]` 暴露原生 OS 文件选择 / 通知 API，与司辰阁 HITLBridge
  对接（弹原生确认框，比 web 内嵌按钮更醒目）
- 用 `tauri::process` 管理 Python 后端进程：窗口关闭时自动停 server
- 系统托盘 + 全局热键
- 自动更新：用 `tauri-plugin-updater`
