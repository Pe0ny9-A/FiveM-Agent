// FiveM 内联智能：lua/fxmanifest 的 Hover + Completion + Signature Help。
//
// 数据来源是稷下学宫 SkillGraph（IPC: knowledge.symbols_by_prefix /
// knowledge.symbol），不本地缓存——后端可以随时 ingest 新文档，不重启插件。
// 三个 provider 共享一个轻量 LRU，避免对每次按键都打一发 RPC。

import * as vscode from "vscode";

import { XuanjiBackend } from "./backend";

interface SkillSymbol {
    id: string;
    namespace: string;
    name: string;
    kind: "function" | "event" | "export" | "native" | "module";
    side?: "client" | "server" | "shared" | "any";
    signature?: string | null;
    summary?: string | null;
    params?: Array<{ name: string; type?: string; desc?: string }>;
    returns?: { type?: string; desc?: string } | null;
    example?: string | null;
    url?: string | null;
}

const LUA_DOCSEL: vscode.DocumentSelector = [
    { language: "lua", scheme: "file" },
    { language: "lua", scheme: "untitled" },
];
const FXMANIFEST_DOCSEL: vscode.DocumentSelector = {
    pattern: "**/{fxmanifest,__resource}.lua",
    scheme: "file",
};

// FiveM SkillGraph 的命名空间集合。lookup 时只在这些里面查，避免被
// 用户私有命名空间或非 FiveM 内容污染。
const FIVEM_NAMESPACES = [
    "fivem.qbcore@1.x",
    "fivem.qbox@main",
    "fivem.esx@1.13",
    "fivem.ox_lib@3.x",
    "fivem.ox_inventory@2.x",
    "fivem.ox_target@1.x",
    "fivem.ox_doorlock@1.x",
    "fivem.npc_ai@1.x",
    "fivem.cfx@latest",
    "fivem.natives@latest",
];

// fxmanifest 里 dependencies / dependency 字段常见可补全的资源名。
// 不打 RPC，纯静态——这些是固定的官方/社区资源标识。
const FXMANIFEST_DEPS = [
    "qb-core",
    "qbx_core",
    "es_extended",
    "ox_lib",
    "ox_inventory",
    "ox_target",
    "ox_doorlock",
    "ox_mdt",
    "oxmysql",
    "MySQL-Async",
    "ghmattimysql",
    "PolyZone",
    "cron",
    "screenshot-basic",
    "pma-voice",
    "menuv",
    "qb-menu",
    "qb-input",
    "qb-target",
    "qb-radialmenu",
];

// fxmanifest 顶层声明字段（fx_version / game / lua54 / 等）
const FXMANIFEST_KEYS = [
    "fx_version",
    "game",
    "games",
    "name",
    "author",
    "description",
    "version",
    "lua54",
    "use_experimental_fxv2_oal",
    "client_script",
    "client_scripts",
    "server_script",
    "server_scripts",
    "shared_script",
    "shared_scripts",
    "ui_page",
    "files",
    "data_file",
    "dependencies",
    "dependency",
    "provide",
    "this_is_a_map",
    "server_only",
    "client_only",
    "convar_category",
    "before",
    "after",
    "loadscreen",
    "loadscreen_manual_shutdown",
];

class SymbolCache {
    private prefixCache = new Map<string, { ts: number; items: SkillSymbol[] }>();
    private nameCache = new Map<string, { ts: number; items: SkillSymbol[] }>();
    private readonly ttlMs = 60_000;
    private readonly maxEntries = 200;

    getPrefix(prefix: string): SkillSymbol[] | null {
        const hit = this.prefixCache.get(prefix);
        if (!hit) return null;
        if (Date.now() - hit.ts > this.ttlMs) {
            this.prefixCache.delete(prefix);
            return null;
        }
        return hit.items;
    }

    setPrefix(prefix: string, items: SkillSymbol[]): void {
        if (this.prefixCache.size >= this.maxEntries) {
            const oldest = this.prefixCache.keys().next().value;
            if (oldest !== undefined) this.prefixCache.delete(oldest);
        }
        this.prefixCache.set(prefix, { ts: Date.now(), items });
    }

