import { create } from "zustand";
import { onNotification, onWorkspace, persistState, loadState } from "./bridge";

export type TabKey = "chat" | "council" | "profiles" | "skills" | "mcp" | "hooks" | "dashboard";

export interface WorkspaceInfo {
    version: string;
    active_profile: string | null;
    assistant_alias: string;
    user_alias: string;
    workspace_root: string | null;
    is_fivem_resource: boolean;
    framework: string;
    framework_confidence: number;
    inventory: string;
    target: string;
    summary: string;
}

interface AppState {
    activeTab: TabKey;
    setTab: (tab: TabKey) => void;
    workspace: WorkspaceInfo | null;
    setWorkspace: (info: WorkspaceInfo | null) => void;
    backendError: string | null;
    setBackendError: (err: string | null) => void;
}

const persisted = loadState<{ activeTab?: TabKey }>() || {};

export const useAppStore = create<AppState>((set) => ({
    activeTab: persisted.activeTab ?? "chat",
    setTab: (tab) => {
        set({ activeTab: tab });
        persistState({ activeTab: tab });
    },
    workspace: null,
    setWorkspace: (info) => set({ workspace: info }),
    backendError: null,
    setBackendError: (err) => set({ backendError: err }),
}));

// 后端 push 的 workspace 信息→注入 store。host 在初始化和重启时主动推。
onWorkspace((payload) => {
    const info = payload as Partial<WorkspaceInfo>;
    if (info && typeof info === "object") {
        useAppStore.setState({
            workspace: info as WorkspaceInfo,
            backendError: null,
        });
    }
});

// 后端 backend.error 通知（host 加上的虚拟 method）→ 显示成 banner
onNotification((method, params) => {
    if (method === "host.backend_error") {
        useAppStore.setState({
            backendError: String(params.message || "后端错误"),
        });
    } else if (method === "host.backend_ok") {
        useAppStore.setState({ backendError: null });
    }
});
