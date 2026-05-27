// 群英会议会式协作面板。
// 用户配题 + 选议员（角色 + profile）+ 发起会议；
// 进度通过订阅 ensemble.* notification 实时显示。

import { useEffect, useMemo, useRef, useState } from "react";
import { onNotification, rpcCall } from "../bridge";

interface ProfileItem {
    name: string;
    label: string;
    kind: string;
    default_model: string;
}

interface CouncilorDraft {
    role: string;
    profile_override?: string;
    model_override?: string;
    brief_extra?: string;
}

const DEFAULT_ROLES = ["稷下生", "百工匠", "司鉴"];

interface CouncilorOutcome {
    role: string;
    profile_name: string;
    model: string;
    final_text: string;
    iterations: number;
    tool_calls_made: number;
    truncated: boolean;
    error: string | null;
}

interface Verdict {
    summary: string;
    chosen_path: string | null;
    consensus_points: string[];
    divergence_points: string[];
    risks: string[];
    decided_by: string;
    councilors: string[];
    decided_at: number;
}

interface RunState {
    request_id: string;
    question: string;
    started_at: number;
    phase: "running" | "judging" | "done" | "error";
    error?: string;
    councilor_status: Record<number, {
        role: string;
        profile: string;
        model: string;
        state: "running" | "ok" | "fail";
        iterations?: number;
        tool_calls?: number;
        error?: string;
    }>;
    elapsed_seconds?: number;
    verdict?: Verdict;
    councilors?: CouncilorOutcome[];
    memory_id?: string | null;
}