    getName(name: string): SkillSymbol[] | null {
        const hit = this.nameCache.get(name);
        if (!hit) return null;
        if (Date.now() - hit.ts > this.ttlMs) {
            this.nameCache.delete(name);
            return null;
        }
        return hit.items;
    }

    setName(name: string, items: SkillSymbol[]): void {
        if (this.nameCache.size >= this.maxEntries) {
            const oldest = this.nameCache.keys().next().value;
            if (oldest !== undefined) this.nameCache.delete(oldest);
        }
        this.nameCache.set(name, { ts: Date.now(), items });
    }

    clear(): void {
        this.prefixCache.clear();
        this.nameCache.clear();
    }
}

class SkillGraphClient {
    private cache = new SymbolCache();

    constructor(private readonly backend: XuanjiBackend) {}

    async byPrefix(prefix: string, limit = 30): Promise<SkillSymbol[]> {
        if (prefix.length < 2) return [];
        const cached = this.cache.getPrefix(prefix);
        if (cached) return cached;
        if (!this.backend.isAlive()) return [];
        try {
            const r = await this.backend.rpc.call<{ items: SkillSymbol[] }>(
                "knowledge.symbols_by_prefix",
                {
                    prefix,
                    namespaces: FIVEM_NAMESPACES,
                    limit,
                },
            );
            const items = r.items || [];
            this.cache.setPrefix(prefix, items);
            return items;
        } catch {
            return [];
        }
    }

    async byName(name: string): Promise<SkillSymbol[]> {
        if (!name) return [];
        const cached = this.cache.getName(name);
        if (cached) return cached;
        if (!this.backend.isAlive()) return [];
        try {
            const r = await this.backend.rpc.call<{ items: SkillSymbol[] }>(
                "knowledge.symbol",
                {
                    name,
                    namespaces: FIVEM_NAMESPACES,
                },
            );
            const items = r.items || [];
            this.cache.setName(name, items);
            return items;
        } catch {
            return [];
        }
    }

    invalidate(): void {
        this.cache.clear();
    }
}

// ============================================================
// Lua: Hover / Completion / SignatureHelp
// ============================================================

const SYMBOL_TOKEN_RE = /[A-Za-z_][\w]*(?:[.:][A-Za-z_][\w]*)*/g;

function tokenAt(
    document: vscode.TextDocument,
    position: vscode.Position,
): { word: string; range: vscode.Range } | null {
    const line = document.lineAt(position.line).text;
    SYMBOL_TOKEN_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SYMBOL_TOKEN_RE.exec(line)) !== null) {
        const start = match.index;
        const end = start + match[0].length;
        if (position.character >= start && position.character <= end) {
            return {
                word: match[0],
                range: new vscode.Range(
                    new vscode.Position(position.line, start),
                    new vscode.Position(position.line, end),
                ),
            };
        }
    }
    return null;
}

function symbolToHoverMd(sym: SkillSymbol): vscode.MarkdownString {
    const md = new vscode.MarkdownString();
    md.isTrusted = false;
    md.supportHtml = false;
    const sideTag = sym.side && sym.side !== "any" ? ` · _${sym.side}_` : "";
    md.appendMarkdown(`**${sym.name}** · \`${sym.kind}\`${sideTag}\n\n`);
    md.appendMarkdown(`> 来自 \`${sym.namespace}\`\n\n`);
    if (sym.signature) {
        md.appendCodeblock(sym.signature, "lua");
    }
    if (sym.summary) {
        md.appendMarkdown(`\n${sym.summary}\n`);
    }
    if (sym.params && sym.params.length > 0) {
        md.appendMarkdown("\n**参数**\n");
        for (const p of sym.params) {
            const t = p.type ? ` \`${p.type}\`` : "";
            const d = p.desc ? ` — ${p.desc}` : "";
            md.appendMarkdown(`- \`${p.name}\`${t}${d}\n`);
        }
    }
    if (sym.returns) {
        const t = sym.returns.type ? ` \`${sym.returns.type}\`` : "";
        const d = sym.returns.desc ? ` — ${sym.returns.desc}` : "";
        md.appendMarkdown(`\n**返回**${t}${d}\n`);
    }
    if (sym.example) {
        md.appendMarkdown("\n**示例**\n");
        md.appendCodeblock(sym.example, "lua");
    }
    if (sym.url) {
        md.appendMarkdown(`\n[📖 查看官方文档](${sym.url})\n`);
    }
    return md;
}

