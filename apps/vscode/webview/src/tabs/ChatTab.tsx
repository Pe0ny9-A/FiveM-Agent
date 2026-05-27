import { useEffect, useRef, useState } from "react";
import {
    useChatStore,
    ChatMessage,
    AssistantMessage,
    SessionState,
    ToolEvent,
} from "../chatStore";
import { hostCall, postCommand, rpcCall } from "../bridge";

interface ProfileItem {
    name: string;
    label: string;
    kind: string;
    default_model: string;
}

interface SkillItem {
    id: string;
    summary: string;
    tags: string[];
}

type AttachedContext =
    | {
          kind: "file";
          path: string;
          text: string;
          truncated?: boolean;
      }
    | {
          kind: "selection";
          path: string;
          text: string;
          line_from: number;
          line_to: number;
          is_full_file?: boolean;
      }
    | {
          kind: "image";
          path: string;
      };

interface BuiltinCommand {
    name: string;
    description: string;
    handler: "clear" | "reset" | "help" | "compact";
}

const BUILTIN_COMMANDS: BuiltinCommand[] = [
    { name: "/clear", description: "清空当前会话消息（仅前端，后端历史保留）", handler: "clear" },
    { name: "/reset", description: "彻底重启会话（chat.close + chat.start）", handler: "reset" },
    { name: "/compact", description: "提示玄玑做一次摘要压缩", handler: "compact" },
    { name: "/help", description: "查看可用命令与提示", handler: "help" },
];

