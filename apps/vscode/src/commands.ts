// 命令面板五件套 + 重启后端。

import * as path from "path";
import * as vscode from "vscode";

import { resolveBackendOptions, XuanjiBackend } from "./backend";
import { XuanjiDashboard } from "./dashboard";
import { XuanjiStatusBar } from "./statusBar";

interface Deps {
    backend: XuanjiBackend;
    statusBar: XuanjiStatusBar;
    dashboard: XuanjiDashboard;
}

interface DetectResult {
    is_fivem_resource: boolean;
    framework: string;
    framework_confidence: number;
    inventory: string;
    target: string;
    summary: string;
    notes: string[];
    sub_resources: string[];
}

interface AnalyzeResult {
    resource_path: string;
    is_fivem_resource: boolean;
    framework: string;
    files_scanned: number;
    exports: string[];
    events_registered: string[];
    events_triggered: string[];
    callbacks: string[];
    top_api_calls: Record<string, number>;
}

interface PresetItem {
    key: string;
    source: string;
    framework: string;
    label: string;
}

interface ScaffoldResult {
    target_dir: string;
    preset: string;
    files_written: string[];
    files_skipped: string[];
}

interface KnowledgeHit {
    namespace: string;
    source_title: string;
    section: string | null;
    text: string;
    score: number;
    source: string;
    anchor_symbol: string | null;
}

export function registerCommands(context: vscode.ExtensionContext, deps: Deps): void {
    const { backend, statusBar, dashboard } = deps;

    context.subscriptions.push(
        vscode.commands.registerCommand("xuanji.detectProject", async (uri?: vscode.Uri) => {
            await ensureAlive(backend, statusBar);
            const target = pickPath(uri);
            const params: Record<string, unknown> = {};
            if (target) {
                params.path = target;
            }
            const detect = await backend.rpc.call<DetectResult>("project.detect", params);
            await statusBar.refresh(backend);
            await showDetectResult(detect);
        }),

        vscode.commands.registerCommand("xuanji.analyzeResource", async (uri?: vscode.Uri) => {
            await ensureAlive(backend, statusBar);
            const target =
                pickPath(uri) ??
                (await vscode.window.showInputBox({
                    prompt: "要分析的 resource 路径（相对 workspace）",
                    placeHolder: "resources/[my-pack]/myresource",
                }));
            if (!target) {
                return;
            }
            const result = await backend.rpc.call<AnalyzeResult>("project.analyze", {
                path: target,
            });
            await showAnalyzeResult(result);
        }),

        vscode.commands.registerCommand("xuanji.scaffoldFromPreset", async () => {
            await ensureAlive(backend, statusBar);
            const presets = await backend.rpc.call<{ items: PresetItem[] }>("presets.list");
            if (presets.items.length === 0) {
                void vscode.window.showWarningMessage(
                    "暂无可用预设。先在 CLI 用 `xuanji preset accept` 激活一个草案。",
                );
                return;
            }
            const pick = await vscode.window.showQuickPick(
                presets.items.map((p) => ({
                    label: `${p.label}`,
                    description: `${p.framework} · ${p.source}`,
                    detail: p.key,
                    preset: p,
                })),
                { placeHolder: "选一个预设" },
            );
            if (!pick) {
                return;
            }
            const name = await vscode.window.showInputBox({
                prompt: "新 resource 名（也是目录名）",
                placeHolder: "my-pack",
            });
            if (!name) {
                return;
            }
            const target = await vscode.window.showInputBox({
                prompt: "生成到哪个相对目录？默认 resources/",
                value: "resources",
            });
            const result = await backend.rpc.call<ScaffoldResult>("project.scaffold", {
                preset: pick.preset.key,
                name,
                target: target || ".",
            });
            void vscode.window.showInformationMessage(
                `已生成 ${result.files_written.length} 个文件到 ${result.target_dir}`,
            );
            const openIt = await vscode.window.showInformationMessage(
                "要在编辑器里打开 fxmanifest.lua 吗？",
                "打开",
                "不用",
            );
            if (openIt === "打开") {
                const manifest = path.join(result.target_dir, "fxmanifest.lua");
                const doc = await vscode.workspace.openTextDocument(manifest);
                await vscode.window.showTextDocument(doc);
            }
        }),

        vscode.commands.registerCommand("xuanji.searchKnowledge", async () => {
            await ensureAlive(backend, statusBar);
            const query = await vscode.window.showInputBox({
                prompt: "在玄玑知识库里查什么？",
                placeHolder: "QBCore 创建可使用物品",
            });
            if (!query) {
                return;
            }
            const result = await backend.rpc.call<{ items: KnowledgeHit[] }>(
                "knowledge.search",
                { query, k: 8, hybrid: true },
            );
            if (result.items.length === 0) {
                void vscode.window.showInformationMessage("没找到相关内容。");
                return;
            }
            const pick = await vscode.window.showQuickPick(
                result.items.map((h) => ({
                    label: `${h.source_title}${h.section ? " · " + h.section : ""}`,
                    description: `${h.namespace} · score=${h.score.toFixed(2)}`,
                    detail: stripFirstLines(h.text, 2),
                    hit: h,
                })),
                { placeHolder: `${result.items.length} 条命中，回车看详情` },
            );
            if (pick) {
                await openKnowledgeHit(pick.hit);
            }
        }),

        vscode.commands.registerCommand("xuanji.saveSelectionAsMemory", async () => {
            await ensureAlive(backend, statusBar);
            const editor = vscode.window.activeTextEditor;
            if (!editor || editor.selection.isEmpty) {
                void vscode.window.showWarningMessage("先在编辑器里选中要保存的文本。");
                return;
            }
            const text = editor.document.getText(editor.selection);
            const summary = await vscode.window.showInputBox({
                prompt: "一句话摘要（可选）",
                placeHolder: "为什么记这条 / 什么场景用到",
            });
            const tags = await vscode.window.showInputBox({
                prompt: "标签，逗号分隔（可选）",
                placeHolder: "qbox, inventory, hint",
            });
            const result = await backend.rpc.call<{
                id: string;
                scope: string;
                kind: string;
                namespace: string;
            }>("memory.write", {
                text,
                summary: summary || undefined,
                tags: tags
                    ? tags.split(",").map((t) => t.trim()).filter(Boolean)
                    : [],
                kind: "semantic",
                scope: "project",
                importance: 0.65,
            });
            void vscode.window.showInformationMessage(
                `已记入 ${result.namespace}（${result.scope}/${result.kind}，id=${result.id.slice(0, 8)}）`,
            );
        }),

        vscode.commands.registerCommand("xuanji.openDashboard", async () => {
            await ensureAlive(backend, statusBar);
            await dashboard.show(backend);
        }),

        vscode.commands.registerCommand("xuanji.restartBackend", async () => {
            try {
                await backend.restart(resolveBackendOptions());
                await statusBar.refresh(backend);
                void vscode.window.showInformationMessage("玄玑后端已重启。");
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                statusBar.setError(msg);
                void vscode.window.showErrorMessage(`重启失败：${msg}`);
            }
        }),
    );
}

