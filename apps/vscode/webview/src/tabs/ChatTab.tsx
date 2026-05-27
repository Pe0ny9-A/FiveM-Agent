import { useEffect, useRef, useState } from "react";
import { useChatStore, ChatMessage, AssistantMessage, SessionState } from "../chatStore";
import { postCommand, rpcCall } from "../bridge";

interface ProfileItem {
    name: string;
    label: string;
    kind: string;
    default_model: string;
}

export function ChatTab(): JSX.Element {
    const sessions = useChatStore((s) => s.sessions);
    const order = useChatStore((s) => s.order);
    const activeId = useChatStore((s) => s.activeId);
    const setActive = useChatStore((s) => s.setActive);
    const createSession = useChatStore((s) => s.createSession);
    const closeSession = useChatStore((s) => s.closeSession);
    const renameSession = useChatStore((s) => s.renameSession);

    const [creating, setCreating] = useState(false);
    const [profiles, setProfiles] = useState<ProfileItem[]>([]);
    const [showStartMenu, setShowStartMenu] = useState(false);

    useEffect(() => {
        rpcCall<{ active: string | null; items: ProfileItem[] }>("profiles.list")
            .then((r) => setProfiles(r.items))
            .catch(() => setProfiles([]));
    }, []);

    // 首次进入：如果还没会话，自动起一个
    useEffect(() => {
        if (order.length === 0 && !creating) {
            setCreating(true);
            createSession()
                .catch(() => {
                    /* error 已 patch 进 store */
                })
                .finally(() => setCreating(false));
        }
    }, [order.length, creating, createSession]);

    const active = activeId ? sessions[activeId] : null;

    return (
        <div className="h-full flex">
            <aside className="w-44 border-r border-vsborder bg-vspanel flex flex-col">
                <div className="p-2 border-b border-vsborder relative">
                    <button
                        onClick={() => setShowStartMenu((v) => !v)}
                        className="w-full text-[11px] px-2 py-1 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                    >
                        + 新会话 ▾
                    </button>
                    {showStartMenu && (
                        <div className="absolute left-2 right-2 top-full mt-1 z-10 bg-vsbg border border-vsborder rounded shadow-lg">
                            <button
                                className="w-full text-left text-[11px] px-2 py-1 hover:bg-vswidget"
                                onClick={() => {
                                    setShowStartMenu(false);
                                    void createSession();
                                }}
                            >
                                ✨ 默认 profile
                            </button>
                            {profiles.length > 0 && (
                                <div className="border-t border-vsborder my-0.5" />
                            )}
                            {profiles.map((p) => (
                                <button
                                    key={p.name}
                                    className="w-full text-left text-[11px] px-2 py-1 hover:bg-vswidget truncate"
                                    onClick={() => {
                                        setShowStartMenu(false);
                                        void createSession(p.name);
                                    }}
                                    title={p.default_model}
                                >
                                    {p.name}
                                    <span className="text-vsmuted ml-1">
                                        · {p.kind}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex-1 overflow-auto">
                    {order.length === 0 && (
                        <div className="p-3 text-[11px] text-vsmuted italic">
                            正在为小宝准备一个新会话…
                        </div>
                    )}
                    {order.map((id) => (
                        <SessionRow
                            key={id}
                            session={sessions[id]}
                            active={id === activeId}
                            onClick={() => setActive(id)}
                            onClose={() => void closeSession(id)}
                            onRename={(t) => renameSession(id, t)}
                        />
                    ))}
                </div>
            </aside>
            <section className="flex-1 flex flex-col min-w-0">
                {active ? (
                    <ActiveSession session={active} profiles={profiles} />
                ) : (
                    <div className="flex-1 flex items-center justify-center text-vsmuted text-xs">
                        请选择或新建一个会话
                    </div>
                )}
            </section>
        </div>
    );
}

function SessionRow({
    session,
    active,
    onClick,
    onClose,
    onRename,
}: {
    session: SessionState;
    active: boolean;
    onClick: () => void;
    onClose: () => void;
    onRename: (title: string) => void;
}): JSX.Element {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(session.title);
    return (
        <div
            onClick={onClick}
            className={
                "px-2 py-2 border-b border-vsborder cursor-pointer text-xs " +
                (active ? "bg-vswidget" : "hover:bg-vswidget/50")
            }
        >
            <div className="flex items-center justify-between gap-1">
                {editing ? (
                    <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={() => {
                            onRename(draft.trim() || session.title);
                            setEditing(false);
                        }}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                            else if (e.key === "Escape") {
                                setDraft(session.title);
                                setEditing(false);
                            }
                        }}
                        className="flex-1 text-xs px-1 py-0"
                    />
                ) : (
                    <span
                        className="flex-1 truncate"
                        onDoubleClick={() => setEditing(true)}
                    >
                        {session.title}
                    </span>
                )}
                <button
                    onClick={(e) => {
                        e.stopPropagation();
                        onClose();
                    }}
                    className="text-vsmuted hover:text-vserror text-[14px] leading-none"
                    title="关闭会话"
                >
                    ×
                </button>
            </div>
            <div className="text-[10px] text-vsmuted mt-0.5 truncate">
                {session.provider} · {shortenModel(session.model)}
            </div>
        </div>
    );
}

function shortenModel(m: string): string {
    return m.replace(/^claude-/, "").replace(/^deepseek-/, "ds-").replace(/^gpt-/, "gpt-");
}

function ActiveSession({
    session,
    profiles,
}: {
    session: SessionState;
    profiles: ProfileItem[];
}): JSX.Element {
    const sendMessage = useChatStore((s) => s.sendMessage);
    const cancelSend = useChatStore((s) => s.cancelSend);
    const answerHitl = useChatStore((s) => s.answerHitl);
    const switchProfile = useChatStore((s) => s.switchProfile);
    const [draft, setDraft] = useState("");
    const [showSwitch, setShowSwitch] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const el = scrollRef.current;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }, [session.messages, session.pendingHitl]);

    function submit(): void {
        const text = draft.trim();
        if (!text || session.sending) return;
        setDraft("");
        void sendMessage(session.session_id, text);
    }

    return (
        <>
            <div className="px-3 py-1.5 border-b border-vsborder bg-vspanel text-[11px] text-vsmuted flex items-center gap-2 relative">
                <button
                    onClick={() => setShowSwitch((v) => !v)}
                    disabled={session.sending}
                    className="text-[11px] px-2 py-0.5 rounded border border-vsborder hover:border-vslink disabled:opacity-50 flex items-center gap-1"
                    title="切换 profile（会重启会话）"
                >
                    <span className="text-vsfg">{session.profile_name || "default"}</span>
                    <span className="text-vsmuted">▾</span>
                </button>
                {showSwitch && (
                    <div className="absolute left-3 top-full mt-1 z-20 bg-vsbg border border-vsborder rounded shadow-lg min-w-[180px]">
                        {profiles.length === 0 ? (
                            <div className="text-[11px] px-2 py-1 text-vsmuted italic">
                                没有可用 profile
                            </div>
                        ) : (
                            profiles.map((p) => (
                                <button
                                    key={p.name}
                                    className={
                                        "w-full text-left text-[11px] px-2 py-1 hover:bg-vswidget truncate " +
                                        (p.name === session.profile_name
                                            ? "text-vslink"
                                            : "")
                                    }
                                    onClick={() => {
                                        setShowSwitch(false);
                                        if (p.name !== session.profile_name) {
                                            void switchProfile(session.session_id, p.name);
                                        }
                                    }}
                                    title={p.default_model}
                                >
                                    {p.name}
                                    <span className="text-vsmuted ml-1">
                                        · {p.kind}
                                    </span>
                                </button>
                            ))
                        )}
                    </div>
                )}
                <span>·</span>
                <span>
                    model: <span className="text-vsfg">{session.model}</span>
                </span>
                <span>·</span>
                <span>
                    mode: <span className="text-vsfg">{session.mode}</span>
                </span>
                {session.error && (
                    <span className="ml-auto text-vserror truncate max-w-md">
                        {session.error}
                    </span>
                )}
            </div>
            <div ref={scrollRef} className="flex-1 overflow-auto p-3 space-y-3">
                {session.messages.map((m) => (
                    <MessageBubble key={m.id} msg={m} />
                ))}
                {session.pendingHitl && (
                    <HitlCard
                        pending={session.pendingHitl}
                        onApprove={() => void answerHitl(session.session_id, true)}
                        onReject={() => void answerHitl(session.session_id, false)}
                    />
                )}
            </div>
            <div className="p-2 border-t border-vsborder bg-vspanel">
                <div className="flex gap-2 items-end">
                    <textarea
                        rows={2}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                submit();
                            }
                        }}
                        placeholder="跟玄玑说点什么…（Enter 发送 / Shift+Enter 换行）"
                        className="flex-1 resize-none text-xs"
                    />
                    {session.sending ? (
                        <button
                            onClick={() => void cancelSend(session.session_id)}
                            className="text-[11px] px-3 py-1.5 rounded bg-vssec text-vssecfg"
                        >
                            取消
                        </button>
                    ) : (
                        <button
                            onClick={submit}
                            disabled={!draft.trim()}
                            className="text-[11px] px-3 py-1.5 rounded bg-vsaccent text-vsaccentfg disabled:opacity-50 hover:bg-vsaccenthov"
                        >
                            发送
                        </button>
                    )}
                </div>
            </div>
        </>
    );
}