export function ChatTab(): JSX.Element {
    const sessions = useChatStore((s) => s.sessions);
    const order = useChatStore((s) => s.order);
    const activeId = useChatStore((s) => s.activeId);
    const hydrated = useChatStore((s) => s.hydrated);
    const setActive = useChatStore((s) => s.setActive);
    const createSession = useChatStore((s) => s.createSession);
    const closeSession = useChatStore((s) => s.closeSession);
    const renameSession = useChatStore((s) => s.renameSession);
    const hydrate = useChatStore((s) => s.hydrate);

    const [creating, setCreating] = useState(false);
    const [profiles, setProfiles] = useState<ProfileItem[]>([]);
    const [showStartMenu, setShowStartMenu] = useState(false);

    useEffect(() => {
        hydrate();
    }, [hydrate]);

    useEffect(() => {
        rpcCall<{ active: string | null; items: ProfileItem[] }>("profiles.list")
            .then((r) => setProfiles(r.items))
            .catch(() => setProfiles([]));
    }, []);

    // hydrate 完成后如果还没会话，自动起一个
    useEffect(() => {
        if (!hydrated) return;
        if (order.length === 0 && !creating) {
            setCreating(true);
            createSession()
                .catch(() => {
                    /* error 已 patch 进 store */
                })
                .finally(() => setCreating(false));
        }
    }, [hydrated, order.length, creating, createSession]);

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
    const closeSession = useChatStore((s) => s.closeSession);
    const createSession = useChatStore((s) => s.createSession);
    const [draft, setDraft] = useState("");
    const [showSwitch, setShowSwitch] = useState(false);
    const [showSlashMenu, setShowSlashMenu] = useState(false);
    const [showPlusMenu, setShowPlusMenu] = useState(false);
    const [skills, setSkills] = useState<SkillItem[]>([]);
    const [attached, setAttached] = useState<AttachedContext[]>([]);
    const [busyAttach, setBusyAttach] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        const el = scrollRef.current;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }, [session.messages, session.pendingHitl]);

    // 拉一次 skills 列表（/ 菜单要用）
    useEffect(() => {
        rpcCall<{ items: SkillItem[] }>("skill.list", { limit: 50 })
            .then((r) => setSkills(r.items || []))
            .catch(() => setSkills([]));
    }, [session.session_id]);

    // 点击外部关菜单
    useEffect(() => {
        if (!showSlashMenu && !showPlusMenu) return;
        const onClick = (e: MouseEvent): void => {
            const t = e.target as HTMLElement;
            if (!t.closest("[data-input-menu]")) {
                setShowSlashMenu(false);
                setShowPlusMenu(false);
            }
        };
        window.addEventListener("mousedown", onClick);
        return () => window.removeEventListener("mousedown", onClick);
    }, [showSlashMenu, showPlusMenu]);

    function buildContextPrefix(): string {
        if (attached.length === 0) return "";
        const blocks: string[] = [];
        for (const c of attached) {
            if (c.kind === "image") {
                blocks.push(`![image](${c.path})`);
            } else if (c.kind === "selection") {
                const range = c.is_full_file
                    ? `${c.path}（整文件，光标 L${c.line_from}）`
                    : `${c.path}#L${c.line_from}-${c.line_to}`;
                blocks.push(
                    "```" + langOf(c.path) + "\n" +
                    "// " + range + "\n" +
                    c.text + "\n" +
                    "```",
                );
            } else {
                blocks.push(
                    "```" + langOf(c.path) + "\n" +
                    "// " + c.path + (c.truncated ? "（已截断到 60KB）" : "") + "\n" +
                    c.text + "\n" +
                    "```",
                );
            }
        }
        return blocks.join("\n\n") + "\n\n";
    }

    async function runSlash(cmd: BuiltinCommand): Promise<void> {
        setShowSlashMenu(false);
        if (cmd.handler === "clear") {
            // 仅清前端缓存
            useChatStore.setState((s) => {
                const cur = s.sessions[session.session_id];
                if (!cur) return s;
                return {
                    sessions: {
                        ...s.sessions,
                        [session.session_id]: { ...cur, messages: [] },
                    },
                };
            });
        } else if (cmd.handler === "reset") {
            const oldId = session.session_id;
            const profile = session.profile_name || undefined;
            await closeSession(oldId);
            await createSession(profile).catch(() => undefined);
        } else if (cmd.handler === "compact") {
            setDraft((d) => "请把当前会话做一次摘要压缩，只保留关键决策与未完成事项。" + (d ? "\n" + d : ""));
            textareaRef.current?.focus();
        } else if (cmd.handler === "help") {
            setDraft(
                "/clear 清空消息   /reset 重启会话   /compact 摘要压缩\n" +
                "/<skill 名> 让玄玑按某个 procedural skill 执行",
            );
            textareaRef.current?.focus();
        }
    }

    function insertSkillSlug(skill: SkillItem): void {
        setShowSlashMenu(false);
        const slug = (skill.summary || skill.id).replace(/\s+/g, "-").slice(0, 40);
        setDraft((d) => `请按 skill「${skill.summary || skill.id}」执行。\n（skill_id: ${skill.id}）\n${d}`);
        textareaRef.current?.focus();
        // 防 lint：slug 用作未来扩展，先标记下
        void slug;
    }

    async function attachFiles(): Promise<void> {
        setShowPlusMenu(false);
        setBusyAttach(true);
        try {
            const r = await hostCall<{
                items: { path: string; text: string; truncated?: boolean }[];
            }>("host.pickFiles", { multiple: true });
            if (r.items && r.items.length > 0) {
                setAttached((prev) => [
                    ...prev,
                    ...r.items.map((f) => ({
                        kind: "file" as const,
                        path: f.path,
                        text: f.text,
                        truncated: f.truncated,
                    })),
                ]);
            }
        } finally {
            setBusyAttach(false);
        }
    }

    async function attachSelection(): Promise<void> {
        setShowPlusMenu(false);
        setBusyAttach(true);
        try {
            const r = await hostCall<{
                item: {
                    path: string;
                    text: string;
                    line_from: number;
                    line_to: number;
                    is_full_file?: boolean;
                } | null;
            }>("host.getActiveSelection");
            if (r.item) {
                setAttached((prev) => [
                    ...prev,
                    { kind: "selection", ...r.item! },
                ]);
            }
        } finally {
            setBusyAttach(false);
        }
    }

    async function attachImage(): Promise<void> {
        setShowPlusMenu(false);
        setBusyAttach(true);
        try {
            const r = await hostCall<{ item: { path: string } | null }>("host.pickImage");
            if (r.item) {
                setAttached((prev) => [
                    ...prev,
                    { kind: "image", path: r.item!.path },
                ]);
            }
        } finally {
            setBusyAttach(false);
        }
    }

    function removeAttached(idx: number): void {
        setAttached((prev) => prev.filter((_, i) => i !== idx));
    }

    function submit(): void {
        const text = draft.trim();
        if (!text || session.sending) return;
        const prefix = buildContextPrefix();
        setDraft("");
        setAttached([]);
        void sendMessage(session.session_id, prefix + text);
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
                    <span className="ml-2 text-vserror truncate max-w-[260px]">
                        {session.error}
                    </span>
                )}
                <button
                    onClick={() => postCommand("xuanji.openWorkbench")}
                    className="ml-auto text-[11px] px-2 py-0.5 rounded border border-vsborder hover:border-vslink hover:text-vslink flex items-center gap-1"
                    title="在编辑器窗口打开（独立 panel，更宽更舒展）"
                >
                    <span>⧉</span>
                    <span>在编辑器中打开</span>
                </button>
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
                {attached.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1.5">
                        {attached.map((c, i) => (
                            <AttachedChip
                                key={i}
                                ctx={c}
                                onRemove={() => removeAttached(i)}
                            />
                        ))}
                    </div>
                )}
                <div className="flex gap-1.5 items-end">
                    <div className="relative" data-input-menu>
                        <button
                            type="button"
                            onClick={() => {
                                setShowSlashMenu((v) => !v);
                                setShowPlusMenu(false);
                            }}
                            className="text-[12px] w-7 h-7 rounded border border-vsborder hover:border-vslink hover:text-vslink flex items-center justify-center"
                            title="命令与 skills"
                        >
                            /
                        </button>
                        {showSlashMenu && (
                            <div className="absolute left-0 bottom-full mb-1 z-30 bg-vsbg border border-vsborder rounded shadow-lg w-72 max-h-72 overflow-auto">
                                <div className="px-2 py-1 text-[10px] text-vsmuted bg-vswidget sticky top-0">
                                    内置命令
                                </div>
                                {BUILTIN_COMMANDS.map((c) => (
                                    <button
                                        key={c.name}
                                        onClick={() => void runSlash(c)}
                                        className="w-full text-left px-2 py-1.5 hover:bg-vswidget border-b border-vsborder/50"
                                    >
                                        <div className="text-[11px] font-mono text-vslink">{c.name}</div>
                                        <div className="text-[10px] text-vsmuted">{c.description}</div>
                                    </button>
                                ))}
                                <div className="px-2 py-1 text-[10px] text-vsmuted bg-vswidget sticky top-0">
                                    Skills（{skills.length}）
                                </div>
                                {skills.length === 0 && (
                                    <div className="px-2 py-2 text-[11px] text-vsmuted italic">
                                        还没有保存的 skill。
                                    </div>
                                )}
                                {skills.map((s) => (
                                    <button
                                        key={s.id}
                                        onClick={() => insertSkillSlug(s)}
                                        className="w-full text-left px-2 py-1.5 hover:bg-vswidget border-b border-vsborder/50"
                                    >
                                        <div className="text-[11px] truncate">{s.summary || s.id}</div>
                                        {s.tags && s.tags.length > 0 && (
                                            <div className="text-[10px] text-vsmuted truncate">
                                                {s.tags.slice(0, 4).join(" · ")}
                                            </div>
                                        )}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    <div className="relative" data-input-menu>
                        <button
                            type="button"
                            onClick={() => {
                                setShowPlusMenu((v) => !v);
                                setShowSlashMenu(false);
                            }}
                            disabled={busyAttach}
                            className="text-[12px] w-7 h-7 rounded border border-vsborder hover:border-vslink hover:text-vslink flex items-center justify-center disabled:opacity-50"
                            title="添加文件 / 当前选中 / 图片"
                        >
                            +
                        </button>
                        {showPlusMenu && (
                            <div className="absolute left-0 bottom-full mb-1 z-30 bg-vsbg border border-vsborder rounded shadow-lg min-w-[180px]">
                                <button
                                    onClick={() => void attachFiles()}
                                    className="w-full text-left text-[11px] px-2 py-1.5 hover:bg-vswidget"
                                >
                                    📁 添加文件…
                                </button>
                                <button
                                    onClick={() => void attachSelection()}
                                    className="w-full text-left text-[11px] px-2 py-1.5 hover:bg-vswidget"
                                >
                                    📋 当前编辑器选中
                                </button>
                                <button
                                    onClick={() => void attachImage()}
                                    className="w-full text-left text-[11px] px-2 py-1.5 hover:bg-vswidget"
                                >
                                    🖼️ 插入图片引用
                                </button>
                            </div>
                        )}
                    </div>
                    <textarea
                        ref={textareaRef}
                        rows={2}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                submit();
                            }
                        }}
                        placeholder="跟玄玑说点什么…（Enter 发送 / Shift+Enter 换行 / 点 / 看命令 / 点 + 加上下文）"
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
            <ContextStatusBar session={session} />
        </>
    );
}

