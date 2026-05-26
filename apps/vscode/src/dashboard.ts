// 仪表盘 webview：单 panel，三栏布局——项目身份 / 预设草案 / 技能。
//
// 数据流：
//   webview ─postMessage(refresh)→ extension
//   extension ─rpc.call→ backend
//   extension ─postMessage(data)→ webview

import * as vscode from "vscode";

import { XuanjiBackend } from "./backend";

interface PresetDraft {
    key: string;
    label: string;
    description: string;
    framework: string;
    inventory: string;
    target: string;
    files_count: number;
}

interface SkillItem {
    id: string;
    summary: string;
    tags: string[];
    tools_used: string[];
    importance: number;
    hits: number;
}

interface InfoResult {
    version: string;
    active_profile: string | null;
    assistant_alias: string;
    user_alias: string;
    project: {
        root: string;
        namespace: string;
        is_fivem_resource: boolean;
        framework: string;
        framework_confidence: number;
        inventory: string;
        target: string;
        summary: string;
    };
}

export class XuanjiDashboard {
    private panel: vscode.WebviewPanel | null = null;

    constructor(_context: vscode.ExtensionContext) {}

    async show(backend: XuanjiBackend): Promise<void> {
        if (this.panel) {
            this.panel.reveal(vscode.ViewColumn.Beside);
            await this.refresh(backend);
            return;
        }
        this.panel = vscode.window.createWebviewPanel(
            "xuanji.dashboard",
            "玄玑 · 仪表盘",
            vscode.ViewColumn.Beside,
            { enableScripts: true, retainContextWhenHidden: true },
        );
        this.panel.onDidDispose(() => {
            this.panel = null;
        });
        this.panel.webview.html = this.renderHtml();
        this.panel.webview.onDidReceiveMessage(async (msg: { type: string; payload?: unknown }) => {
            if (msg.type === "refresh") {
                await this.refresh(backend);
            } else if (msg.type === "accept-preset" && this.panel) {
                const key = (msg.payload as { key: string }).key;
                try {
                    await backend.rpc.call("presets.accept", { key });
                    void vscode.window.showInformationMessage(`已激活预设 ${key}`);
                    await this.refresh(backend);
                } catch (e) {
                    const m = e instanceof Error ? e.message : String(e);
                    void vscode.window.showErrorMessage(`激活失败：${m}`);
                }
            } else if (msg.type === "reject-preset" && this.panel) {
                const key = (msg.payload as { key: string }).key;
                const ok = await vscode.window.showWarningMessage(
                    `确定拒绝草案 ${key}？`,
                    "拒绝",
                    "取消",
                );
                if (ok === "拒绝") {
                    await backend.rpc.call("presets.reject", { key });
                    await this.refresh(backend);
                }
            } else if (msg.type === "show-preset" && this.panel) {
                const key = (msg.payload as { key: string }).key;
                const detail = await backend.rpc.call<{
                    label: string;
                    description: string;
                    files: { path: string; content: string }[];
                }>("presets.show", { key });
                const lines = [
                    `# ${detail.label}`,
                    "",
                    detail.description,
                    "",
                    `## 包含 ${detail.files.length} 个文件`,
                    "",
                ];
                detail.files.forEach((f) => {
                    lines.push(`### ${f.path}`);
                    lines.push("```");
                    lines.push(f.content);
                    lines.push("```");
                    lines.push("");
                });
                const doc = await vscode.workspace.openTextDocument({
                    content: lines.join("\n"),
                    language: "markdown",
                });
                await vscode.window.showTextDocument(doc, { preview: true });
            } else if (msg.type === "show-skill" && this.panel) {
                const id = (msg.payload as { id: string }).id;
                const detail = await backend.rpc.call<{
                    summary: string;
                    text: string;
                    tags: string[];
                    tools_used: string[];
                }>("skill.show", { id });
                const lines = [
                    `# ${detail.summary || id}`,
                    "",
                    `tags: ${detail.tags.join(", ") || "-"}`,
                    `tools: ${detail.tools_used.join(", ") || "-"}`,
                    "",
                    "---",
                    "",
                    detail.text,
                ];
                const doc = await vscode.workspace.openTextDocument({
                    content: lines.join("\n"),
                    language: "markdown",
                });
                await vscode.window.showTextDocument(doc, { preview: true });
            }
        });

        await this.refresh(backend);
    }

    private async refresh(backend: XuanjiBackend): Promise<void> {
        if (!this.panel) {
            return;
        }
        try {
            const [info, drafts, skills] = await Promise.all([
                backend.rpc.call<InfoResult>("info"),
                backend.rpc.call<{ items: PresetDraft[] }>("presets.drafts"),
                backend.rpc.call<{ items: SkillItem[] }>("skill.list", { limit: 30 }),
            ]);
            this.panel.webview.postMessage({
                type: "data",
                payload: { info, drafts: drafts.items, skills: skills.items },
            });
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.panel.webview.postMessage({ type: "error", payload: msg });
        }
    }

