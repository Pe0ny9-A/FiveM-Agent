import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

interface HookSpec {
    matcher: string;
    command: string;
    timeout?: number;
    description?: string;
}

interface HooksList {
    events: Record<string, HookSpec[]>;
}

const EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Notification",
] as const;

export function HooksTab(): JSX.Element {
    const [data, setData] = useState<HooksList | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [editingEvent, setEditingEvent] = useState<string | null>(null);
    const [editingHooks, setEditingHooks] = useState<HookSpec[]>([]);

    async function refresh(): Promise<void> {
        try {
            const out = await rpcCall<HooksList>("hooks.list");
            setData(out);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    useEffect(() => {
        void refresh();
    }, []);

    function startEdit(event: string): void {
        setEditingEvent(event);
        setEditingHooks(data?.events[event] ? [...data.events[event]] : []);
    }

    async function saveEdit(): Promise<void> {
        if (!editingEvent) return;
        try {
            await rpcCall("hooks.set_event", {
                event: editingEvent,
                hooks: editingHooks,
            });
            setEditingEvent(null);
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    async function clearEvent(event: string): Promise<void> {
        try {
            await rpcCall("hooks.remove_event", { event });
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    return (
        <div className="h-full overflow-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">Hooks</h2>
                <button
                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                    onClick={() => void refresh()}
                >
                    刷新
                </button>
            </div>
            {error && <div className="text-[11px] text-vserror">{error}</div>}
            <div className="text-[11px] text-vsmuted">
                兼容 Claude Code hook 协议。事件名：PreToolUse / PostToolUse /
                UserPromptSubmit / Notification。
            </div>
            <div className="space-y-3">
                {EVENTS.map((event) => {
                    const hooks = data?.events[event] || [];
                    return (
                        <div
                            key={event}
                            className="bg-vswidget border border-vsborder rounded p-2"
                        >
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-semibold">{event}</span>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => startEdit(event)}
                                        className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                                    >
                                        编辑（{hooks.length}）
                                    </button>
                                    {hooks.length > 0 && (
                                        <button
                                            onClick={() => void clearEvent(event)}
                                            className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                                        >
                                            清空
                                        </button>
                                    )}
                                </div>
                            </div>
                            {hooks.length === 0 ? (
                                <div className="mt-1 text-[11px] text-vsmuted italic">
                                    没注册 hook
                                </div>
                            ) : (
                                <ul className="mt-2 space-y-1">
                                    {hooks.map((h, i) => (
                                        <li
                                            key={i}
                                            className="text-[11px] bg-vsbg border border-vsborder rounded px-2 py-1"
                                        >
                                            <div>
                                                <span className="text-vsmuted">matcher:</span>{" "}
                                                <span className="font-mono">{h.matcher}</span>
                                            </div>
                                            <div>
                                                <span className="text-vsmuted">command:</span>{" "}
                                                <span className="font-mono">{h.command}</span>
                                            </div>
                                            {h.timeout != null && (
                                                <div className="text-vsmuted">
                                                    timeout: {h.timeout}s
                                                </div>
                                            )}
                                            {h.description && (
                                                <div className="text-vsmuted">
                                                    {h.description}
                                                </div>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    );
                })}
            </div>
            {editingEvent && (
                <HookEditor
                    event={editingEvent}
                    hooks={editingHooks}
                    setHooks={setEditingHooks}
                    onClose={() => setEditingEvent(null)}
                    onSave={() => void saveEdit()}
                />
            )}
        </div>
    );
}

function HookEditor({
    event,
    hooks,
    setHooks,
    onClose,
    onSave,
}: {
    event: string;
    hooks: HookSpec[];
    setHooks: (hooks: HookSpec[]) => void;
    onClose: () => void;
    onSave: () => void;
}): JSX.Element {
    function update(idx: number, patch: Partial<HookSpec>): void {
        setHooks(hooks.map((h, i) => (i === idx ? { ...h, ...patch } : h)));
    }
    function add(): void {
        setHooks([...hooks, { matcher: "*", command: "" }]);
    }
    function remove(idx: number): void {
        setHooks(hooks.filter((_, i) => i !== idx));
    }
    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
            <div className="bg-vsbg border border-vsborder rounded p-4 w-[560px] max-w-[90vw] max-h-[80vh] flex flex-col">
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold">编辑 {event} hooks</h3>
                    <button
                        onClick={add}
                        className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                    >
                        + 添加 hook
                    </button>
                </div>
                <div className="flex-1 overflow-auto space-y-2">
                    {hooks.length === 0 && (
                        <div className="text-[11px] text-vsmuted italic">
                            还没有 hook，点上面的「+ 添加 hook」开始。
                        </div>
                    )}
                    {hooks.map((h, idx) => (
                        <div
                            key={idx}
                            className="border border-vsborder rounded p-2 bg-vswidget space-y-1.5"
                        >
                            <div className="flex justify-between">
                                <span className="text-[11px] text-vsmuted">#{idx + 1}</span>
                                <button
                                    onClick={() => remove(idx)}
                                    className="text-[11px] text-vserror hover:underline"
                                >
                                    删除
                                </button>
                            </div>
                            <Row label="matcher">
                                <input
                                    value={h.matcher}
                                    onChange={(e) => update(idx, { matcher: e.target.value })}
                                    placeholder='例：write_file 或 *（全部）'
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="command">
                                <input
                                    value={h.command}
                                    onChange={(e) => update(idx, { command: e.target.value })}
                                    placeholder="python -m my_audit"
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="timeout">
                                <input
                                    type="number"
                                    value={h.timeout ?? ""}
                                    onChange={(e) =>
                                        update(idx, {
                                            timeout: e.target.value
                                                ? parseInt(e.target.value, 10)
                                                : undefined,
                                        })
                                    }
                                    placeholder="秒数（可空）"
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="说明">
                                <input
                                    value={h.description || ""}
                                    onChange={(e) =>
                                        update(idx, { description: e.target.value })
                                    }
                                    className="w-full"
                                />
                            </Row>
                        </div>
                    ))}
                </div>
                <div className="flex justify-end gap-2 mt-3">
                    <button
                        onClick={onClose}
                        className="text-[11px] px-3 py-1 rounded bg-vssec text-vssecfg"
                    >
                        取消
                    </button>
                    <button
                        onClick={onSave}
                        className="text-[11px] px-3 py-1 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
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
        <div className="flex items-start gap-2 text-xs">
            <span className="w-20 text-vsmuted text-right pt-1">{label}</span>
            <div className="flex-1">{children}</div>
        </div>
    );
}