export function CouncilTab(): JSX.Element {
    const [profiles, setProfiles] = useState<ProfileItem[]>([]);
    const [profilesError, setProfilesError] = useState<string | null>(null);
    const [question, setQuestion] = useState("");
    const [councilors, setCouncilors] = useState<CouncilorDraft[]>(
        DEFAULT_ROLES.map((r) => ({ role: r })),
    );
    const [deadline, setDeadline] = useState(120);
    const [runState, setRunState] = useState<RunState | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const runStateRef = useRef<RunState | null>(null);
    runStateRef.current = runState;

    useEffect(() => {
        rpcCall<{ active: string | null; items: ProfileItem[] }>("profiles.list")
            .then((r) => {
                setProfiles(r.items);
                setProfilesError(null);
            })
            .catch((e) => {
                setProfilesError(e instanceof Error ? e.message : String(e));
            });
    }, []);

    // 订阅 ensemble.* notification
    useEffect(() => {
        const dispose = onNotification((method, params) => {
            if (!method.startsWith("ensemble.")) return;
            const cur = runStateRef.current;
            if (!cur) return;
            const reqId = params.request_id as string | undefined;
            if (reqId && reqId !== cur.request_id) return;

            setRunState((prev) => {
                if (!prev) return prev;
                const event = method.slice("ensemble.".length);
                switch (event) {
                    case "council_started":
                        return prev;
                    case "councilor_started": {
                        const idx = Number(params.index ?? -1);
                        if (idx < 0) return prev;
                        return {
                            ...prev,
                            councilor_status: {
                                ...prev.councilor_status,
                                [idx]: {
                                    role: String(params.role || ""),
                                    profile: String(params.profile || ""),
                                    model: String(params.model || ""),
                                    state: "running",
                                },
                            },
                        };
                    }
                    case "councilor_done": {
                        const idx = Number(params.index ?? -1);
                        if (idx < 0) return prev;
                        const ok = Boolean(params.ok);
                        const old = prev.councilor_status[idx];
                        if (!old) return prev;
                        return {
                            ...prev,
                            councilor_status: {
                                ...prev.councilor_status,
                                [idx]: {
                                    ...old,
                                    state: ok ? "ok" : "fail",
                                    iterations: params.iterations as number | undefined,
                                    tool_calls: params.tool_calls as number | undefined,
                                    error: params.error as string | undefined,
                                },
                            },
                        };
                    }
                    case "council_judging":
                        return { ...prev, phase: "judging" };
                    case "council_done":
                        // verdict 落到 RPC 返回值上，这里只切阶段
                        return prev;
                    default:
                        return prev;
                }
            });
        });
        return dispose;
    }, []);

    function updateCouncilor(idx: number, patch: Partial<CouncilorDraft>): void {
        setCouncilors((cs) =>
            cs.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
        );
    }

    function addCouncilor(): void {
        setCouncilors((cs) => [...cs, { role: "稷下生" }]);
    }

    function removeCouncilor(idx: number): void {
        setCouncilors((cs) => cs.filter((_, i) => i !== idx));
    }

    async function submit(): Promise<void> {
        if (submitting) return;
        const q = question.trim();
        if (!q) return;
        if (councilors.length < 2) return;

        const requestId = crypto.randomUUID();
        const initial: RunState = {
            request_id: requestId,
            question: q,
            started_at: Date.now(),
            phase: "running",
            councilor_status: {},
        };
        setRunState(initial);
        setSubmitting(true);

        try {
            const result = await rpcCall<{
                question: string;
                elapsed_seconds: number;
                memory_id: string | null;
                councilors: CouncilorOutcome[];
                verdict: Verdict;
            }>("ensemble.council", {
                request_id: requestId,
                question: q,
                councilors: councilors.map((c) => ({
                    role: c.role,
                    profile_override: c.profile_override || null,
                    model_override: c.model_override || null,
                    brief_extra: c.brief_extra || "",
                })),
                judge: {},
                deadline_seconds: deadline,
            });
            setRunState((prev) =>
                prev && prev.request_id === requestId
                    ? {
                          ...prev,
                          phase: "done",
                          elapsed_seconds: result.elapsed_seconds,
                          verdict: result.verdict,
                          councilors: result.councilors,
                          memory_id: result.memory_id,
                      }
                    : prev,
            );
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setRunState((prev) =>
                prev && prev.request_id === requestId
                    ? { ...prev, phase: "error", error: msg }
                    : prev,
            );
        } finally {
            setSubmitting(false);
        }
    }

    const profileOptions = useMemo(() => profiles.map((p) => p.name), [profiles]);

    return (
        <div className="h-full overflow-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">群英会 · 议会式协作</h2>
                <span className="text-[10px] text-vsmuted">
                    多个 Councilor 并行论证 + Judge 裁决
                </span>
            </div>
            {profilesError && (
                <div className="text-[11px] text-vserror">
                    无法读取 profile 列表：{profilesError}
                </div>
            )}
            <div className="bg-vswidget border border-vsborder rounded p-3 space-y-3">
                <div>
                    <label className="text-[11px] text-vsmuted">议题</label>
                    <textarea
                        rows={3}
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        placeholder="例：把这个 ESX 资源迁移到 QBox 的影响范围与方案？"
                        className="w-full text-xs"
                    />
                </div>
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] text-vsmuted">
                            议员（≥ 2 名）
                        </span>
                        <button
                            onClick={addCouncilor}
                            className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                        >
                            + 增议员
                        </button>
                    </div>
                    <div className="space-y-2">
                        {councilors.map((c, i) => (
                            <CouncilorRow
                                key={i}
                                idx={i}
                                draft={c}
                                profileOptions={profileOptions}
                                canRemove={councilors.length > 2}
                                onChange={(p) => updateCouncilor(i, p)}
                                onRemove={() => removeCouncilor(i)}
                            />
                        ))}
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <label className="text-[11px] text-vsmuted">
                        每位议员超时(s):
                    </label>
                    <input
                        type="number"
                        min={30}
                        max={600}
                        value={deadline}
                        onChange={(e) => setDeadline(Number(e.target.value) || 120)}
                        className="w-20 text-xs"
                    />
                    <button
                        onClick={() => void submit()}
                        disabled={submitting || !question.trim() || councilors.length < 2}
                        className="ml-auto text-[11px] px-3 py-1 rounded bg-vsaccent text-vsaccentfg disabled:opacity-50 hover:bg-vsaccenthov"
                    >
                        {submitting ? "议事中…" : "召开议会"}
                    </button>
                </div>
            </div>
            {runState && <CouncilProgress run={runState} />}
        </div>
    );
}

