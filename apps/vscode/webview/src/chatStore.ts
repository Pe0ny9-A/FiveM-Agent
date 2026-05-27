// 多会话聊天状态。
// Session 列表 + 每会话的消息流，订阅后端 chat.* notification。
// 持久化：webview 状态写入 vscode.setState/getState，关闭后再开能还原会话历史。
// 后端 session_id 重启即失效；恢复出来的会话标记 archived=true，
// 用户首次发送时自动 chat.start 拿新 session_id 替换。

import { create } from "zustand";
import { onNotification, rpcCall, loadState, persistState } from "./bridge";

export type MessageRole = "user" | "assistant" | "system";

export interface ToolEvent {
    tool_call_id: string;
    tool_name: string;
    args?: Record<string, unknown>;
    state: "started" | "blocked" | "done";
    ok?: boolean;
    duration_ms?: number;
    reason?: string;
}

export interface AssistantMessage {
    role: "assistant";
    text: string;
    thinking: string;
    tools: ToolEvent[];
    stop_reason: string | null;
    usage: { input_tokens: number; output_tokens: number } | null;
    streaming: boolean;
}

export interface UserMessage {
    role: "user";
    text: string;
}

export type ChatMessage = (UserMessage | AssistantMessage) & { id: string };

interface PersistedSession {
    title: string;
    profile_name: string | null;
    model: string;
    provider: string;
    mode: string;
    messages: ChatMessage[];
}
interface PersistedState {
    sessions: Record<string, PersistedSession>;
    order: string[];
    activeId: string | null;
}

export interface HitlPending {
    request_id: string;
    tool: string;
    risk: string;
    args: Record<string, unknown>;
    reason: string;
}

export interface SessionState {
    session_id: string;
    title: string;
    profile_name: string | null;
    model: string;
    provider: string;
    mode: string;
    messages: ChatMessage[];
    pendingAssistant: string | null; // id of streaming assistant message
    pendingHitl: HitlPending | null;
    sending: boolean;
    error: string | null;
    archived: boolean; // true = 从 setState 恢复，后端 session 已失效，下次发送前要重连
}

interface ChatStore {
    sessions: Record<string, SessionState>;
    order: string[];
    activeId: string | null;
    hydrated: boolean;
    setActive: (id: string | null) => void;
    createSession: (profileName?: string) => Promise<string>;
    closeSession: (id: string) => Promise<void>;
    sendMessage: (id: string, text: string) => Promise<void>;
    cancelSend: (id: string) => Promise<void>;
    answerHitl: (id: string, approve: boolean) => Promise<void>;
    renameSession: (id: string, title: string) => void;
    switchProfile: (id: string, profileName: string) => Promise<void>;
    hydrate: () => void;
}

function emptyAssistant(id: string): AssistantMessage & { id: string } {
    return {
        id,
        role: "assistant",
        text: "",
        thinking: "",
        tools: [],
        stop_reason: null,
        usage: null,
        streaming: true,
    };
}