interface CompactionInfo {
    enabled: boolean;
    max_context_tokens: number;
    keep_recent_turns: number;
}

function ContextStatusBar({ session }: { session: SessionState }): JSX.Element {
    const [compaction, setCompaction] = useState<CompactionInfo | null>(null);

    useEffect(() => {
        rpcCall<{ compaction: CompactionInfo }>("config.summary")
            .then((r) => setCompaction(r.compaction))
            .catch(() => setCompaction(null));
    }, []);

    // 取最近一条带 usage 的 assistant 消息
    let usage: { input_tokens: number; output_tokens: number } | null = null;
    let totalTools = 0;
    for (let i = session.messages.length - 1; i >= 0; i--) {
        const m = session.messages[i];
        if (m.role !== "assistant") continue;
        const a = m as AssistantMessage & { id: string };
        if (a.usage && !usage) usage = a.usage;
        totalTools += a.tools.length;
    }

    const inTokens = usage?.input_tokens ?? 0;
    const outTokens = usage?.output_tokens ?? 0;
    const ctxMax = compaction?.max_context_tokens ?? 0;
    const ctxUsed = inTokens; // 上一轮 input_tokens 即上下文占用估计
    const ctxPct = ctxMax > 0 ? Math.min(100, Math.round((ctxUsed / ctxMax) * 100)) : 0;

    let ctxColor = "text-vsmuted";
    if (ctxPct >= 90) ctxColor = "text-vserror";
    else if (ctxPct >= 70) ctxColor = "text-vswarn";
    else if (ctxUsed > 0) ctxColor = "text-vsok";

    return (
        <div className="px-3 py-1 border-t border-vsborder bg-vsbg text-[10px] text-vsmuted flex items-center gap-3 whitespace-nowrap">
            {session.sending && (
                <span className="text-vslink flex items-center gap-1">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-vslink animate-pulse" />
                    玄玑思考中…
                </span>
            )}
            <span title="上一轮输入 / 输出 token">
                <span className="opacity-70">↑</span> {fmtNum(inTokens)}
                <span className="mx-0.5 opacity-40">·</span>
                <span className="opacity-70">↓</span> {fmtNum(outTokens)}
            </span>
            <span className={ctxColor} title="上下文占用 / 自动 compact 阈值">
                ctx {fmtNum(ctxUsed)}
                {ctxMax > 0 && (
                    <>
                        <span className="opacity-40"> / </span>
                        {fmtNum(ctxMax)}
                        <span className="ml-1 opacity-70">({ctxPct}%)</span>
                    </>
                )}
            </span>
            {ctxMax > 0 && (
                <span className="flex-1 max-w-[120px] h-1 bg-vswidget rounded overflow-hidden">
                    <span
                        className={
                            "block h-full " +
                            (ctxPct >= 90
                                ? "bg-vserror"
                                : ctxPct >= 70
                                  ? "bg-vswarn"
                                  : "bg-vsok")
                        }
                        style={{ width: ctxPct + "%" }}
                    />
                </span>
            )}
            <span title="是否启用自动 compact">
                {compaction?.enabled ? "🪶 auto-compact" : "✋ compact 关"}
            </span>
            {totalTools > 0 && (
                <span className="opacity-70" title="本会话累计工具调用次数">
                    🔧 {totalTools}
                </span>
            )}
            <span className="ml-auto opacity-60">{session.provider}</span>
        </div>
    );
}

