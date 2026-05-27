// Webview 宿主：把 React 工作台挂到一个 sidebar view + 一个独立 panel，
// 处理与 webview 之间的 postMessage 桥（RPC + 命令 + 后端通知转发）。

import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

import { XuanjiBackend } from "./backend";

interface IncomingRpcCall {
    type: "rpc.call";
    id: number;
    method: string;
    params?: Record<string, unknown>;
}

interface IncomingCommand {
    type: "command";
    command: string;
    args?: Record<string, unknown>;
}

type Incoming = IncomingRpcCall | IncomingCommand;

type NotificationFwd = (method: string, params: Record<string, unknown>) => void;

export class XuanjiWorkbench {
    private readonly extensionUri: vscode.Uri;
    private readonly notificationListeners = new Set<NotificationFwd>();
    private rpcUnsubscribe: (() => void) | null = null;
    private currentBackend: XuanjiBackend | null = null;
    private webviews = new Set<vscode.Webview>();

    constructor(context: vscode.ExtensionContext) {
        this.extensionUri = context.extensionUri;
    }

    registerSidebar(): vscode.Disposable {
        return vscode.window.registerWebviewViewProvider(
            "xuanji.sidebar",
            {
                resolveWebviewView: (view) => {
                    view.webview.options = this.webviewOptions();
                    view.webview.html = this.renderHtml(view.webview);
                    this.attachWebview(view.webview);
                    view.onDidDispose(() => this.detachWebview(view.webview));
                },
            },
            { webviewOptions: { retainContextWhenHidden: true } },
        );
    }

    openPanel(): void {
        const panel = vscode.window.createWebviewPanel(
            "xuanji.workbench",
            "玄玑工作台",
            vscode.ViewColumn.Beside,
            this.webviewOptions(),
        );
        panel.webview.html = this.renderHtml(panel.webview);
        this.attachWebview(panel.webview);
        panel.onDidDispose(() => this.detachWebview(panel.webview));
    }

    /** 由 extension.ts 在后端 ready 后注入。重启时会重新调用。 */
    bindBackend(backend: XuanjiBackend): void {
        this.currentBackend = backend;
        // 后端 push 的 notification 转发到所有 webview
        this.rpcUnsubscribe?.();
        const client = backend.rpc;
        this.rpcUnsubscribe = client.onNotification((method, params) => {
            const safe = (params || {}) as Record<string, unknown>;
            this.broadcast({ type: "notification", method, params: safe });
            this.notificationListeners.forEach((fn) => fn(method, safe));
        });
        // 让 webview 知道 backend ok
        this.broadcast({ type: "notification", method: "host.backend_ok", params: {} });
        void this.pushWorkspace();
    }

    notifyBackendError(message: string): void {
        this.broadcast({
            type: "notification",
            method: "host.backend_error",
            params: { message },
        });
    }

    /** 主动推一份 workspace 元信息——info() 调一遍。 */
    async pushWorkspace(): Promise<void> {
        if (!this.currentBackend?.isAlive()) {
            return;
        }
        try {
            const info = await this.currentBackend.rpc.call<{
                version: string;
                active_profile: string | null;
                assistant_alias: string;
                user_alias: string;
                project: {
                    root: string;
                    is_fivem_resource: boolean;
                    framework: string;
                    framework_confidence: number;
                    inventory: string;
                    target: string;
                    summary: string;
                };
            }>("info");
            this.broadcast({
                type: "workspace",
                payload: {
                    version: info.version,
                    active_profile: info.active_profile,
                    assistant_alias: info.assistant_alias,
                    user_alias: info.user_alias,
                    workspace_root: info.project.root,
                    is_fivem_resource: info.project.is_fivem_resource,
                    framework: info.project.framework,
                    framework_confidence: info.project.framework_confidence,
                    inventory: info.project.inventory,
                    target: info.project.target,
                    summary: info.project.summary,
                },
            });
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.notifyBackendError(msg);
        }
    }

    onNotification(fn: NotificationFwd): vscode.Disposable {
        this.notificationListeners.add(fn);
        return new vscode.Disposable(() => this.notificationListeners.delete(fn));
    }