async function ensureAlive(backend: XuanjiBackend, statusBar: XuanjiStatusBar): Promise<void> {
    if (!backend.isAlive()) {
        try {
            await backend.ensureStarted(resolveBackendOptions());
            await statusBar.refresh(backend);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            void vscode.window.showErrorMessage(`玄玑后端未运行：${msg}`);
            throw e;
        }
    }
}

function pickPath(uri?: vscode.Uri): string | undefined {
    if (uri && uri.fsPath) {
        const wf = vscode.workspace.getWorkspaceFolder(uri);
        if (wf) {
            const rel = path.relative(wf.uri.fsPath, uri.fsPath);
            return rel || ".";
        }
        return uri.fsPath;
    }
    return undefined;
}

async function showDetectResult(detect: DetectResult): Promise<void> {
    const lines: string[] = [];
    if (!detect.is_fivem_resource) {
        lines.push("识别结果：不是 FiveM resource");
        if (detect.notes.length) {
            lines.push("说明：");
            detect.notes.forEach((n) => lines.push(`  · ${n}`));
        }
        if (detect.sub_resources.length) {
            lines.push("");
            lines.push(`发现 ${detect.sub_resources.length} 个子 resource：`);
            detect.sub_resources.slice(0, 20).forEach((p) => lines.push(`  · ${p}`));
        }
    } else {
        lines.push(`framework: ${detect.framework} (${Math.round(detect.framework_confidence * 100)}%)`);
        lines.push(`inventory: ${detect.inventory}`);
        lines.push(`target: ${detect.target}`);
        lines.push("");
        lines.push(detect.summary);
    }
    await openInfoDocument("玄玑 · 项目识别", lines.join("\n"));
}

async function showAnalyzeResult(result: AnalyzeResult): Promise<void> {
    const lines: string[] = [];
    lines.push(`resource: ${result.resource_path}`);
    lines.push(`framework: ${result.framework}`);
    lines.push(`files_scanned: ${result.files_scanned}`);
    lines.push("");
    lines.push("exports:");
    result.exports.slice(0, 30).forEach((e) => lines.push(`  · ${e}`));
    lines.push("");
    lines.push("events_registered:");
    result.events_registered.slice(0, 30).forEach((e) => lines.push(`  · ${e}`));
    lines.push("");
    lines.push("events_triggered:");
    result.events_triggered.slice(0, 30).forEach((e) => lines.push(`  · ${e}`));
    lines.push("");
    lines.push("callbacks:");
    result.callbacks.slice(0, 30).forEach((c) => lines.push(`  · ${c}`));
    lines.push("");
    lines.push("top API calls:");
    Object.entries(result.top_api_calls)
        .slice(0, 20)
        .forEach(([k, v]) => lines.push(`  ${k}  ×${v}`));
    await openInfoDocument("玄玑 · 资源分析", lines.join("\n"));
}

async function openKnowledgeHit(hit: KnowledgeHit): Promise<void> {
    const lines: string[] = [];
    lines.push(`# ${hit.source_title}`);
    if (hit.section) {
        lines.push(`## ${hit.section}`);
    }
    lines.push("");
    lines.push(`namespace: ${hit.namespace}`);
    lines.push(`score: ${hit.score.toFixed(3)} (${hit.source})`);
    if (hit.anchor_symbol) {
        lines.push(`anchor: ${hit.anchor_symbol}`);
    }
    lines.push("");
    lines.push("---");
    lines.push("");
    lines.push(hit.text);
    const doc = await vscode.workspace.openTextDocument({
        content: lines.join("\n"),
        language: "markdown",
    });
    await vscode.window.showTextDocument(doc, { preview: true });
}

async function openInfoDocument(title: string, body: string): Promise<void> {
    const doc = await vscode.workspace.openTextDocument({
        content: `# ${title}\n\n${body}\n`,
        language: "markdown",
    });
    await vscode.window.showTextDocument(doc, { preview: true });
}

function stripFirstLines(text: string, lines: number): string {
    return text.split("\n").slice(0, lines).join("\n");
}
