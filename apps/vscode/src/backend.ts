// 后端进程托管：spawn / 重启 / 错误日志聚合。
// 后端是 stdio JSON-RPC server（python -m core.cli ipc），
// 我们把 stdout 喂给 JsonRpcClient，stderr 倒进 OutputChannel。

import * as cp from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

import { XuanjiInstaller } from "./installer";
import { JsonRpcClient } from "./rpc";

export interface BackendOptions {
    pythonPath: string;
    args: string[];
    cwd: string;
    useUv: boolean;
    autoInstall: boolean;
}

export class XuanjiBackend implements vscode.Disposable {
    private process: cp.ChildProcess | null = null;
    private rpcClient: JsonRpcClient | null = null;
    private readonly logChannel: vscode.OutputChannel;
    private starting: Promise<void> | null = null;
    private exitListener: ((code: number | null) => void) | null = null;
    private stderrTail: string[] = [];
    private installAttempted = false;
    private intentionalShutdown = false;

    constructor() {
        this.logChannel = vscode.window.createOutputChannel("玄玑 Backend");
    }

    get rpc(): JsonRpcClient {
        if (!this.rpcClient) {
            throw new Error("玄玑后端未启动");
        }
        return this.rpcClient;
    }

    isAlive(): boolean {
        return this.process !== null && this.rpcClient !== null;
    }

    async ensureStarted(options: BackendOptions): Promise<void> {
        if (this.isAlive()) {
            return;
        }
        if (this.starting) {
            return this.starting;
        }
        this.starting = this.startWithAutoInstall(options).finally(() => {
            this.starting = null;
        });
        return this.starting;
    }

    /**
     * 包一层自动安装：找不到 xuanji 可执行就装一遍重试一次。
     * 只在 autoInstall=true 且本进程内还没装过的时候触发。
     */
    private async startWithAutoInstall(options: BackendOptions): Promise<void> {
        try {
            await this.start(options);
            return;
        } catch (err) {
            const reason = err instanceof Error ? err.message : String(err);
            const looksMissing =
                /ENOENT|无法启动|not found|command not found|系统找不到指定的(?:文件|路径)/i.test(
                    reason,
                );
            if (
                !options.autoInstall ||
                this.installAttempted ||
                options.useUv ||
                options.pythonPath ||
                !looksMissing
            ) {
                throw err;
            }
            this.installAttempted = true;
            this.logChannel.appendLine(
                `[auto-install] 后端缺失（${reason}），尝试自动安装 xuanji-fivem`,
            );
            const installer = new XuanjiInstaller(this.logChannel);
            await installer.install();
            await this.start(options);
        }
    }

    private async start(options: BackendOptions): Promise<void> {
        let command: string;
        let args: string[];
        if (options.useUv) {
            command = process.platform === "win32" ? "uv.exe" : "uv";
            const uvArgs = options.pythonPath
                ? ["run", "--python", options.pythonPath]
                : ["run"];
            args = [...uvArgs, ...options.args];
        } else if (options.pythonPath) {
            // 用户显式配了解释器，老老实实用它跑 backendArgs
            command = options.pythonPath;
            args = options.args;
        } else {
            // 优先用装好的 xuanji 可执行文件——这样 wheel 装哪儿都行，
            // cwd 不必是仓库根
            const xuanjiBin = findXuanjiBin(options.cwd);
            if (xuanjiBin) {
                command = xuanjiBin;
                args = ["ipc"];
            } else {
                // 没装 xuanji，也没 venv python：直接抛"not found"，
                // 让 startWithAutoInstall 决定要不要触发自动安装
                const venvPy = findVenvPython(options.cwd);
                if (!venvPy) {
                    throw new Error(
                        "未找到 xuanji 可执行文件（command not found）",
                    );
                }
                command = venvPy;
                args = options.args;
            }
        }

        this.stderrTail = [];
        this.logChannel.appendLine(
            `[spawn] cwd=${options.cwd} cmd=${command} args=${JSON.stringify(args)}`,
        );

        let child: cp.ChildProcess;
        try {
            child = cp.spawn(command, args, {
                cwd: options.cwd,
                env: { ...process.env, PYTHONIOENCODING: "utf-8" },
                stdio: ["pipe", "pipe", "pipe"],
                windowsHide: true,
            });
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.logChannel.appendLine(`[spawn-error] ${msg}`);
            throw new Error(`无法启动 ${command}：${msg}`);
        }

        this.process = child;
        const rpcClient = new JsonRpcClient(child.stdin!);
        this.rpcClient = rpcClient;

        let exited = false;
        let exitCode: number | null = null;

        child.stdout!.on("data", (chunk: Buffer) => rpcClient.feed(chunk));
        child.stderr!.on("data", (chunk: Buffer) => {
            const text = chunk.toString("utf-8");
            this.logChannel.append(text);
            this.stderrTail.push(text);
            if (this.stderrTail.length > 50) {
                this.stderrTail.shift();
            }
        });
        child.on("error", (err) => {
            this.logChannel.appendLine(`[error] ${err.message}`);
        });
        child.on("exit", (code) => {
            exited = true;
            exitCode = code;
            this.logChannel.appendLine(`[exit] 后端进程退出 code=${code}`);
            this.rpcClient?.close();
            this.rpcClient = null;
            this.process = null;
            // dispose() / restart() 主动杀进程时不该报错
            if (this.intentionalShutdown) {
                this.intentionalShutdown = false;
                return;
            }
            this.exitListener?.(code);
        });

        // 用一次 info 调用确认握手成功。30 秒超时是给"首次启动 + 老 DB schema 迁移
        // + jieba 词典加载 + 兄弟进程占着 SQLite/LanceDB"留的兜底窗口；正常情况握手秒级返回。
        try {
            await Promise.race([
                rpcClient.call("info"),
                this.wait(30000).then(() => {
                    throw new Error("后端 30 秒内没响应 info 调用");
                }),
            ]);
            this.logChannel.appendLine("[ok] 握手通过，后端就绪");
        } catch (e) {
            const reason = e instanceof Error ? e.message : String(e);
            const tail = this.stderrTail.join("").trim().split("\n").slice(-8).join("\n");
            const hint = exited
                ? `后端进程退出 code=${exitCode}`
                : "进程仍在跑但握手失败";
            const detail = tail ? `\n— stderr 末尾 —\n${tail}` : "";
            this.logChannel.appendLine(`[fail] ${hint}：${reason}${detail}`);
            this.dispose();
            throw new Error(`${hint}：${reason}${detail}`);
        }
    }

