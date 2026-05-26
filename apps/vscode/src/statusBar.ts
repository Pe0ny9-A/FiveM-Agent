// 状态栏：显示当前项目身份卡（framework/inventory/target）。
// 自动启动时跑一次 project.detect，点击打开仪表盘。

import * as vscode from "vscode";

import { XuanjiBackend } from "./backend";

interface InfoResult {
    project: {
        is_fivem_resource: boolean;
        framework: string;
        framework_confidence: number;
        inventory: string;
        target: string;
        summary: string;
    };
}

export class XuanjiStatusBar implements vscode.Disposable {
    private item: vscode.StatusBarItem;

    constructor() {
        this.item = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            900,
        );
        this.item.command = "xuanji.openDashboard";
        this.item.text = "$(sparkle) 玄玑";
        this.item.tooltip = "玄玑 · 加载中…";
        this.item.show();
    }

    setError(message: string): void {
        this.item.text = "$(error) 玄玑";
        this.item.tooltip = `玄玑 后端错误：${message}\n点击打开仪表盘可重启`;
    }

    setUnknown(): void {
        this.item.text = "$(circle-outline) 玄玑";
        this.item.tooltip = "玄玑 · 当前目录不是 FiveM resource";
    }

    async refresh(backend: XuanjiBackend): Promise<void> {
        if (!backend.isAlive()) {
            this.setError("后端未启动");
            return;
        }
        try {
            const info = await backend.rpc.call<InfoResult>("info");
            const p = info.project;
            if (!p.is_fivem_resource) {
                this.setUnknown();
                return;
            }
            const fwShort = shortenFramework(p.framework);
            this.item.text = `$(sparkle) 玄玑 · ${fwShort} / ${p.inventory} / ${p.target}`;
            this.item.tooltip =
                `framework: ${p.framework} (${Math.round(
                    p.framework_confidence * 100,
                )}%)\n` +
                `inventory: ${p.inventory}\n` +
                `target: ${p.target}\n` +
                "─────\n" +
                p.summary;
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.setError(msg);
        }
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
