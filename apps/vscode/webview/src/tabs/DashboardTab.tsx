import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

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

export function DashboardTab(): JSX.Element {
    const [drafts, setDrafts] = useState<PresetDraft[]>([]);
    const [skills, setSkills] = useState<SkillItem[]>([]);
    const [error, setError] = useState<string | null>(null);

    async function refresh(): Promise<void> {
        try {
            const [d, s] = await Promise.all([
                rpcCall<{ items: PresetDraft[] }>("presets.drafts"),
                rpcCall<{ items: SkillItem[] }>("skill.list", { limit: 30 }),
            ]);
            setDrafts(d.items);
            setSkills(s.items);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    useEffect(() => {
        void refresh();
    }, []);

    return (
        <div className="h-full overflow-auto p-3 space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">仪表盘</h2>
                <button
                    className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                    onClick={() => void refresh()}
                >
                    刷新
                </button>
            </div>
            {error && (
                <div className="text-[11px] text-vserror">{error}</div>
            )}
            <section>
                <h3 className="text-xs text-vslink mb-2 border-b border-vsborder pb-1">
                    预设草案（待 review · {drafts.length}）
                </h3>
                {drafts.length === 0 ? (
                    <div className="text-[11px] text-vsmuted italic">
                        暂无草案。让玄玑用 propose_preset 提交。
                    </div>
                ) : (
                    <div className="space-y-2">
                        {drafts.map((d) => (
                            <DraftCard
                                key={d.key}
                                draft={d}
                                onChange={() => void refresh()}
                            />
                        ))}
                    </div>
                )}
            </section>
            <section>
                <h3 className="text-xs text-vslink mb-2 border-b border-vsborder pb-1">
                    技能（{skills.length}）
                </h3>
                {skills.length === 0 ? (
                    <div className="text-[11px] text-vsmuted italic">技能库还是空的。</div>
                ) : (
                    <div className="space-y-2">
                        {skills.map((s) => (
                            <div
                                key={s.id}
                                className="bg-vswidget border border-vsborder rounded p-2"
                            >
                                <div className="text-xs font-medium">{s.summary}</div>
                                <div className="text-[11px] text-vsmuted mt-1">
                                    tags: {s.tags.join(", ") || "-"} · tools:{" "}
                                    {s.tools_used.join(", ") || "-"}
                                </div>
                                <div className="text-[11px] text-vsmuted">
                                    imp={s.importance.toFixed(2)} · hits={s.hits}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}

function DraftCard({
    draft,
    onChange,
}: {
    draft: PresetDraft;
    onChange: () => void;
}): JSX.Element {
    const [busy, setBusy] = useState(false);
    async function accept(): Promise<void> {
        setBusy(true);
        try {
            await rpcCall("presets.accept", { key: draft.key });
            onChange();
        } finally {
            setBusy(false);
        }
    }
    async function reject(): Promise<void> {
        setBusy(true);
        try {
            await rpcCall("presets.reject", { key: draft.key });
            onChange();
        } finally {
            setBusy(false);
        }
    }
    return (
        <div className="bg-vswidget border border-vsborder rounded p-2">
            <div className="text-xs font-medium">{draft.label}</div>
            <div className="text-[11px] text-vsmuted mt-1">
                {draft.framework} · {draft.inventory} · {draft.files_count} 文件 · key=
                {draft.key}
            </div>
            <div className="text-[11px] text-vsmuted">{draft.description}</div>
            <div className="mt-2 flex gap-2">
                <button
                    disabled={busy}
                    onClick={() => void accept()}
                    className="text-[11px] px-2 py-0.5 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov disabled:opacity-50"
                >
                    激活
                </button>
                <button
                    disabled={busy}
                    onClick={() => void reject()}
                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg disabled:opacity-50"
                >
                    拒绝
                </button>
            </div>
        </div>
    );
}