function kindToCompletionKind(kind: string): vscode.CompletionItemKind {
    switch (kind) {
        case "function":
            return vscode.CompletionItemKind.Function;
        case "event":
            return vscode.CompletionItemKind.Event;
        case "export":
            return vscode.CompletionItemKind.Method;
        case "native":
            return vscode.CompletionItemKind.Function;
        case "module":
            return vscode.CompletionItemKind.Module;
        default:
            return vscode.CompletionItemKind.Variable;
    }
}

function symbolToCompletion(sym: SkillSymbol): vscode.CompletionItem {
    const item = new vscode.CompletionItem(sym.name, kindToCompletionKind(sym.kind));
    item.detail = sym.signature || `${sym.kind} · ${sym.namespace}`;
    item.documentation = symbolToHoverMd(sym);
    // 让 . 与 : 都能正确替换
    return item;
}

class LuaHoverProvider implements vscode.HoverProvider {
    constructor(private readonly client: SkillGraphClient) {}

    async provideHover(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken,
    ): Promise<vscode.Hover | null> {
        const tok = tokenAt(document, position);
        if (!tok) return null;
        if (tok.word.length < 3) return null;
        const items = await this.client.byName(tok.word);
        if (items.length === 0) return null;
        // 选最契合的：完全匹配 > 最短 name
        items.sort(
            (a, b) =>
                Number(b.name === tok.word) - Number(a.name === tok.word) ||
                a.name.length - b.name.length,
        );
        return new vscode.Hover(symbolToHoverMd(items[0]), tok.range);
    }
}

class LuaCompletionProvider implements vscode.CompletionItemProvider {
    constructor(private readonly client: SkillGraphClient) {}

    async provideCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken,
        _ctx: vscode.CompletionContext,
    ): Promise<vscode.CompletionItem[]> {
        // 取光标前的 token（含 . 与 :）
        const linePrefix = document.lineAt(position.line).text.slice(0, position.character);
        const m = /([A-Za-z_][\w]*(?:[.:][A-Za-z_][\w]*)*)$/.exec(linePrefix);
        if (!m) return [];
        const prefix = m[1];
        if (prefix.length < 2) return [];
        const items = await this.client.byPrefix(prefix, 50);
        return items.map(symbolToCompletion);
    }
}

class LuaSignatureHelpProvider implements vscode.SignatureHelpProvider {
    constructor(private readonly client: SkillGraphClient) {}

    async provideSignatureHelp(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken,
        _ctx: vscode.SignatureHelpContext,
    ): Promise<vscode.SignatureHelp | null> {
        const linePrefix = document
            .lineAt(position.line)
            .text.slice(0, position.character);
        // 找最近一个未闭合的 ( 之前的 callee
        const openIdx = linePrefix.lastIndexOf("(");
        if (openIdx < 0) return null;
        // 简化：只看最近的左括号是否被同行右括号关闭
        const after = linePrefix.slice(openIdx + 1);
        if (after.includes(")")) return null;
        const before = linePrefix.slice(0, openIdx);
        const m = /([A-Za-z_][\w]*(?:[.:][A-Za-z_][\w]*)*)$/.exec(before);
        if (!m) return null;
        const callee = m[1];
        const items = await this.client.byName(callee);
        const sym = items.find((s) => s.name === callee) || items[0];
        if (!sym) return null;

        const help = new vscode.SignatureHelp();
        const sigText =
            sym.signature ||
            `${sym.name}(${(sym.params || []).map((p) => p.name).join(", ")})`;
        const sigInfo = new vscode.SignatureInformation(sigText, symbolToHoverMd(sym));
        sigInfo.parameters = (sym.params || []).map(
            (p) =>
                new vscode.ParameterInformation(
                    p.name,
                    p.desc ? new vscode.MarkdownString(p.desc) : undefined,
                ),
        );
        help.signatures = [sigInfo];
        // 当前参数 idx = 已经输入的 , 数量
        help.activeParameter = (after.match(/,/g) || []).length;
        help.activeSignature = 0;
        return help;
    }
}