export const useChatStore = create<ChatStore>((set, get) => {
    function cryptoRandomId(): string {
        if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
            return crypto.randomUUID();
        }
        return Math.random().toString(36).slice(2);
    }
    function patchSession(id: string, patch: Partial<SessionState>): void {
        set((s) => {
            const sess = s.sessions[id];
            if (!sess) return s;
            return {
                sessions: { ...s.sessions, [id]: { ...sess, ...patch } },
            };
        });
    }

    return {
        sessions: {},
        order: [],
        activeId: null,
        hydrated: false,
        setActive: (id) => set({ activeId: id }),

        createSession: async (profileName?: string): Promise<string> => {
            const result = await rpcCall<{
                session_id: string;
                profile_name: string | null;
                model: string;
                provider: string;
                mode: string;
            }>("chat.start", profileName ? { profile: profileName } : {});
            const idx = get().order.length + 1;
            const sess: SessionState = {
                session_id: result.session_id,
                title: `会话 ${idx}`,
                profile_name: result.profile_name,
                model: result.model,
                provider: result.provider,
                mode: result.mode,
                messages: [],
                pendingAssistant: null,
                pendingHitl: null,
                sending: false,
                error: null,
                archived: false,
            };
            set((s) => ({
                sessions: { ...s.sessions, [result.session_id]: sess },
                order: [...s.order, result.session_id],
                activeId: result.session_id,
            }));
            return result.session_id;
        },

        closeSession: async (id: string): Promise<void> => {
            try {
                await rpcCall("chat.close", { session_id: id });
            } catch {
                /* 后端可能已经清理 */
            }
            set((s) => {
                const next = { ...s.sessions };
                delete next[id];
                const order = s.order.filter((x) => x !== id);
                const activeId =
                    s.activeId === id
                        ? order[order.length - 1] ?? null
                        : s.activeId;
                return { sessions: next, order, activeId };
            });
        },

        sendMessage: async (id: string, text: string): Promise<void> => {
            let sess = get().sessions[id];
            if (!sess || sess.sending) return;

            // 持久化恢复出来的会话：后端 session_id 已失效，要先重新 chat.start
            // 拿一个新的 id 接上，再把消息历史搬过去。
            let activeId = id;
            if (sess.archived) {
                try {
                    const result = await rpcCall<{
                        session_id: string;
                        profile_name: string | null;
                        model: string;
                        provider: string;
                        mode: string;
                    }>("chat.start", sess.profile_name ? { profile: sess.profile_name } : {});
                    activeId = result.session_id;
                    set((s) => {
                        const old = s.sessions[id];
                        if (!old) return s;
                        const next: SessionState = {
                            ...old,
                            session_id: result.session_id,
                            profile_name: result.profile_name,
                            model: result.model,
                            provider: result.provider,
                            mode: result.mode,
                            archived: false,
                            error: null,
                        };
                        const sessions = { ...s.sessions };
                        delete sessions[id];
                        sessions[result.session_id] = next;
                        const order = s.order.map((x) =>
                            x === id ? result.session_id : x,
                        );
                        const curActive =
                            s.activeId === id ? result.session_id : s.activeId;
                        return { sessions, order, activeId: curActive };
                    });
                    sess = get().sessions[activeId];
                    if (!sess) return;
                } catch (e) {
                    const msg = e instanceof Error ? e.message : String(e);
                    patchSession(id, { error: msg });
                    return;
                }
            }

            const userMsg: ChatMessage = {
                id: cryptoRandomId(),
                role: "user",
                text,
            };
            const assistantId = cryptoRandomId();
            patchSession(activeId, {
                messages: [...sess.messages, userMsg, emptyAssistant(assistantId)],
                pendingAssistant: assistantId,
                sending: true,
                error: null,
            });
            try {
                await rpcCall("chat.send", { session_id: activeId, text });
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                patchSession(activeId, {
                    sending: false,
                    pendingAssistant: null,
                    error: msg,
                });
            }
        },

        cancelSend: async (id: string): Promise<void> => {
            try {
                await rpcCall("chat.cancel", { session_id: id });
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                patchSession(id, { error: msg });
            }
        },

        answerHitl: async (id: string, approve: boolean): Promise<void> => {
            const sess = get().sessions[id];
            if (!sess?.pendingHitl) return;
            try {
                await rpcCall("chat.hitl_response", {
                    session_id: id,
                    request_id: sess.pendingHitl.request_id,
                    approve,
                });
                patchSession(id, { pendingHitl: null });
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                patchSession(id, { error: msg });
            }
        },

        renameSession: (id, title) => patchSession(id, { title }),

        hydrate: (): void => {
            if (get().hydrated) return;
            const saved = loadState<PersistedState>();
            if (!saved || typeof saved !== "object") {
                set({ hydrated: true });
                return;
            }
            try {
                const sessions: Record<string, SessionState> = {};
                const order: string[] = [];
                for (const id of saved.order || []) {
                    const raw = saved.sessions?.[id];
                    if (!raw) continue;
                    sessions[id] = {
                        session_id: id,
                        title: raw.title || "会话",
                        profile_name: raw.profile_name ?? null,
                        model: raw.model || "",
                        provider: raw.provider || "",
                        mode: raw.mode || "chat",
                        messages: (raw.messages || []).map((m: ChatMessage) =>
                            m.role === "assistant"
                                ? {
                                      ...m,
                                      streaming: false,
                                      tools: m.tools || [],
                                  }
                                : m,
                        ),
                        pendingAssistant: null,
                        pendingHitl: null,
                        sending: false,
                        error: null,
                        archived: true,
                    };
                    order.push(id);
                }
                set({
                    sessions,
                    order,
                    activeId:
                        saved.activeId && sessions[saved.activeId]
                            ? saved.activeId
                            : order[order.length - 1] ?? null,
                    hydrated: true,
                });
            } catch {
                set({ hydrated: true });
            }
        },

        switchProfile: async (id: string, profileName: string): Promise<void> => {
            const sess = get().sessions[id];
            if (!sess) return;
            if (sess.sending) return;
            try {
                // 后端无原地切换；做法：close 旧 → start 新 → 替换
                await rpcCall("chat.close", { session_id: id }).catch(() => undefined);
                const result = await rpcCall<{
                    session_id: string;
                    profile_name: string | null;
                    model: string;
                    provider: string;
                    mode: string;
                }>("chat.start", { profile: profileName });
                set((s) => {
                    const old = s.sessions[id];
                    if (!old) return s;
                    const next: SessionState = {
                        ...old,
                        session_id: result.session_id,
                        profile_name: result.profile_name,
                        model: result.model,
                        provider: result.provider,
                        mode: result.mode,
                        messages: [
                            ...old.messages,
                            {
                                id: cryptoRandomId(),
                                role: "user",
                                text: `[已切换到 profile: ${profileName}，新会话开始]`,
                            },
                        ],
                        pendingAssistant: null,
                        pendingHitl: null,
                        sending: false,
                        error: null,
                        archived: false,
                    };
                    const sessions = { ...s.sessions };
                    delete sessions[id];
                    sessions[result.session_id] = next;
                    const order = s.order.map((x) => (x === id ? result.session_id : x));
                    const activeId = s.activeId === id ? result.session_id : s.activeId;
                    return { sessions, order, activeId };
                });
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                patchSession(id, { error: msg });
            }
        },
    };
});

