// 玄玑 VS Code 扩展入口。
//
// 1. 启动 stdio 后端，建立 RPC
// 2. 状态栏跑 project.detect，显示 framework/inventory/target
// 3. 命令面板（旧版命令保留）+ 仪表盘 webview（旧）+ 工作台（1.0 新）

import * as path from "path";
import * as vscode from "vscode";

import { resolveBackendOptions, XuanjiBackend } from "./backend";
import { registerCommands } from "./commands";
import { XuanjiDashboard } from "./dashboard";
import { registerIntellisense } from "./intellisense";
import { XuanjiStatusBar } from "./statusBar";
import { XuanjiWorkbench } from "./workbench";

let backend: XuanjiBackend | null = null;
let statusBar: XuanjiStatusBar | null = null;
let dashboard: XuanjiDashboard | null = null;
let workbench: XuanjiWorkbench | null = null;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    backend = new XuanjiBackend();
    statusBar = new XuanjiStatusBar();
    dashboard = new XuanjiDashboard(context);
    workbench = new XuanjiWorkbench(context);

    context.subscriptions.push(backend, statusBar);
    context.subscriptions.push(workbench.registerSidebar());

    backend.onExit((code) => {
        const msg = `后端退出 code=${code}`;
        statusBar?.setError(msg);
        workbench?.notifyBackendError(msg);
    });

    try {
        await backend.ensureStarted(resolveBackendOptions());
        await statusBar.refresh(backend);
        workbench.bindBackend(backend);
        registerIntellisense(context, backend);
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        statusBar.setError(msg);
        workbench.notifyBackendError(msg);
        void vscode.window.showWarningMessage(
            `玄玑后端启动失败：${msg}。在设置里调整 xuanji.pythonPath 或 xuanji.useUv 后用「玄玑：重启后端」重试。`,
        );
    }

    // 状态栏订阅 chat.* 通知，显示 token / busy 状态
    context.subscriptions.push(
        workbench.onNotification((method, params) => {
            if (method === "chat.message_done") {
                const usage = params.usage as
                    | { input_tokens?: number; output_tokens?: number }
                    | null
                    | undefined;
                statusBar?.onChatTurnDone(
                    usage
                        ? {
                              input_tokens: Number(usage.input_tokens ?? 0),
                              output_tokens: Number(usage.output_tokens ?? 0),
                              stop_reason: (params.stop_reason as string) || null,
                          }
                        : null,
                );
            } else if (method === "chat.tool_run_started") {
                statusBar?.setBusy(true);
            } else if (method === "chat.turn_done" || method === "chat.turn_cancelled") {
                statusBar?.setBusy(false);
            } else if (method === "chat.error") {
                statusBar?.setBusy(false);
            }
        }),
    );

    registerCommands(context, {
        backend,
        statusBar,
        dashboard,
        workbench,
    });

    // 工作台命令——独立 panel
    context.subscriptions.push(
        vscode.commands.registerCommand("xuanji.openWorkbench", () => {
            workbench?.openPanel();
        }),
    );

    // webview 内点击链接：打开 workspace 内的文件并跳到指定行
    context.subscriptions.push(
        vscode.commands.registerCommand(
            "xuanji.openFile",
            async (args: { target?: string } = {}) => {
                await openFileTarget(args?.target);
            },
        ),
    );

    // 切换 workspace 文件夹时刷新状态栏 + 推 workspace
    context.subscriptions.push(
        vscode.workspace.onDidChangeWorkspaceFolders(async () => {
            if (backend && statusBar) {
                await statusBar.refresh(backend);
                await workbench?.pushWorkspace();
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
                    try {
                        await backend.restart(resolveBackendOptions());
                        if (statusBar) {
                            await statusBar.refresh(backend);
                        }
                        workbench?.bindBackend(backend);
                    } catch (err) {
                        const msg = err instanceof Error ? err.message : String(err);
                        statusBar?.setError(msg);
                        workbench?.notifyBackendError(msg);
                    }
                }
            }
        }),
    );
}

export function deactivate(): void {
    backend?.dispose();
    workbench?.dispose();
    backend = null;
    statusBar = null;
    dashboard = null;
    workbench = null;
}

/**
 * webview 里点击 [text](path#L42-51) 时调进来。
 * - 相对路径：在 workspace 根下解析
 * - 绝对路径：直接用
 * - #L<n> / #L<n>-<m>：高亮跳转到对应行
 */
async function openFileTarget(target?: string): Promise<void> {
    if (!target) return;
    let pathPart = target;
    let lineFrom: number | null = null;
    let lineTo: number | null = null;
    const hashIdx = target.indexOf("#");
    if (hashIdx >= 0) {
        pathPart = target.slice(0, hashIdx);
        const fragment = target.slice(hashIdx + 1);
        const m = /^L(\d+)(?:-L?(\d+))?$/.exec(fragment);
        if (m) {
            lineFrom = parseInt(m[1], 10);
            lineTo = m[2] ? parseInt(m[2], 10) : lineFrom;
        }
    }
    const fsPath = path.isAbsolute(pathPart)
        ? pathPart
        : (() => {
              const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
              if (!root) return pathPart;
              return path.join(root, pathPart);
          })();
    const uri = vscode.Uri.file(fsPath);
    try {
        const doc = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(doc, { preview: true });
        if (lineFrom !== null) {
            const start = new vscode.Position(Math.max(0, lineFrom - 1), 0);
            const end = new vscode.Position(
                Math.max(0, (lineTo ?? lineFrom) - 1),
                Number.MAX_SAFE_INTEGER,
            );
            editor.selection = new vscode.Selection(start, end);
            editor.revealRange(
                new vscode.Range(start, end),
                vscode.TextEditorRevealType.InCenter,
            );
        }
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        void vscode.window.showWarningMessage(`打不开 ${pathPart}：${msg}`);
    }
}
