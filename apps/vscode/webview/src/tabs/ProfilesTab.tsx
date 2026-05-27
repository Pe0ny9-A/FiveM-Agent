import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

interface ProfileSummary {
    name: string;
    label: string;
    kind: string;
    default_model: string;
    base_url: string;
}

interface ProfilesList {
    active: string | null;
    items: ProfileSummary[];
}

const KIND_LABELS: Record<string, string> = {
    anthropic: "Anthropic（Claude）",
    openai: "OpenAI（GPT）",
    deepseek: "DeepSeek",
    "openai-compatible": "OpenAI 兼容（自定义 Base URL）",
};

export function ProfilesTab(): JSX.Element {
    const [list, setList] = useState<ProfilesList | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [editing, setEditing] = useState<{ name?: string } | null>(null);

    async function refresh(): Promise<void> {
        try {
            const out = await rpcCall<ProfilesList>("profiles.list");
            setList(out);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    useEffect(() => {
        void refresh();
    }, []);

    async function activate(name: string): Promise<void> {
        try {
            await rpcCall("profiles.use", { name });
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    async function remove(name: string): Promise<void> {
        try {
            await rpcCall("profiles.remove", { name });
            await refresh();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    return (
        <div className="h-full overflow-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">Profiles</h2>
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
            <div className="space-y-2">
                {list?.items.map((p) => (
                    <div
                        key={p.name}
                        className="bg-vswidget border border-vsborder rounded p-2"
                    >
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold">{p.name}</span>
                            {list.active === p.name && (
                                <span className="text-[10px] text-vsok border border-vsok rounded px-1">
                                    active
                                </span>
                            )}
                            <span className="text-[10px] text-vsmuted">
                                {KIND_LABELS[p.kind] || p.kind}
                            </span>
                        </div>
                        <div className="text-[11px] text-vsmuted mt-1">
                            label: {p.label} · model: {p.default_model}
                        </div>
                        {p.base_url && (
                            <div className="text-[11px] text-vsmuted truncate">
                                base_url: {p.base_url}
                            </div>
                        )}
                        <div className="mt-2 flex gap-2">
                            {list.active !== p.name && (
                                <button
                                    onClick={() => void activate(p.name)}
                                    className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                                >
                                    激活
                                </button>
                            )}
                            <button
                                onClick={() => setEditing({ name: p.name })}
                                className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                            >
                                编辑
                            </button>
                            <button
                                onClick={() => void remove(p.name)}
                                className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                            >
                                删除
                            </button>
                        </div>
                    </div>
                ))}
                {list && list.items.length === 0 && (
                    <div className="text-[11px] text-vsmuted italic">
                        还没配置 profile。点「新增」添加第一个。
                    </div>
                )}
            </div>
            {editing && (
                <ProfileEditor
                    initial={
                        editing.name ? list?.items.find((x) => x.name === editing.name) : undefined
                    }
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

function ProfileEditor({
    initial,
    onClose,
    onSaved,
}: {
    initial: ProfileSummary | undefined;
    onClose: () => void;
    onSaved: () => void;
}): JSX.Element {
    const [name, setName] = useState(initial?.name || "");
    const [label, setLabel] = useState(initial?.label || "");
    const [kind, setKind] = useState(initial?.kind || "anthropic");
    const [apiKey, setApiKey] = useState("");
    const [defaultModel, setDefaultModel] = useState(initial?.default_model || "");
    const [baseUrl, setBaseUrl] = useState(initial?.base_url || "");
    const [activate, setActivate] = useState(false);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    async function save(): Promise<void> {
        if (!name || !apiKey) {
            setErr("name 和 api_key 必填");
            return;
        }
        setBusy(true);
        setErr(null);
        try {
            const params: Record<string, unknown> = {
                name,
                kind,
                api_key: apiKey,
                label: label || undefined,
                default_model: defaultModel || undefined,
                activate,
            };
            if (kind === "openai-compatible") {
                params.base_url = baseUrl;
            }
            await rpcCall("profiles.upsert", params);
            onSaved();
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
            <div className="bg-vsbg border border-vsborder rounded p-4 w-[420px] max-w-[90vw]">
                <h3 className="text-sm font-semibold mb-3">
                    {initial ? `编辑 ${initial.name}` : "新增 profile"}
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
                    <Row label="kind">
                        <select
                            value={kind}
                            onChange={(e) => setKind(e.target.value)}
                            className="w-full"
                        >
                            <option value="anthropic">Anthropic</option>
                            <option value="openai">OpenAI</option>
                            <option value="deepseek">DeepSeek</option>
                            <option value="openai-compatible">OpenAI 兼容</option>
                        </select>
                    </Row>
                    <Row label="api_key">
                        <input
                            type="password"
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            placeholder={initial ? "留空保持不变" : "sk-..."}
                            className="w-full font-mono"
                        />
                    </Row>
                    <Row label="default_model">
                        <input
                            value={defaultModel}
                            onChange={(e) => setDefaultModel(e.target.value)}
                            placeholder="可空，按 kind 取默认"
                            className="w-full font-mono"
                        />
                    </Row>
                    {kind === "openai-compatible" && (
                        <Row label="base_url">
                            <input
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                placeholder="https://..."
                                className="w-full font-mono"
                            />
                        </Row>
                    )}
                    <Row label="label">
                        <input
                            value={label}
                            onChange={(e) => setLabel(e.target.value)}
                            className="w-full"
                        />
                    </Row>
                    {!initial && (
                        <Row label="">
                            <label className="flex items-center gap-1.5">
                                <input
                                    type="checkbox"
                                    checked={activate}
                                    onChange={(e) => setActivate(e.target.checked)}
                                />
                                <span>保存后立即激活</span>
                            </label>
                        </Row>
                    )}
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
