// LSP 风格 stdio JSON-RPC 客户端。
// 跟后端 core/ipc/framing.py 严格对齐：Content-Length\r\n\r\n + utf-8 JSON。
//
// 双向通道：除了 request/response，还订阅 server-push notification（无 id）。

import { Writable } from "stream";

export interface RpcError {
    code: number;
    message: string;
    data?: unknown;
}

export class RpcCallError extends Error {
    code: number;
    data: unknown;
    constructor(err: RpcError) {
        super(err.message);
        this.code = err.code;
        this.data = err.data;
        this.name = "RpcCallError";
    }
}

interface PendingCall {
    resolve: (value: unknown) => void;
    reject: (reason: unknown) => void;
}

type NotificationListener = (
    method: string,
    params: Record<string, unknown>,
) => void;

export class JsonRpcClient {
    private nextId = 1;
    private pending = new Map<number, PendingCall>();
    private buffer = Buffer.alloc(0);
    private closed = false;
    private notificationListeners = new Set<NotificationListener>();

    constructor(private readonly stdin: Writable) {}

    feed(chunk: Buffer): void {
        if (this.closed) {
            return;
        }
        this.buffer = Buffer.concat([this.buffer, chunk]);
        while (true) {
            const headerEnd = this.buffer.indexOf("\r\n\r\n");
            if (headerEnd < 0) {
                return;
            }
            const headerText = this.buffer.subarray(0, headerEnd).toString("ascii");
            const match = headerText.match(/Content-Length:\s*(\d+)/i);
            if (!match) {
                this.buffer = this.buffer.subarray(headerEnd + 4);
                continue;
            }
            const length = parseInt(match[1], 10);
            const bodyStart = headerEnd + 4;
            if (this.buffer.length < bodyStart + length) {
                return;
            }
            const bodyBuf = this.buffer.subarray(bodyStart, bodyStart + length);
            this.buffer = this.buffer.subarray(bodyStart + length);
            try {
                const msg = JSON.parse(bodyBuf.toString("utf-8"));
                this.handleMessage(msg);
            } catch (e) {
                console.error("[xuanji.rpc] 解析消息失败：", e);
            }
        }
    }

    private handleMessage(msg: {
        id?: number;
        method?: string;
        params?: Record<string, unknown>;
        result?: unknown;
        error?: RpcError;
    }): void {
        // 没 id 但有 method = server push notification
        if (typeof msg.id !== "number") {
            if (typeof msg.method === "string") {
                const params = msg.params || {};
                this.notificationListeners.forEach((fn) => fn(msg.method!, params));
            }
            return;
        }
        const pending = this.pending.get(msg.id);
        if (!pending) {
            return;
        }
        this.pending.delete(msg.id);
        if (msg.error) {
            pending.reject(new RpcCallError(msg.error));
        } else {
            pending.resolve(msg.result);
        }
    }

    call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
        if (this.closed) {
            return Promise.reject(new Error("RPC 通道已关闭"));
        }
        const id = this.nextId++;
        const message = { jsonrpc: "2.0", id, method, params };
        return new Promise<T>((resolve, reject) => {
            this.pending.set(id, {
                resolve: resolve as (v: unknown) => void,
                reject,
            });
            const body = Buffer.from(JSON.stringify(message), "utf-8");
            const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "ascii");
            this.stdin.write(Buffer.concat([header, body]), (err) => {
                if (err) {
                    this.pending.delete(id);
                    reject(err);
                }
            });
        });
    }

    onNotification(fn: NotificationListener): () => void {
        this.notificationListeners.add(fn);
        return () => this.notificationListeners.delete(fn);
    }

    close(): void {
        this.closed = true;
        for (const pending of this.pending.values()) {
            pending.reject(new Error("RPC 通道已关闭"));
        }
        this.pending.clear();
        this.notificationListeners.clear();
    }
}
