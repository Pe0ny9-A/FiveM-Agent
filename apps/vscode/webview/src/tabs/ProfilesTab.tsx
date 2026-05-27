import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

interface ProfileSummary {
    name: string;
    label: string;
    kind: string;
    default_model: string;
    base_url: string;
    wire_format: string;
}

interface ProfilesList {
    active: string | null;
    items: ProfileSummary[];
}

interface ModelItem {
    id: string;
    owned_by: string | null;
    created: number | null;
}

interface TestResult {
    ok: boolean;
    latency_ms: number;
    status: number | null;
    error: string | null;
}

const KIND_LABELS: Record<string, string> = {
    anthropic: "Anthropic（Claude）",
    openai: "OpenAI（GPT）",
    deepseek: "DeepSeek",
    "openai-compatible": "OpenAI 兼容（自定义 Base URL）",
};

const WIRE_LABELS: Record<string, string> = {
    openai: "OpenAI 协议（/v1/chat/completions）",
    anthropic: "Anthropic 协议（/v1/messages）",
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
                        {p.kind === "openai-compatible" && (
                            <div className="text-[11px] text-vsmuted">
                                wire: {WIRE_LABELS[p.wire_format] || p.wire_format}
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
    const [wireFormat, setWireFormat] = useState(initial?.wire_format || "openai");
    const [activate, setActivate] = useState(false);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    const [models, setModels] = useState<ModelItem[] | null>(null);
    const [fetchingModels, setFetchingModels] = useState(false);
    const [modelsErr, setModelsErr] = useState<string | null>(null);

    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<TestResult | null>(null);

    function probeParams(): Record<string, unknown> {
        const p: Record<string, unknown> = {
            kind,
            label: label || name,
            default_model: defaultModel || undefined,
        };
        // 若编辑已有 profile 且没改 api_key，传 name 让后端用已存的 key
        if (apiKey) {
            p.api_key = apiKey;
        } else if (initial?.name) {
            p.name = initial.name;
        }
        if (kind === "openai-compatible") {
            p.base_url = baseUrl;
            p.wire_format = wireFormat;
        }
        return p;
    }

    async function fetchModels(): Promise<void> {
        if (kind === "openai-compatible" && !baseUrl) {
            setModelsErr("先填 base_url");
            return;
        }
        setFetchingModels(true);
        setModelsErr(null);
        try {
            const out = await rpcCall<{ items: ModelItem[] }>(
                "profiles.list_models",
                probeParams(),
            );
            setModels(out.items);
            if (out.items.length === 0) {
                setModelsErr("端点返回空模型列表");
            } else if (!defaultModel) {
                setDefaultModel(out.items[0].id);
            }
        } catch (e) {
            setModelsErr(e instanceof Error ? e.message : String(e));
        } finally {
            setFetchingModels(false);
        }
    }

    async function testConnection(): Promise<void> {
        setTesting(true);
        setTestResult(null);
        try {
            const params = probeParams();
            if (defaultModel) params.model = defaultModel;
            const out = await rpcCall<TestResult>("profiles.test", params);
            setTestResult(out);
        } catch (e) {
            setTestResult({
                ok: false,
                latency_ms: 0,
                status: null,
                error: e instanceof Error ? e.message : String(e),
            });
        } finally {
            setTesting(false);
        }
    }

    async function save(): Promise<void> {
        if (!name) {
            setErr("name 必填");
            return;
        }
        if (!initial && !apiKey) {
            setErr("新建时 api_key 必填");
            return;
        }
        setBusy(true);
        setErr(null);
        try {
            const params: Record<string, unknown> = {
                name,
                kind,
                label: label || undefined,
                default_model: defaultModel || undefined,
                activate,
            };
            // 编辑时空 api_key 表示保持不变。后端 schema 要求 api_key 非空，
            // 所以如果是编辑且没改 key，需要先把已存的 key 拉回来填上。
            if (apiKey) {
                params.api_key = apiKey;
            } else if (initial?.name) {
                // 后端要求 api_key 字段；read 不到原值时只好让用户重填
                setErr("请输入 api_key（编辑时也必填，留空请回填原值）");
                setBusy(false);
                return;
            }
            if (kind === "openai-compatible") {
                params.base_url = baseUrl;
                params.wire_format = wireFormat;
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
            <div className="bg-vsbg border border-vsborder rounded p-4 w-[480px] max-w-[92vw] max-h-[90vh] overflow-auto">
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
                    {kind === "openai-compatible" && (
                        <>
                            <Row label="base_url">
                                <input
                                    value={baseUrl}
                                    onChange={(e) => setBaseUrl(e.target.value)}
                                    placeholder="https://newapi.example.com 或 https://api.x.com/v1"
                                    className="w-full font-mono"
                                />
                            </Row>
                            <Row label="wire_format">
                                <select
                                    value={wireFormat}
                                    onChange={(e) => setWireFormat(e.target.value)}
                                    className="w-full"
                                >
                                    <option value="openai">
                                        OpenAI（/v1/chat/completions）
                                    </option>
                                    <option value="anthropic">
                                        Anthropic（/v1/messages，NewAPI 转 Claude）
                                    </option>
                                </select>
                            </Row>
                        </>
                    )}
                    <Row label="api_key">
                        <input
                            type="password"
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            placeholder={initial ? "重新输入以覆盖" : "sk-..."}
                            className="w-full font-mono"
                        />
                    </Row>
                    <Row label="default_model">
                        <div className="flex gap-1">
                            {models && models.length > 0 ? (
                                <select
                                    value={defaultModel}
                                    onChange={(e) => setDefaultModel(e.target.value)}
                                    className="flex-1 font-mono"
                                >
                                    <option value="">（手填）</option>
                                    {models.map((m) => (
                                        <option key={m.id} value={m.id}>
                                            {m.id}
                                            {m.owned_by ? ` · ${m.owned_by}` : ""}
                                        </option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    value={defaultModel}
                                    onChange={(e) => setDefaultModel(e.target.value)}
                                    placeholder="可空，按 kind 取默认"
                                    className="flex-1 font-mono"
                                />
                            )}
                            <button
                                onClick={() => void fetchModels()}
                                disabled={fetchingModels}
                                className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg disabled:opacity-50"
                                title="拉取该端点支持的模型列表"
                            >
                                {fetchingModels ? "…" : "拉取"}
                            </button>
                        </div>
                    </Row>
                    {modelsErr && (
                        <div className="text-[11px] text-vswarn ml-26">
                            模型拉取失败：{modelsErr}
                        </div>
                    )}
                    {models && models.length > 0 && (
                        <div className="text-[10px] text-vsmuted ml-26">
                            ✓ 拉到 {models.length} 个模型
                        </div>
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
                <div className="mt-3 border-t border-vsborder pt-2 space-y-1">
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => void testConnection()}
                            disabled={testing}
                            className="text-[11px] px-2 py-0.5 rounded border border-vsborder hover:border-vslink disabled:opacity-50"
                        >
                            {testing ? "测试中…" : "🔌 测试连接"}
                        </button>
                        {testResult && (
                            <span
                                className={
                                    "text-[11px] " +
                                    (testResult.ok ? "text-vsok" : "text-vserror")
                                }
                            >
                                {testResult.ok
                                    ? `✓ 连通（${testResult.latency_ms}ms${
                                          testResult.status
                                              ? ` · HTTP ${testResult.status}`
                                              : ""
                                      }）`
                                    : `✗ ${testResult.error || "失败"}`}
                            </span>
                        )}
                    </div>
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