function CouncilorRow({
    idx,
    draft,
    profileOptions,
    canRemove,
    onChange,
    onRemove,
}: {
    idx: number;
    draft: CouncilorDraft;
    profileOptions: string[];
    canRemove: boolean;
    onChange: (patch: Partial<CouncilorDraft>) => void;
    onRemove: () => void;
}): JSX.Element {
    return (
        <div className="border border-vsborder rounded p-2 bg-vsbg">
            <div className="flex items-center gap-2">
                <span className="text-[10px] text-vsmuted w-6">#{idx + 1}</span>
                <select
                    value={draft.role}
                    onChange={(e) => onChange({ role: e.target.value })}
                    className="text-xs flex-1"
                >
                    <option value="稷下生">稷下生 (researcher)</option>
                    <option value="百工匠">百工匠 (coder)</option>
                    <option value="司鉴">司鉴 (reviewer)</option>
                    <option value="天枢令">天枢令 (orchestrator)</option>
                </select>
                <select
                    value={draft.profile_override || ""}
                    onChange={(e) =>
                        onChange({ profile_override: e.target.value || undefined })
                    }
                    className="text-xs flex-1"
                >
                    <option value="">profile: 自动</option>
                    {profileOptions.map((p) => (
                        <option key={p} value={p}>
                            {p}
                        </option>
                    ))}
                </select>
                {canRemove && (
                    <button
                        onClick={onRemove}
                        className="text-vsmuted hover:text-vserror text-sm leading-none px-1"
                        title="移除"
                    >
                        ×
                    </button>
                )}
            </div>
            <input
                type="text"
                value={draft.brief_extra || ""}
                onChange={(e) => onChange({ brief_extra: e.target.value })}
                placeholder="侧重提示（可空）：例『重点看安全风险』"
                className="w-full text-[11px] mt-1.5"
            />
        </div>
    );
}