function MessageBubble({ msg }: { msg: ChatMessage }): JSX.Element {
    if (msg.role === "user") {
        return (
            <div className="flex flex-col gap-1">
                <div className="text-[10px] font-semibold text-vslink">用户</div>
                <div className="bg-vsinput border border-vsborder text-vsinputfg px-3 py-2 rounded text-xs whitespace-pre-wrap break-words">
                    {msg.text}
                </div>
            </div>
        );
    }
    const a = msg as AssistantMessage & { id: string };
    return (
        <div className="flex flex-col gap-1.5">
            <div className="text-[10px] font-semibold text-vsok">玄玑</div>
            {a.thinking && (
                <details className="bg-vswidget border border-vsborder rounded px-2 py-1 text-[11px] text-vsmuted">
                    <summary className="cursor-pointer">思考过程</summary>
                    <div className="whitespace-pre-wrap mt-1">{a.thinking}</div>
                </details>
            )}
            {a.tools.map((t, i) => (
                <ToolEventChip key={t.tool_call_id || i} ev={t} />
            ))}
            <div className="bg-vswidget border border-vsborder rounded px-3 py-2 text-xs whitespace-pre-wrap break-words markdown">
                {renderMarkdownLite(a.text)}
                {a.streaming && <span className="inline-block w-2 h-3 bg-vsfg/60 ml-0.5 animate-pulse" />}
            </div>
            {!a.streaming && (a.usage || a.stop_reason) && (
                <div className="text-[10px] text-vsmuted">
                    {a.stop_reason && <span>stop: {a.stop_reason}</span>}
                    {a.usage && (
                        <span className="ml-2">
                            in {a.usage.input_tokens} · out {a.usage.output_tokens}
                        </span>
                    )}
                </div>
            )}
        </div>
    );
}