// ============================================================
// 后端 chat.* notification 订阅
// ============================================================

onNotification((method, params) => {
    if (!method.startsWith("chat.")) return;
    const sessionId = params.session_id as string | undefined;
    if (!sessionId) return;
    const state = useChatStore.getState();
    const sess = state.sessions[sessionId];
    if (!sess) return;

    const apply = (patch: Partial<SessionState>): void => {
        useChatStore.setState((s) => ({
            sessions: {
                ...s.sessions,
                [sessionId]: { ...s.sessions[sessionId], ...patch },
            },
        }));
    };
    const patchAssistant = (
        msgId: string | null,
        fn: (m: AssistantMessage & { id: string }) => AssistantMessage & { id: string },
    ): void => {
        if (!msgId) return;
        useChatStore.setState((s) => {
            const cur = s.sessions[sessionId];
            if (!cur) return s;
            return {
                sessions: {
                    ...s.sessions,
                    [sessionId]: {
                        ...cur,
                        messages: cur.messages.map((m) =>
                            m.id === msgId && m.role === "assistant"
                                ? fn(m as AssistantMessage & { id: string })
                                : m,
                        ),
                    },
                },
            };
        });
    };

    switch (method) {
        case "chat.text_delta": {
            const text = String(params.text || "");
            patchAssistant(sess.pendingAssistant, (m) => ({ ...m, text: m.text + text }));
            break;
        }
        case "chat.thinking_delta": {
            const text = String(params.text || "");
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                thinking: m.thinking + text,
            }));
            break;
        }
        case "chat.tool_run_started": {
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                tools: [
                    ...m.tools,
                    {
                        tool_call_id: String(params.tool_call_id || ""),
                        tool_name: String(params.tool_name || ""),
                        args: params.args as Record<string, unknown>,
                        state: "started",
                    },
                ],
            }));
            break;
        }
        case "chat.tool_run_blocked": {
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                tools: m.tools.map((t) =>
                    t.tool_name === params.tool_name && t.state === "started"
                        ? { ...t, state: "blocked", reason: String(params.reason || "") }
                        : t,
                ),
            }));
            break;
        }
        case "chat.tool_run_done": {
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                tools: m.tools.map((t) =>
                    t.tool_name === params.tool_name && t.state === "started"
                        ? {
                              ...t,
                              state: "done",
                              ok: Boolean(params.ok),
                              duration_ms: Number(params.duration_ms ?? 0),
                          }
                        : t,
                ),
            }));
            break;
        }
        case "chat.message_done": {
            const usage = params.usage as
                | { input_tokens: number; output_tokens: number }
                | undefined;
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                stop_reason: String(params.stop_reason || ""),
                usage: usage ?? null,
            }));
            // 注意：conductor 是多轮 tool loop，message_done 只代表本轮 LLM 段
            // 结束（stop=tool_use 时后端还要继续跑工具+下一轮）。真正的 turn
            // 结束信号是 chat.turn_done。这里不能 reset pendingAssistant，否则
            // 后续 tool/delta 事件会被 patchAssistant 的早退判断丢弃。
            break;
        }
        case "chat.turn_done": {
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                streaming: false,
            }));
            apply({ sending: false, pendingAssistant: null });
            break;
        }
        case "chat.error": {
            const msg = String(params.message || "");
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                streaming: false,
                stop_reason: "error",
            }));
            apply({ sending: false, pendingAssistant: null, error: msg });
            break;
        }
        case "chat.cancelled":
        case "chat.turn_cancelled": {
            patchAssistant(sess.pendingAssistant, (m) => ({
                ...m,
                streaming: false,
                stop_reason: "cancelled",
            }));
            apply({ sending: false, pendingAssistant: null });
            break;
        }
        case "chat.hitl_request": {
            apply({
                pendingHitl: {
                    request_id: String(params.request_id || ""),
                    tool: String(params.tool || ""),
                    risk: String(params.risk || ""),
                    args: (params.args as Record<string, unknown>) || {},
                    reason: String(params.reason || ""),
                },
            });
            break;
        }
        default:
            break;
    }
});

// ============================================================
// 持久化：订阅 store 把会话写到 vscode webview state
// ============================================================
//
// vscode.setState 在 webview 销毁时保留，重开 webview 通过 getState 还原。
// 我们只持久化"长期信息"（标题/profile/消息历史），剩下的运行时字段
// （sending / pendingAssistant / pendingHitl / error）都重置。
// 后端 session_id 不持久化语义，我们存当前的 id 仅作为 React key 用，
// 第一次发送时 sendMessage 会因为 archived=true 触发 chat.start 重连。

let persistTimer: ReturnType<typeof setTimeout> | null = null;
useChatStore.subscribe((state) => {
    if (!state.hydrated) return;
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
        const snapshot: PersistedState = {
            sessions: {},
            order: state.order,
            activeId: state.activeId,
        };
        for (const id of state.order) {
            const s = state.sessions[id];
            if (!s) continue;
            snapshot.sessions[id] = {
                title: s.title,
                profile_name: s.profile_name,
                model: s.model,
                provider: s.provider,
                mode: s.mode,
                messages: s.messages.map((m) =>
                    m.role === "assistant"
                        ? { ...m, streaming: false, pendingHitl: null }
                        : m,
                ),
            };
        }
        persistState(snapshot);
    }, 200);
});
