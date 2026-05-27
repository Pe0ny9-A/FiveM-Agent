// 多会话聊天状态。
// Session 列表 + 每会话的消息流，订阅后端 chat.* notification。

import { create } from "zustand";
import { onNotification, rpcCall } from "./bridge";

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
}

interface ChatStore {
    sessions: Record<string, SessionState>;
    order: string[];
    activeId: string | null;
    setActive: (id: string | null) => void;
    createSession: (profileName?: string) => Promise<string>;
    closeSession: (id: string) => Promise<void>;
    sendMessage: (id: string, text: string) => Promise<void>;
    cancelSend: (id: string) => Promise<void>;
    answerHitl: (id: string, approve: boolean) => Promise<void>;
    renameSession: (id: string, title: string) => void;
    switchProfile: (id: string, profileName: string) => Promise<void>;
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
            const sess = get().sessions[id];
            if (!sess || sess.sending) return;
            const userMsg: ChatMessage = {
                id: cryptoRandomId(),
                role: "user",
                text,
            };
            const assistantId = cryptoRandomId();
            patchSession(id, {
                messages: [...sess.messages, userMsg, emptyAssistant(assistantId)],
                pendingAssistant: assistantId,
                sending: true,
                error: null,
            });
            try {
                await rpcCall("chat.send", { session_id: id, text });
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                patchSession(id, {
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
                streaming: false,
                stop_reason: String(params.stop_reason || ""),
                usage: usage ?? null,
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
        case "chat.cancelled": {
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