function fmtNum(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
    return String(n);
}

function AttachedChip({
    ctx,
    onRemove,
}: {
    ctx: AttachedContext;
    onRemove: () => void;
}): JSX.Element {
    let icon = "📎";
    let label = "";
    let title = "";
    if (ctx.kind === "file") {
        icon = "📁";
        label = shortPath(ctx.path) + (ctx.truncated ? " (截断)" : "");
        title = ctx.path + (ctx.truncated ? " · 已截断到 60KB" : "");
    } else if (ctx.kind === "selection") {
        icon = "📋";
        label = ctx.is_full_file
            ? `${shortPath(ctx.path)} (整文件 L${ctx.line_from})`
            : `${shortPath(ctx.path)}:L${ctx.line_from}-${ctx.line_to}`;
        title = `${ctx.path}#L${ctx.line_from}-${ctx.line_to}`;
    } else {
        icon = "🖼️";
        label = shortPath(ctx.path);
        title = ctx.path;
    }
    return (
        <span
            className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-vswidget border border-vsborder"
            title={title}
        >
            <span aria-hidden>{icon}</span>
            <span className="truncate max-w-[200px]">{label}</span>
            <button
                onClick={onRemove}
                className="text-vsmuted hover:text-vserror text-[12px] leading-none ml-0.5"
                title="移除"
            >
                ×
            </button>
        </span>
    );
}