    private renderHtml(): string {
        return /* html */ `
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px; }
  .columns { display: grid; grid-template-columns: 1fr 1.2fr 1fr; gap: 16px; }
  .col { background: var(--vscode-editor-background); border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 12px; }
  h2 { margin-top: 0; font-size: 14px; color: var(--vscode-textLink-foreground); border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 6px; }
  .card { background: var(--vscode-editorWidget-background); border: 1px solid var(--vscode-panel-border); border-radius: 4px; padding: 8px; margin-bottom: 8px; }
  .card .title { font-weight: bold; }
  .card .meta { color: var(--vscode-descriptionForeground); font-size: 11px; margin-top: 2px; }
  .card .actions { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: 0; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  .empty { color: var(--vscode-descriptionForeground); font-style: italic; }
  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .header h1 { font-size: 18px; margin: 0; }
  pre.summary { white-space: pre-wrap; font-size: 12px; background: var(--vscode-editorWidget-background); padding: 8px; border-radius: 3px; }
  .kvs { font-size: 12px; }
  .kvs .row { display: flex; padding: 2px 0; }
  .kvs .k { color: var(--vscode-descriptionForeground); width: 96px; }
</style>
</head>
<body>
<div class="header">
  <h1>玄玑 · 仪表盘</h1>
  <button onclick="refresh()">刷新</button>
</div>
<div id="error" style="color: var(--vscode-errorForeground); display: none; margin-bottom: 12px;"></div>
<div class="columns">
  <div class="col"><h2>项目身份</h2><div id="info">加载中…</div></div>
  <div class="col"><h2>预设草案（待 review）</h2><div id="drafts">加载中…</div></div>
  <div class="col"><h2>技能</h2><div id="skills">加载中…</div></div>
</div>
<script>
const vscode = acquireVsCodeApi();
function refresh() { vscode.postMessage({ type: 'refresh' }); }

window.addEventListener('message', (e) => {
  const msg = e.data;
  if (msg.type === 'error') {
    document.getElementById('error').style.display = 'block';
    document.getElementById('error').textContent = msg.payload;
    return;
  }
  document.getElementById('error').style.display = 'none';
  const { info, drafts, skills } = msg.payload;
  renderInfo(info);
  renderDrafts(drafts);
  renderSkills(skills);
});

function escape(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderInfo(info) {
  const p = info.project;
  const html = [
    '<div class="kvs">',
    rowKV('版本', info.version),
    rowKV('profile', info.active_profile || '未配置'),
    rowKV('称呼', info.assistant_alias + ' / ' + info.user_alias),
    rowKV('namespace', p.namespace),
    rowKV('framework', p.framework + ' (' + Math.round(p.framework_confidence * 100) + '%)'),
    rowKV('inventory', p.inventory),
    rowKV('target', p.target),
    rowKV('is_resource', p.is_fivem_resource ? '是' : '否'),
    '</div>',
    '<pre class="summary">' + escape(p.summary) + '</pre>',
  ].join('');
  document.getElementById('info').innerHTML = html;
}

function rowKV(k, v) {
  return '<div class="row"><div class="k">' + escape(k) + '</div><div>' + escape(v) + '</div></div>';
}

function renderDrafts(drafts) {
  if (!drafts || drafts.length === 0) {
    document.getElementById('drafts').innerHTML = '<div class="empty">没有待 review 的草案。让玄玑用 propose_preset 提交。</div>';
    return;
  }
  document.getElementById('drafts').innerHTML = drafts.map((d) => {
    return '<div class="card">'
      + '<div class="title">' + escape(d.label) + '</div>'
      + '<div class="meta">' + escape(d.framework) + ' · ' + escape(d.inventory) + ' · ' + d.files_count + ' 文件 · key=' + escape(d.key) + '</div>'
      + '<div class="meta">' + escape(d.description || '') + '</div>'
      + '<div class="actions">'
        + '<button onclick="showPreset(\\'' + escape(d.key) + '\\')">查看</button>'
        + '<button onclick="acceptPreset(\\'' + escape(d.key) + '\\')">激活</button>'
        + '<button class="secondary" onclick="rejectPreset(\\'' + escape(d.key) + '\\')">拒绝</button>'
      + '</div>'
    + '</div>';
  }).join('');
}

function renderSkills(skills) {
  if (!skills || skills.length === 0) {
    document.getElementById('skills').innerHTML = '<div class="empty">技能库还是空的。</div>';
    return;
  }
  document.getElementById('skills').innerHTML = skills.map((s) => {
    const tags = (s.tags || []).map((t) => escape(t)).join(', ');
    const tools = (s.tools_used || []).map((t) => escape(t)).join(', ');
    return '<div class="card">'
      + '<div class="title">' + escape(s.summary) + '</div>'
      + '<div class="meta">tags: ' + tags + ' · tools: ' + tools + '</div>'
      + '<div class="meta">imp=' + s.importance.toFixed(2) + ' · hits=' + s.hits + '</div>'
      + '<div class="actions"><button onclick="showSkill(\\'' + escape(s.id) + '\\')">查看</button></div>'
    + '</div>';
  }).join('');
}

function acceptPreset(key) { vscode.postMessage({ type: 'accept-preset', payload: { key } }); }
function rejectPreset(key) { vscode.postMessage({ type: 'reject-preset', payload: { key } }); }
function showPreset(key) { vscode.postMessage({ type: 'show-preset', payload: { key } }); }
function showSkill(id) { vscode.postMessage({ type: 'show-skill', payload: { id } }); }
</script>
</body>
</html>`;
    }
}
