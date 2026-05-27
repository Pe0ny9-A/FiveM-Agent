// 自动安装 xuanji 后端。
//
// 优先级：uv tool install → pipx install → python -m pip install --user
// 装完返回新解析出的可执行文件路径，让 backend.ts 重试 spawn。

import * as cp from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

const PACKAGE_NAME = "xuanji-fivem";

export interface InstallResult {
    method: "uv" | "pipx" | "pip";
    binPath: string;
}

export class XuanjiInstaller {
    private readonly logChannel: vscode.OutputChannel;

    constructor(logChannel: vscode.OutputChannel) {
        this.logChannel = logChannel;
    }

    async install(): Promise<InstallResult> {
        const uv = which("uv");
        if (uv) {
            this.logChannel.appendLine(`[installer] 找到 uv：${uv}，用 uv tool install`);
            await this.runWithProgress(
                "玄玑：用 uv tool 安装后端…",
                uv,
                ["tool", "install", PACKAGE_NAME, "--upgrade"],
            );
            const bin = findXuanjiBinAfterInstall();
            if (bin) {
                return { method: "uv", binPath: bin };
            }
            throw new Error("uv tool install 完成但找不到 xuanji 可执行，请重启 VS Code");
        }

        const pipx = which("pipx");
        if (pipx) {
            this.logChannel.appendLine(`[installer] 找到 pipx：${pipx}，用 pipx install`);
            await this.runWithProgress(
                "玄玑：用 pipx 安装后端…",
                pipx,
                ["install", PACKAGE_NAME, "--force"],
            );
            const bin = findXuanjiBinAfterInstall();
            if (bin) {
                return { method: "pipx", binPath: bin };
            }
            throw new Error("pipx install 完成但找不到 xuanji 可执行，请重启 VS Code");
        }

        const py = pickPython();
        if (!py) {
            throw new Error(
                "本机没找到 uv / pipx / python。请装 Python 3.12+ 或 uv 后重启 VS Code。",
            );
        }
        this.logChannel.appendLine(`[installer] 用 ${py} -m pip install --user`);
        await this.runWithProgress(
            `玄玑：用 ${path.basename(py)} pip install --user 安装后端…`,
            py,
            ["-m", "pip", "install", "--user", "--upgrade", PACKAGE_NAME],
        );
        const bin = findXuanjiBinAfterInstall();
        if (bin) {
            return { method: "pip", binPath: bin };
        }
        throw new Error("pip install 完成但找不到 xuanji 可执行，请重启 VS Code");
    }

    private async runWithProgress(
        title: string,
        command: string,
        args: string[],
    ): Promise<void> {
        return vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title,
                cancellable: false,
            },
            () => this.runCommand(command, args),
        );
    }

    private runCommand(command: string, args: string[]): Promise<void> {
        return new Promise((resolve, reject) => {
            this.logChannel.appendLine(
                `[installer] spawn ${command} ${args.join(" ")}`,
            );
            const child = cp.spawn(command, args, {
                env: { ...process.env, PYTHONIOENCODING: "utf-8" },
                stdio: ["ignore", "pipe", "pipe"],
                windowsHide: true,
            });
            const out: string[] = [];
            child.stdout?.on("data", (b: Buffer) => {
                const t = b.toString("utf-8");
                this.logChannel.append(t);
                out.push(t);
            });
            child.stderr?.on("data", (b: Buffer) => {
                const t = b.toString("utf-8");
                this.logChannel.append(t);
                out.push(t);
            });
            child.on("error", (err) =>
                reject(new Error(`无法启动 ${command}：${err.message}`)),
            );
            child.on("exit", (code) => {
                if (code === 0) {
                    resolve();
                } else {
                    const tail = out.join("").trim().split("\n").slice(-12).join("\n");
                    reject(new Error(`${command} 退出 code=${code}\n${tail}`));
                }
            });
        });
    }
}

function which(cmd: string): string | undefined {
    const isWin = process.platform === "win32";
    const exeNames = isWin ? [`${cmd}.exe`, `${cmd}.cmd`, cmd] : [cmd];
    const pathEnv = process.env.PATH || process.env.Path || "";
    const sep = isWin ? ";" : ":";
    for (const dir of pathEnv.split(sep)) {
        if (!dir) continue;
        for (const name of exeNames) {
            const full = path.join(dir, name);
            if (fs.existsSync(full)) {
                return full;
            }
        }
    }
    return undefined;
}

function pickPython(): string | undefined {
    const candidates =
        process.platform === "win32"
            ? ["py", "python", "python3"]
            : ["python3", "python"];
    for (const c of candidates) {
        const found = which(c);
        if (found) return found;
    }
    return undefined;
}

/**
 * 装完后扫常见位置：uv tools / pipx / pip --user 各自的 bin 目录。
 * 找到就返回完整路径。
 */
function findXuanjiBinAfterInstall(): string | undefined {
    const isWin = process.platform === "win32";
    const exe = isWin ? "xuanji.exe" : "xuanji";
    const home = process.env.HOME || process.env.USERPROFILE || "";

    const dirs: string[] = [];

    // PATH 第一优先（uv tool / pipx 都会更新 PATH）
    const pathEnv = process.env.PATH || process.env.Path || "";
    const sep = isWin ? ";" : ":";
    for (const d of pathEnv.split(sep)) {
        if (d) dirs.push(d);
    }

    if (home) {
        if (isWin) {
            dirs.push(
                path.join(home, ".local", "bin"),
                path.join(home, "AppData", "Roaming", "uv", "tools"),
                path.join(home, "AppData", "Roaming", "Python", "Scripts"),
                path.join(home, "AppData", "Local", "Programs", "Python", "Scripts"),
            );
        } else {
            dirs.push(
                path.join(home, ".local", "bin"),
                path.join(home, ".cargo", "bin"),
            );
        }
    }

    for (const d of dirs) {
        const full = path.join(d, exe);
        if (fs.existsSync(full)) {
            return full;
        }
    }
    return undefined;
}