// ============================================================
// fxmanifest.lua: dependencies / events / 顶层字段补全
// ============================================================

class FxmanifestCompletionProvider implements vscode.CompletionItemProvider {
    constructor(private readonly client: SkillGraphClient) {}

    async provideCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken,
        _ctx: vscode.CompletionContext,
    ): Promise<vscode.CompletionItem[]> {
        const lineText = document.lineAt(position.line).text;
        const linePrefix = lineText.slice(0, position.character);
        const fullText = document.getText();

        // 看光标在不在 dependencies/dependency 块内
        if (this.insideDepsBlock(fullText, document.offsetAt(position), lineText)) {
            return FXMANIFEST_DEPS.map((d) => {
                const item = new vscode.CompletionItem(
                    d,
                    vscode.CompletionItemKind.Module,
                );
                item.detail = "FiveM 资源依赖";
                return item;
            });
        }

        // 看是否在写事件名（TriggerEvent / RegisterNetEvent / AddEventHandler）
        const eventMatch = /(?:TriggerEvent|TriggerServerEvent|TriggerClientEvent|RegisterNetEvent|AddEventHandler|RegisterServerEvent)\s*\(\s*['"]([^'"]*)$/.exec(
            linePrefix,
        );
        if (eventMatch) {
            const prefix = eventMatch[1];
            if (prefix.length < 2) return [];
            const items = await this.client.byPrefix(prefix, 30);
            return items
                .filter((s) => s.kind === "event")
                .map((s) => {
                    const ci = new vscode.CompletionItem(
                        s.name,
                        vscode.CompletionItemKind.Event,
                    );
                    ci.detail = s.signature || s.namespace;
                    ci.documentation = symbolToHoverMd(s);
                    return ci;
                });
        }

        // 顶层：行首/缩进开头，建议 manifest 关键字
        if (/^\s*[A-Za-z_]*$/.test(linePrefix)) {
            const m = /^\s*([A-Za-z_]*)$/.exec(linePrefix);
            const prefix = m ? m[1] : "";
            return FXMANIFEST_KEYS.filter((k) =>
                k.toLowerCase().startsWith(prefix.toLowerCase()),
            ).map((k) => {
                const item = new vscode.CompletionItem(
                    k,
                    vscode.CompletionItemKind.Keyword,
                );
                item.detail = "fxmanifest 字段";
                return item;
            });
        }

        return [];
    }

    private insideDepsBlock(
        fullText: string,
        offset: number,
        currentLine: string,
    ): boolean {
        // dependencies { ... } 或 dependency 'xxx' 单行格式
        if (/^\s*dependency\s+['"]/.test(currentLine)) return true;
        // 查光标之前最后一个 dependencies/dependency 与 } 的相对位置
        const before = fullText.slice(0, offset);
        const lastOpen = Math.max(
            before.lastIndexOf("dependencies{"),
            before.lastIndexOf("dependencies {"),
            before.lastIndexOf("dependencies\n{"),
        );
        if (lastOpen < 0) return false;
        const lastClose = before.lastIndexOf("}");
        return lastClose < lastOpen;
    }
}

// ============================================================
// 注册入口
// ============================================================

export function registerIntellisense(
    context: vscode.ExtensionContext,
    backend: XuanjiBackend,
): SkillGraphClient {
    const client = new SkillGraphClient(backend);
    context.subscriptions.push(
        vscode.languages.registerHoverProvider(
            LUA_DOCSEL,
            new LuaHoverProvider(client),
        ),
        vscode.languages.registerCompletionItemProvider(
            LUA_DOCSEL,
            new LuaCompletionProvider(client),
            ".",
            ":",
        ),
        vscode.languages.registerSignatureHelpProvider(
            LUA_DOCSEL,
            new LuaSignatureHelpProvider(client),
            "(",
            ",",
        ),
        vscode.languages.registerCompletionItemProvider(
            FXMANIFEST_DOCSEL,
            new FxmanifestCompletionProvider(client),
            "'",
            '"',
        ),
    );
    return client;
}
