// 状态栏：显示当前项目身份卡（framework/inventory/target） + 活跃 profile + 最近一轮 token 用量。
// 自动启动时跑一次 project.detect，点击打开仪表盘。
// 通过 workbench.onNotification 订阅 chat.message_done，更新 token 状态。

import * as vscode from "vscode";

import { XuanjiBackend } from "./backend";

interface InfoResult {
    active_profile: string | null;
    project: {
        is_fivem_resource: boolean;
        framework: string;
        framework_confidence: number;
        inventory: string;
        target: string;
        summary: string;
    };
}

interface UsageSnapshot {
    input_tokens: number;
    output_tokens: number;
    stop_reason: string | null;
}

export class XuanjiStatusBar implements vscode.Disposable {
    private item: vscode.StatusBarItem;
    private profileName: string | null = null;
    private projectLabel: string | null = null;
    private projectTooltip: string | null = null;
    private lastUsage: UsageSnapshot | null = null;
    private busy = false;

    constructor() {
        this.item = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            900,
        );
        this.item.command = "xuanji.openWorkbench";
        this.item.text = "$(sparkle) 玄玑";
        this.item.tooltip = "玄玑 · 加载中…";
        this.item.show();
    }

    setError(message: string): void {
        this.item.text = "$(error) 玄玑";
        this.item.tooltip = `玄玑 后端错误：${message}\n点击打开工作台可查看`;
    }

    setUnknown(): void {
        this.projectLabel = null;
        this.projectTooltip = null;
        this.render();
    }

    /** 当前一轮聊天产出 — token 显示。 */
    onChatTurnDone(usage: UsageSnapshot | null): void {
        this.lastUsage = usage;
        this.busy = false;
        this.render();
    }

    /** 标记当前在跑 — 加 sync 旋转图标。 */
    setBusy(busy: boolean): void {
        this.busy = busy;
        this.render();
    }

    setActiveProfile(name: string | null): void {
        this.profileName = name;
        this.render();
    }

    async refresh(backend: XuanjiBackend): Promise<void> {
        if (!backend.isAlive()) {
            this.setError("后端未启动");
            return;
        }
        try {
            const info = await backend.rpc.call<InfoResult>("info");
            this.profileName = info.active_profile;
            const p = info.project;
            if (!p.is_fivem_resource) {
                this.projectLabel = null;
                this.projectTooltip = "玄玑 · 当前目录不是 FiveM resource";
            } else {
                const fwShort = shortenFramework(p.framework);
                this.projectLabel = `${fwShort} / ${p.inventory} / ${p.target}`;
                this.projectTooltip =
                    `framework: ${p.framework} (${Math.round(
                        p.framework_confidence * 100,
                    )}%)\n` +
                    `inventory: ${p.inventory}\n` +
                    `target: ${p.target}\n` +
                    "─────\n" +
                    p.summary;
            }
            this.render();
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.setError(msg);
        }
    }

    private render(): void {
        const icon = this.busy ? "$(sync~spin)" : "$(sparkle)";
        const segments: string[] = ["玄玑"];
        if (this.profileName) {
            segments.push(this.profileName);
        }
        if (this.projectLabel) {
            segments.push(this.projectLabel);
        }
        if (this.lastUsage) {
            const u = this.lastUsage;
            segments.push(
                `↑${formatTokens(u.input_tokens)} ↓${formatTokens(u.output_tokens)}`,
            );
        }
        this.item.text = `${icon} ${segments.join(" · ")}`;
        const tooltipParts: string[] = [];
        if (this.profileName) {
            tooltipParts.push(`profile: ${this.profileName}`);
        }
        if (this.projectTooltip) {
            tooltipParts.push(this.projectTooltip);
        }
        if (this.lastUsage) {
            tooltipParts.push(
                `最近一轮 token: in=${this.lastUsage.input_tokens} · out=${this.lastUsage.output_tokens} · stop=${this.lastUsage.stop_reason || "-"}`,
            );
        }
        this.item.tooltip = tooltipParts.join("\n─────\n") || "玄玑";
    }

    dispose(): void {
        this.item.dispose();
    }
}

function shortenFramework(framework: string): string {
    switch (framework) {
        case "qbcore":
            return "QBCore";
        case "qbox":
            return "QBox";
        case "esx":
            return "ESX";
        case "standalone":
            return "Standalone";
        case "unknown":
            return "未识别";
        default:
            return framework;
    }
}

function formatTokens(n: number): string {
    if (n < 1000) return String(n);
    if (n < 10000) return (n / 1000).toFixed(1) + "k";
    return Math.round(n / 1000) + "k";
}