function CouncilProgress({ run }: { run: RunState }): JSX.Element {
    const statusEntries = Object.entries(run.councilor_status)
        .map(([k, v]) => ({ idx: Number(k), ...v }))
        .sort((a, b) => a.idx - b.idx);
    const phaseLabel =
        run.phase === "running"
            ? "议员陈述中…"
            : run.phase === "judging"
              ? "天枢令裁决中…"
              : run.phase === "done"
                ? "议会结束"
                : "出错";
    return (
        <div className="border border-vsborder rounded bg-vswidget p-3 space-y-3">
            <div className="flex items-center justify-between">
                <div className="text-xs">
                    <span className="text-vsfg font-semibold">议题：</span>
                    <span className="text-vsmuted">{run.question}</span>
                </div>
                <span
                    className={
                        "text-[11px] px-2 py-0.5 rounded " +
                        (run.phase === "done"
                            ? "bg-vsok/20 text-vsok"
                            : run.phase === "error"
                              ? "bg-vserror/20 text-vserror"
                              : "bg-vslink/20 text-vslink")
                    }
                >
                    {phaseLabel}
                </span>
            </div>
            {run.error && (
                <div className="text-[11px] text-vserror border border-vserror rounded p-2">
                    {run.error}
                </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {statusEntries.map((s) => (
                    <div
                        key={s.idx}
                        className="border border-vsborder rounded p-2 bg-vsbg"
                    >
                        <div className="flex items-center justify-between text-[11px]">
                            <span className="font-semibold">{s.role}</span>
                            <StateBadge state={s.state} />
                        </div>
                        <div className="text-[10px] text-vsmuted truncate">
                            {s.profile} · {s.model}
                        </div>
                        {s.state !== "running" && (
                            <div className="text-[10px] text-vsmuted mt-1">
                                {s.iterations != null && (
                                    <span>iter {s.iterations}</span>
                                )}
                                {s.tool_calls != null && (
                                    <span className="ml-2">tools {s.tool_calls}</span>
                                )}
                                {s.error && (
                                    <span className="text-vserror ml-2">
                                        {s.error}
                                    </span>
                                )}
                            </div>
                        )}
                    </div>
                ))}
            </div>
            {run.verdict && <VerdictCard verdict={run.verdict} elapsed={run.elapsed_seconds} memoryId={run.memory_id} />}
            {run.councilors && run.councilors.length > 0 && (
                <details className="text-[11px]">
                    <summary className="cursor-pointer text-vsmuted">
                        展开议员陈词（{run.councilors.length}）
                    </summary>
                    <div className="mt-2 space-y-2">
                        {run.councilors.map((c, i) => (
                            <div
                                key={i}
                                className="border border-vsborder rounded p-2 bg-vsbg"
                            >
                                <div className="text-[11px] font-semibold">
                                    {c.role} · {c.profile_name} · {c.model}
                                </div>
                                {c.error ? (
                                    <div className="text-[11px] text-vserror mt-1">
                                        {c.error}
                                    </div>
                                ) : (
                                    <pre className="mt-1 text-[11px] text-vsfg whitespace-pre-wrap">
                                        {c.final_text}
                                    </pre>
                                )}
                            </div>
                        ))}
                    </div>
                </details>
            )}
        </div>
    );
}

function StateBadge({ state }: { state: "running" | "ok" | "fail" }): JSX.Element {
    const cls =
        state === "running"
            ? "bg-vslink/20 text-vslink"
            : state === "ok"
              ? "bg-vsok/20 text-vsok"
              : "bg-vserror/20 text-vserror";
    const label = state === "running" ? "进行中" : state === "ok" ? "完成" : "失败";
    return <span className={"text-[10px] px-2 py-0.5 rounded " + cls}>{label}</span>;
}

function VerdictCard({
    verdict,
    elapsed,
    memoryId,
}: {
    verdict: Verdict;
    elapsed?: number;
    memoryId?: string | null;
}): JSX.Element {
    return (
        <div className="border-2 border-vslink rounded p-3 bg-vsbg space-y-2">
            <div className="flex items-center justify-between">
                <span className="text-xs font-semibold">天枢令裁决书</span>
                <span className="text-[10px] text-vsmuted">
                    {elapsed != null ? `耗时 ${elapsed.toFixed(1)}s` : ""}
                    {memoryId ? ` · 记忆 ${memoryId.slice(0, 8)}` : ""}
                </span>
            </div>
            <div className="text-[11px] text-vsfg whitespace-pre-wrap">
                {verdict.summary}
            </div>
            {verdict.chosen_path && (
                <div className="text-[11px]">
                    <span className="text-vsmuted">选定方案：</span>
                    <span className="text-vsfg">{verdict.chosen_path}</span>
                </div>
            )}
            {verdict.consensus_points.length > 0 && (
                <ListBlock title="共识" items={verdict.consensus_points} color={"vsok"} />
            )}
            {verdict.divergence_points.length > 0 && (
                <ListBlock title="分歧" items={verdict.divergence_points} color={"vswarn"} />
            )}
            {verdict.risks.length > 0 && (
                <ListBlock title="风险提示" items={verdict.risks} color={"vserror"} />
            )}
            <div className="text-[10px] text-vsmuted">
                裁决：{verdict.decided_by}
            </div>
        </div>
    );
}

const TITLE_COLOR: Record<string, string> = {
    vsok: "text-vsok",
    vswarn: "text-vswarn",
    vserror: "text-vserror",
};

function ListBlock({
    title,
    items,
    color,
}: {
    title: string;
    items: string[];
    color: "vsok" | "vswarn" | "vserror";
}): JSX.Element {
    return (
        <div>
            <div className={"text-[11px] font-semibold " + (TITLE_COLOR[color] || "text-vsfg")}>
                {title}
            </div>
            <ul className="text-[11px] list-disc pl-4 mt-1 space-y-0.5">
                {items.map((it, i) => (
                    <li key={i}>{it}</li>
                ))}
            </ul>
        </div>
    );
}
