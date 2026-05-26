// 玄玑 VS Code 扩展入口。
//
// 三件事：
// 1. 启动 stdio 后端，建立 RPC
// 2. 状态栏自动跑 project.detect，显示 framework/inventory/target
// 3. 命令面板五个动作 + 仪表盘 webview

import * as vscode from "vscode";

import { resolveBackendOptions, XuanjiBackend } from "./backend";
import { registerCommands } from "./commands";
import { XuanjiDashboard } from "./dashboard";
import { XuanjiStatusBar } from "./statusBar";

let backend: XuanjiBackend | null = null;
let statusBar: XuanjiStatusBar | null = null;
let dashboard: XuanjiDashboard | null = null;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    backend = new XuanjiBackend();
    statusBar = new XuanjiStatusBar();
    dashboard = new XuanjiDashboard(context);

    context.subscriptions.push(backend, statusBar);

    backend.onExit((code) => {
        statusBar?.setError(`后端退出 code=${code}`);
    });

    try {
        await backend.ensureStarted(resolveBackendOptions());
        await statusBar.refresh(backend);
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        statusBar.setError(msg);
        void vscode.window.showWarningMessage(
            `玄玑后端启动失败：${msg}。在设置里调整 xuanji.pythonPath 或 xuanji.useUv 后用「玄玑：重启后端」重试。`,
        );
    }

    registerCommands(context, {
        backend,
        statusBar,
        dashboard,
    });

    // 切换 workspace 文件夹时刷新状态栏
    context.subscriptions.push(
        vscode.workspace.onDidChangeWorkspaceFolders(async () => {
            if (backend && statusBar) {
                await statusBar.refresh(backend);
            }
        }),
    );

    // 配置变更（pythonPath / useUv 等）→ 自动重启
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(async (e) => {
            if (
                e.affectsConfiguration("xuanji.pythonPath") ||
                e.affectsConfiguration("xuanji.backendArgs") ||
                e.affectsConfiguration("xuanji.useUv") ||
                e.affectsConfiguration("xuanji.workdir")
            ) {
                if (backend) {
                    await backend.restart(resolveBackendOptions());
                    if (statusBar) {
                        await statusBar.refresh(backend);
                    }
                }
            }
        }),
    );
}

export function deactivate(): void {
    backend?.dispose();
    backend = null;
    statusBar = null;
    dashboard = null;
}