    private wait(ms: number): Promise<void> {
        return new Promise((r) => setTimeout(r, ms));
    }

    onExit(listener: (code: number | null) => void): void {
        this.exitListener = listener;
    }

    showLog(): void {
        this.logChannel.show();
    }

    async restart(options: BackendOptions): Promise<void> {
        this.dispose();
        await this.ensureStarted(options);
    }

    dispose(): void {
        if (this.process) {
            this.intentionalShutdown = true;
            try {
                if (process.platform === "win32" && this.process.pid) {
                    // Windows 上 process.kill 只杀父进程，xuanji.exe → python.exe
                    // 子进程会变孤儿。用 taskkill /T /F 杀整棵树。
                    cp.spawn("taskkill", [
                        "/PID",
                        String(this.process.pid),
                        "/T",
                        "/F",
                    ], { windowsHide: true, stdio: "ignore" });
                } else {
                    this.process.kill();
                }
            } catch {
                /* ignore */
            }
        }
        this.process = null;
        this.rpcClient?.close();
        this.rpcClient = null;
    }
}

/**
 * 自动找 xuanji 项目根：从 candidate 往上走，
 * 找到含 `pyproject.toml` 且 `name = "xuanji"` 就返回。
 */
function findXuanjiRoot(candidate: string): string | undefined {
    let current = path.resolve(candidate);
    for (let i = 0; i < 10; i++) {
        const pj = path.join(current, "pyproject.toml");
        if (fs.existsSync(pj)) {
            try {
                const text = fs.readFileSync(pj, "utf-8");
                if (/name\s*=\s*"xuanji"/.test(text)) {
                    return current;
                }
            } catch {
                /* ignore */
            }
        }
        const parent = path.dirname(current);
        if (parent === current) {
            return undefined;
        }
        current = parent;
    }
    return undefined;
}

/**
 * 在 cwd 里找 .venv 里的 Python——uv / python -m venv 创建的 venv。
 * Windows: .venv/Scripts/python.exe
 * 其它：   .venv/bin/python
 */
function findVenvPython(cwd: string): string | undefined {
    const candidates =
        process.platform === "win32"
            ? [
                  path.join(cwd, ".venv", "Scripts", "python.exe"),
                  path.join(cwd, "venv", "Scripts", "python.exe"),
              ]
            : [
                  path.join(cwd, ".venv", "bin", "python"),
                  path.join(cwd, "venv", "bin", "python"),
              ];
    for (const c of candidates) {
        if (fs.existsSync(c)) {
            return c;
        }
    }
    return undefined;
}

/**
 * 找已装好的 xuanji 可执行文件。优先级：
 * 1. cwd 内的 .venv/Scripts/xuanji.exe (Windows) 或 .venv/bin/xuanji (Unix)
 * 2. PATH 上的 xuanji（pipx / uv tool / 系统 python 全局装）
 *
 * 找到就返回完整路径或裸命令名（让 OS 通过 PATH 解析）。
 */
function findXuanjiBin(cwd: string): string | undefined {
    const isWin = process.platform === "win32";
    const venvCandidates = isWin
        ? [
              path.join(cwd, ".venv", "Scripts", "xuanji.exe"),
              path.join(cwd, "venv", "Scripts", "xuanji.exe"),
          ]
        : [
              path.join(cwd, ".venv", "bin", "xuanji"),
              path.join(cwd, "venv", "bin", "xuanji"),
          ];
    for (const c of venvCandidates) {
        if (fs.existsSync(c)) {
            return c;
        }
    }

    // PATH 兜底：扫一下 PATH 里有没有 xuanji
    const pathEnv = process.env.PATH || process.env.Path || "";
    const pathSep = isWin ? ";" : ":";
    const exeName = isWin ? "xuanji.exe" : "xuanji";
    for (const dir of pathEnv.split(pathSep)) {
        if (!dir) {
            continue;
        }
        const full = path.join(dir, exeName);
        if (fs.existsSync(full)) {
            return full;
        }
    }
    return undefined;
}

export function resolveBackendOptions(): BackendOptions {
    const cfg = vscode.workspace.getConfiguration("xuanji");
    const pyFromCfg = cfg.get<string>("pythonPath", "");
    const args = cfg.get<string[]>("backendArgs", ["-m", "xuanji.cli", "ipc"]);
    const useUv = cfg.get<boolean>("useUv", false);
    const cfgCwd = cfg.get<string>("workdir", "");
    const autoInstall = cfg.get<boolean>("autoInstall", true);

    let cwd: string;
    if (cfgCwd) {
        cwd = cfgCwd;
    } else {
        const wsRoot =
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
        // 开发模式（useUv）需要 cwd 里能 import xuanji；装好包后则随 workspace 走
        cwd = useUv ? findXuanjiRoot(wsRoot) || wsRoot : wsRoot;
    }

    return {
        pythonPath: pyFromCfg,
        args,
        cwd: path.resolve(cwd),
        useUv,
        autoInstall,
    };
}