    private attachWebview(webview: vscode.Webview): void {
        this.webviews.add(webview);
        webview.onDidReceiveMessage((msg: Incoming) => {
            void this.handleMessage(webview, msg);
        });
    }

    private detachWebview(webview: vscode.Webview): void {
        this.webviews.delete(webview);
    }

    private broadcast(message: unknown): void {
        for (const w of this.webviews) {
            void w.postMessage(message);
        }
    }

    private async handleMessage(webview: vscode.Webview, msg: Incoming): Promise<void> {
        if (!msg || typeof msg !== "object") {
            return;
        }
        if (msg.type === "rpc.call") {
            const id = msg.id;
            try {
                if (!this.currentBackend?.isAlive()) {
                    throw new Error("后端未启动");
                }
                const result = await this.currentBackend.rpc.call(
                    msg.method,
                    msg.params || {},
                );
                void webview.postMessage({ type: "rpc.result", id, result });
            } catch (e) {
                const err = formatRpcError(e);
                void webview.postMessage({ type: "rpc.error", id, error: err });
            }
        } else if (msg.type === "command") {
            const args = msg.args || {};
            // 限定白名单——只允许 xuanji.* 命令
            if (typeof msg.command === "string" && msg.command.startsWith("xuanji.")) {
                await vscode.commands.executeCommand(msg.command, args);
            }
        }
    }

    private webviewOptions(): vscode.WebviewOptions & vscode.WebviewPanelOptions {
        return {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this.extensionUri, "out", "webview"),
                vscode.Uri.joinPath(this.extensionUri, "media"),
            ],
        };
    }

    private renderHtml(webview: vscode.Webview): string {
        const buildDir = vscode.Uri.joinPath(this.extensionUri, "out", "webview");
        const buildDirFs = buildDir.fsPath;

        // Vite 产物没有 manifest（base="./"），手工解析 assets 目录
        const assetsDir = path.join(buildDirFs, "assets");
        let scriptUri = "";
        let styleUri = "";
        if (fs.existsSync(assetsDir)) {
            const files = fs.readdirSync(assetsDir);
            const js = files.find((f) => f.endsWith(".js"));
            const css = files.find((f) => f.endsWith(".css"));
            if (js) {
                scriptUri = webview
                    .asWebviewUri(vscode.Uri.joinPath(buildDir, "assets", js))
                    .toString();
            }
            if (css) {
                styleUri = webview
                    .asWebviewUri(vscode.Uri.joinPath(buildDir, "assets", css))
                    .toString();
            }
        }

        const csp =
            `default-src 'none'; ` +
            `img-src ${webview.cspSource} https: data:; ` +
            `style-src ${webview.cspSource} 'unsafe-inline'; ` +
            `script-src ${webview.cspSource} 'unsafe-inline'; ` +
            `font-src ${webview.cspSource};`;

        if (!scriptUri) {
            return /* html */ `<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<title>玄玑</title>
<style>body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);padding:24px}.tip{color:var(--vscode-descriptionForeground);font-size:12px}</style>
</head><body>
<h2>玄玑工作台尚未构建</h2>
<p class="tip">在 <code>apps/vscode/</code> 目录下跑 <code>pnpm install &amp;&amp; pnpm run build</code>（或 <code>npm run build</code>），然后用「玄玑：重启后端」或重新加载窗口。</p>
</body></html>`;
        }

        return /* html */ `<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>玄玑工作台</title>
${styleUri ? `<link rel="stylesheet" href="${styleUri}">` : ""}
</head><body>
<div id="root"></div>
<script type="module" src="${scriptUri}"></script>
</body></html>`;
    }

    dispose(): void {
        this.rpcUnsubscribe?.();
        this.rpcUnsubscribe = null;
        this.notificationListeners.clear();
        this.webviews.clear();
    }
}

function formatRpcError(e: unknown): { code: number; message: string; data?: unknown } {
    if (e && typeof e === "object" && "code" in e && "message" in e) {
        const cast = e as { code: number; message: string; data?: unknown };
        return { code: cast.code, message: cast.message, data: cast.data };
    }
    return {
        code: -32603,
        message: e instanceof Error ? e.message : String(e),
    };
}

