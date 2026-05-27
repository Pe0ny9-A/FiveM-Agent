// VS Code webview API 桥：postMessage ⇆ extension host。
// 协议：
//   webview→host : { type:"rpc.call", id, method, params }
//   host→webview : { type:"rpc.result", id, result } 或 { type:"rpc.error", id, error }
//   host→webview : { type:"notification", method, params }   (后端 push)
//   host→webview : { type:"workspace", payload }             (workspace 元信息推送)

interface VsCodeApi {
    postMessage(message: unknown): void;
    getState<T = unknown>(): T | undefined;
    setState<T = unknown>(state: T): void;
}

declare global {
    interface Window {
        acquireVsCodeApi(): VsCodeApi;
    }
}

let vscode: VsCodeApi | null = null;
function getVscode(): VsCodeApi {
    if (!vscode) {
        vscode = window.acquireVsCodeApi();
    }
    return vscode;
}

interface PendingCall {
    resolve: (value: unknown) => void;
    reject: (reason: unknown) => void;
}

const pending = new Map<number, PendingCall>();
let nextId = 1;

type NotificationHandler = (method: string, params: Record<string, unknown>) => void;
type WorkspaceHandler = (payload: Record<string, unknown>) => void;

const notificationListeners = new Set<NotificationHandler>();
const workspaceListeners = new Set<WorkspaceHandler>();

window.addEventListener("message", (e: MessageEvent) => {
    const msg = e.data;
    if (!msg || typeof msg !== "object") {
        return;
    }
    if (msg.type === "rpc.result") {
        const p = pending.get(msg.id);
        if (p) {
            pending.delete(msg.id);
            p.resolve(msg.result);
        }
    } else if (msg.type === "rpc.error") {
        const p = pending.get(msg.id);
        if (p) {
            pending.delete(msg.id);
            p.reject(new RpcCallError(msg.error));
        }
    } else if (msg.type === "notification") {
        notificationListeners.forEach((fn) => fn(msg.method, msg.params || {}));
    } else if (msg.type === "workspace") {
        workspaceListeners.forEach((fn) => fn(msg.payload || {}));
    }
});

export interface RpcError {
    code: number;
    message: string;
    data?: unknown;
}

export class RpcCallError extends Error {
    code: number;
    data: unknown;
    constructor(err: RpcError) {
        super(err?.message || "RPC error");
        this.code = err?.code ?? -32603;
        this.data = err?.data;
        this.name = "RpcCallError";
    }
}

export function rpcCall<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
): Promise<T> {
    const id = nextId++;
    return new Promise<T>((resolve, reject) => {
        pending.set(id, {
            resolve: resolve as (v: unknown) => void,
            reject,
        });
        getVscode().postMessage({ type: "rpc.call", id, method, params });
    });
}

export function onNotification(fn: NotificationHandler): () => void {
    notificationListeners.add(fn);
    return () => notificationListeners.delete(fn);
}

export function onWorkspace(fn: WorkspaceHandler): () => void {
    workspaceListeners.add(fn);
    return () => workspaceListeners.delete(fn);
}

export function postCommand(command: string, args: Record<string, unknown> = {}): void {
    getVscode().postMessage({ type: "command", command, args });
}

export function persistState<T extends object>(state: T): void {
    getVscode().setState(state);
}

export function loadState<T = unknown>(): T | undefined {
    return getVscode().getState<T>();
}