function ToolEventChip({ ev }: { ev: AssistantMessage["tools"][number] }): JSX.Element {
    const color =
        ev.state === "started"
            ? "border-vslink text-vslink"
            : ev.state === "blocked"
              ? "border-vswarn text-vswarn"
              : ev.ok
                ? "border-vsok text-vsok"
                : "border-vserror text-vserror";
    const label =
        ev.state === "started"
            ? "运行中"
            : ev.state === "blocked"
              ? `被拦截：${ev.reason || "Gate"}`
              : `${ev.ok ? "成功" : "失败"}${ev.duration_ms != null ? ` · ${ev.duration_ms}ms` : ""}`;
    return (
        <details className={"text-[11px] border rounded px-2 py-1 bg-vswidget " + color}>
            <summary className="cursor-pointer flex items-center gap-2">
                <span className="font-mono">{ev.tool_name}</span>
                <span className="text-vsmuted">{label}</span>
            </summary>
            {ev.args && (
                <pre className="mt-1 text-[10px] text-vsmuted overflow-x-auto">
                    {JSON.stringify(ev.args, null, 2)}
                </pre>
            )}
        </details>
    );
}

function HitlCard({
    pending,
    onApprove,
    onReject,
}: {
    pending: NonNullable<SessionState["pendingHitl"]>;
    onApprove: () => void;
    onReject: () => void;
}): JSX.Element {
    return (
        <div className="border-2 border-vswarn bg-vswidget rounded p-3 text-xs">
            <div className="font-semibold text-vswarn">司辰阁 · 高危确认</div>
            <div className="mt-1 text-vsmuted">
                工具：<span className="text-vsfg font-mono">{pending.tool}</span> · 风险：
                <span className="text-vsfg">{pending.risk}</span>
            </div>
            <div className="mt-1 text-vsmuted">{pending.reason}</div>
            <pre className="mt-2 text-[10px] bg-vsbg p-2 rounded overflow-x-auto">
                {JSON.stringify(pending.args, null, 2)}
            </pre>
            <div className="mt-2 flex gap-2">
                <button
                    onClick={onApprove}
                    className="text-[11px] px-3 py-1 rounded bg-vsaccent text-vsaccentfg hover:bg-vsaccenthov"
                >
                    批准
                </button>
                <button
                    onClick={onReject}
                    className="text-[11px] px-3 py-1 rounded bg-vssec text-vssecfg"
                >
                    拒绝
                </button>
            </div>
        </div>
    );
}

