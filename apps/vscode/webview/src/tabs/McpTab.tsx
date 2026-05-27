import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

interface McpServer {
    name: string;
    transport: string;
    command?: string;
    args?: string[];
    cwd?: string;
    env?: Record<string, string>;
    url?: string;
    enabled: boolean;
    description: string;
}

export function McpTab(): JSX.Element {
    const [items, setItems] = useState<McpServer[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [editing, setEditing] = useState<{ existing?: McpServer } | null>(null);

    async function refresh(): Promise<void> {
        try {
            const out = await rpcCall<{ items: McpServer[] }>("mcp.list");
            setItems(out.items);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    useEffect(() => {
        void refresh();
    }, []);

    async function toggle(name: string, enabled: boolean): Promise<void> {
        try {
            await rpcCall("mcp.set_enabled", { name, enabled });
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }
    async function remove(name: string): Promise<void> {
        try {
            await rpcCall("mcp.remove", { name });
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    return (
        <div className="h-full overflow-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">MCP Servers</h2>
                <div className="flex gap-2">
                    <button
                        className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                        onClick={() => void refresh()}
                    >
                        刷新
                    </button>
                    <button
                        className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                        onClick={() => setEditing({})}
                    >
                        + 新增
                    </button>
                </div>
            </div>
            {error && <div className="text-[11px] text-vserror">{error}</div>}
            {items.length === 0 ? (
                <div className="text-[11px] text-vsmuted italic">还没接入 MCP server。</div>
            ) : (
                <div className="space-y-2">
                    {items.map((s) => (
                        <div
                            key={s.name}
                            className="bg-vswidget border border-vsborder rounded p-2"
                        >
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold">{s.name}</span>
                                <span className="text-[10px] text-vsmuted">{s.transport}</span>
                                <span
                                    className={
                                        "text-[10px] border rounded px-1 " +
                                        (s.enabled
                                            ? "border-vsok text-vsok"
                                            : "border-vsmuted text-vsmuted")
                                    }
                                >
                                    {s.enabled ? "启用" : "停用"}
                                </span>
                            </div>
                            <div className="text-[11px] text-vsmuted mt-1 truncate">
                                {s.transport === "stdio"
                                    ? `${s.command} ${(s.args || []).join(" ")}`
                                    : s.url}
                            </div>
                            {s.description && (
                                <div className="text-[11px] text-vsmuted">{s.description}</div>
                            )}
                            <div className="mt-2 flex gap-2">
                                <button
                                    onClick={() => void toggle(s.name, !s.enabled)}
                                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                                >
                                    {s.enabled ? "停用" : "启用"}
                                </button>
                                <button
                                    onClick={() => setEditing({ existing: s })}
                                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                                >
                                    编辑
                                </button>
                                <button
                                    onClick={() => void remove(s.name)}
                                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                                >
                                    删除
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {editing && (
                <McpEditor
                    initial={editing.existing}
                    onClose={() => setEditing(null)}
                    onSaved={async () => {
                        setEditing(null);
                        await refresh();
                    }}
                />
            )}
        </div>
    );
}

function McpEditor({
    initial,
    onClose,
    onSaved,
}: {
    initial?: McpServer;
    onClose: () => void;
    onSaved: () => void;
}): JSX.Element {
    const [name, setName] = useState(initial?.name || "");
    const [transport, setTransport] = useState(initial?.transport || "stdio");
    const [command, setCommand] = useState(initial?.command || "");
    const [argsLine, setArgsLine] = useState((initial?.args || []).join(" "));
    const [cwd, setCwd] = useState(initial?.cwd || "");
    const [envLines, setEnvLines] = useState(
        Object.entries(initial?.env || {})
            .map(([k, v]) => `${k}=${v}`)
            .join("\n"),
    );
    const [url, setUrl] = useState(initial?.url || "");
    const [enabled, setEnabled] = useState(initial?.enabled ?? true);
    const [description, setDescription] = useState(initial?.description || "");
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    async function save(): Promise<void> {
        if (!name) {
            setErr("name 必填");
            return;
        }
        setBusy(true);
        setErr(null);
        try {
            const env: Record<string, string> = {};
            for (const line of envLines.split("\n")) {
                const trimmed = line.trim();
                if (!trimmed) continue;
                const idx = trimmed.indexOf("=");
                if (idx > 0) {
                    env[trimmed.slice(0, idx)] = trimmed.slice(idx + 1);
                }
            }
            const args = argsLine
                .split(/\s+/)
                .map((x) => x.trim())
                .filter(Boolean);
            const params: Record<string, unknown> = {
                name,
                transport,
                enabled,
                description,
            };
            if (transport === "stdio") {
                params.command = command;
                params.args = args;
                params.cwd = cwd || undefined;
                params.env = env;
            } else {
                params.url = url;
            }
            await rpcCall("mcp.upsert", params);
            onSaved();
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
            <div className="bg-vsbg border border-vsborder rounded p-4 w-[480px] max-w-[90vw]">
                <h3 className="text-sm font-semibold mb-3">
                    {initial ? `编辑 ${initial.name}` : "新增 MCP server"}
                </h3>
                <div className="space-y-2 text-xs">
                    <Row label="name">
                        <input
                            value={name}
                            disabled={!!initial}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full"
                        />
                    </Row>
                    <Row label="transport">
                        <select
                            value={transport}
                            onChange={(e) => setTransport(e.target.value)}
                            className="w-full"
                        >
                            <option value="stdio">stdio</option>
                            <option value="http">http</option>
                            <option value="sse">sse</option>
                        </select>
                    </Row>
                    {transport === "stdio" ? (
                        <>
                            <Row label="command">
                                <input
                                    value={command}
                                    onChange={(e) => setCommand(e.target.value)}
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="args">
                                <input
                                    value={argsLine}
                                    onChange={(e) => setArgsLine(e.target.value)}
                                    placeholder="空格分隔"
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="cwd">
                                <input
                                    value={cwd}
                                    onChange={(e) => setCwd(e.target.value)}
                                    placeholder="可选"
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="env">
                                <textarea
                                    rows={3}
                                    value={envLines}
                                    onChange={(e) => setEnvLines(e.target.value)}
                                    placeholder="KEY=VALUE 每行一条"
                                    className="w-full font-mono"
                                />
                            </Row>
                        </>
                    ) : (
                        <Row label="url">
                            <input
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                className="w-full font-mono"
                            />
                        </Row>
                    )}
                    <Row label="description">
                        <input
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            className="w-full"
                        />
                    </Row>
                    <Row label="">
                        <label className="flex items-center gap-1.5">
                            <input
                                type="checkbox"
                                checked={enabled}
                                onChange={(e) => setEnabled(e.target.checked)}
                            />
                            <span>启用</span>
                        </label>
                    </Row>
                </div>
                {err && <div className="text-[11px] text-vserror mt-2">{err}</div>}
                <div className="flex justify-end gap-2 mt-3">
                    <button
                        disabled={busy}
                        onClick={onClose}
                        className="text-[11px] px-3 py-1 rounded bg-vssec text-vssecfg"
                    >
                        取消
                    </button>
                    <button
                        disabled={busy}
                        onClick={() => void save()}
                        className="text-[11px] px-3 py-1 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov disabled:opacity-50"
                    >
                        保存
                    </button>
                </div>
            </div>
        </div>
    );
}

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-start gap-2">
            <span className="w-24 text-vsmuted text-right pt-1">{label}</span>
            <div className="flex-1">{children}</div>
        </div>
    );
}