function describeToolEvent(ev: ToolEvent): {
    icon: string;
    label: string;
    target: string | null;
    fullCommand?: string;
} {
    const args = (ev.args || {}) as Record<string, unknown>;
    const get = (k: string): string => {
        const v = args[k];
        return typeof v === "string" ? v : "";
    };
    switch (ev.tool_name) {
        case "read_file": {
            const path = get("path") || get("file_path") || "?";
            const offset = args["offset"];
            const limit = args["limit"];
            let target = path;
            let suffix = "";
            if (typeof offset === "number" && typeof limit === "number") {
                const start = offset + 1;
                const end = offset + limit;
                target = `${path}#L${start}-${end}`;
                suffix = `:L${start}-${end}`;
            }
            return { icon: "📖", label: shortPath(path) + suffix, target };
        }
        case "write_file": {
            const path = get("path") || get("file_path") || "?";
            return { icon: "✏️", label: shortPath(path), target: path };
        }
        case "list_dir": {
            const path = get("path") || ".";
            return { icon: "📁", label: shortPath(path) + "/", target: path };
        }
        case "ripgrep": {
            const pattern = get("pattern") || get("query");
            const path = get("path") || ".";
            return {
                icon: "🔍",
                label: `"${pattern}" in ${shortPath(path)}`,
                target: path,
            };
        }
        case "run_shell": {
            const cmd = get("cmd") || get("command") || "";
            return {
                icon: "$",
                label: cmd.length > 80 ? cmd.slice(0, 77) + "…" : cmd,
                target: null,
                fullCommand: cmd,
            };
        }
        default: {
            // 兜底：把第一个 string 参数显出来
            const firstStr = Object.entries(args).find(
                ([, v]) => typeof v === "string",
            );
            const label = firstStr ? `${ev.tool_name}(${firstStr[1]})` : ev.tool_name;
            return { icon: "🔧", label, target: null };
        }
    }
}

function shortPath(p: string): string {
    if (!p) return "";
    const norm = p.replace(/\\/g, "/");
    // 保留最多 3 段尾部
    const segs = norm.split("/").filter(Boolean);
    if (segs.length <= 3) return norm;
    return ".../" + segs.slice(-3).join("/");
}

function langOf(p: string): string {
    const m = /\.([a-zA-Z0-9]+)$/.exec(p);
    if (!m) return "";
    const ext = m[1].toLowerCase();
    const map: Record<string, string> = {
        ts: "ts", tsx: "tsx", js: "js", jsx: "jsx",
        py: "python", lua: "lua", rs: "rust", go: "go",
        java: "java", kt: "kotlin", c: "c", h: "c",
        cpp: "cpp", cc: "cpp", hpp: "cpp",
        cs: "csharp", rb: "ruby", php: "php", sh: "bash",
        json: "json", yaml: "yaml", yml: "yaml", toml: "toml",
        md: "markdown", html: "html", css: "css", scss: "scss",
        sql: "sql", xml: "xml", ini: "ini",
    };
    return map[ext] || ext;
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
    const status =
        ev.state === "started"
            ? "运行中"
            : ev.state === "blocked"
              ? `被拦截：${ev.reason || "Gate"}`
              : `${ev.ok ? "成功" : "失败"}${ev.duration_ms != null ? ` · ${ev.duration_ms}ms` : ""}`;
    const { icon, label, target, fullCommand } = describeToolEvent(ev);
    const onTargetClick = target
        ? (e: React.MouseEvent) => {
              e.preventDefault();
              e.stopPropagation();
              postCommand("xuanji.openFile", { target });
          }
        : undefined;
    return (
        <details className={"text-[11px] border rounded px-2 py-1 bg-vswidget " + color}>
            <summary className="cursor-pointer flex items-center gap-2 flex-wrap">
                <span className="font-mono">{ev.tool_name}</span>
                <span aria-hidden>{icon}</span>
                {target ? (
                    <a
                        href="#"
                        onClick={onTargetClick}
                        className="font-mono truncate max-w-[320px] underline decoration-dotted hover:decoration-solid"
                        title={"点击跳转：" + target}
                    >
                        {label}
                    </a>
                ) : (
                    <span
                        className="font-mono truncate max-w-[320px]"
                        title={fullCommand || label}
                    >
                        {label}
                    </span>
                )}
                <span className="ml-auto text-vsmuted">{status}</span>
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