// 极轻量 markdown：只识别 [文本](路径#L行号) → 点击跳转 + ```fence```。
// 复杂渲染留到后续。
function renderMarkdownLite(text: string): JSX.Element[] {
    if (!text) return [];
    const out: JSX.Element[] = [];
    const linkRe = /\[([^\]]+)\]\(([^)]+)\)/g;
    const fenceRe = /```([a-zA-Z]*)\n([\s\S]*?)```/g;

    // 先按 fence 拆段
    const segments: { kind: "text" | "code"; lang?: string; body: string }[] = [];
    let lastIdx = 0;
    let fm: RegExpExecArray | null;
    while ((fm = fenceRe.exec(text)) !== null) {
        if (fm.index > lastIdx) {
            segments.push({ kind: "text", body: text.slice(lastIdx, fm.index) });
        }
        segments.push({ kind: "code", lang: fm[1], body: fm[2] });
        lastIdx = fm.index + fm[0].length;
    }
    if (lastIdx < text.length) {
        segments.push({ kind: "text", body: text.slice(lastIdx) });
    }

    segments.forEach((seg, i) => {
        if (seg.kind === "code") {
            out.push(
                <pre key={"c" + i}>
                    <code>{seg.body}</code>
                </pre>,
            );
            return;
        }
        // 文本里挑出链接
        let cursor = 0;
        let lm: RegExpExecArray | null;
        const localRe = new RegExp(linkRe.source, "g");
        while ((lm = localRe.exec(seg.body)) !== null) {
            if (lm.index > cursor) {
                out.push(<span key={"t" + i + "-" + cursor}>{seg.body.slice(cursor, lm.index)}</span>);
            }
            const label = lm[1];
            const target = lm[2];
            out.push(
                <a
                    key={"l" + i + "-" + lm.index}
                    href="#"
                    onClick={(e) => {
                        e.preventDefault();
                        postCommand("xuanji.openFile", { target });
                    }}
                >
                    {label}
                </a>,
            );
            cursor = lm.index + lm[0].length;
        }
        if (cursor < seg.body.length) {
            out.push(<span key={"t" + i + "-tail"}>{seg.body.slice(cursor)}</span>);
        }
    });
    return out;
}
