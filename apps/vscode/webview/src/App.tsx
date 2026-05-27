import { useEffect } from "react";
import { useAppStore, TabKey } from "./store";
import { rpcCall, postCommand } from "./bridge";
import { ChatTab } from "./tabs/ChatTab";
import { CouncilTab } from "./tabs/CouncilTab";
import { ProfilesTab } from "./tabs/ProfilesTab";
import { SkillsTab } from "./tabs/SkillsTab";
import { McpTab } from "./tabs/McpTab";
import { HooksTab } from "./tabs/HooksTab";
import { DashboardTab } from "./tabs/DashboardTab";

const TABS: { key: TabKey; label: string }[] = [
    { key: "chat", label: "对话" },
    { key: "council", label: "群英会" },
    { key: "profiles", label: "Profiles" },
    { key: "skills", label: "Skills" },
    { key: "mcp", label: "MCP" },
    { key: "hooks", label: "Hooks" },
    { key: "dashboard", label: "仪表盘" },
];

export function App(): JSX.Element {
    const activeTab = useAppStore((s) => s.activeTab);
    const setTab = useAppStore((s) => s.setTab);
    const workspace = useAppStore((s) => s.workspace);
    const backendError = useAppStore((s) => s.backendError);
    const setWorkspace = useAppStore((s) => s.setWorkspace);

    // 初次 mount 主动拉一次 workspace 信息（即使 host 还没推过）
    useEffect(() => {
        let cancelled = false;
        rpcCall<{
            version: string;
            active_profile: string | null;
            assistant_alias: string;
            user_alias: string;
            project: {
                root: string;
                is_fivem_resource: boolean;
                framework: string;
                framework_confidence: number;
                inventory: string;
                target: string;
                summary: string;
            };
        }>("info")
            .then((info) => {
                if (cancelled) return;
                setWorkspace({
                    version: info.version,
                    active_profile: info.active_profile,
                    assistant_alias: info.assistant_alias,
                    user_alias: info.user_alias,
                    workspace_root: info.project.root,
                    is_fivem_resource: info.project.is_fivem_resource,
                    framework: info.project.framework,
                    framework_confidence: info.project.framework_confidence,
                    inventory: info.project.inventory,
                    target: info.project.target,
                    summary: info.project.summary,
                });
            })
            .catch(() => {
                /* host 没准备好；workspace push 会兜底 */
            });
        return () => {
            cancelled = true;
        };
    }, [setWorkspace]);

    return (
        <div className="flex flex-col h-full">
            <Header workspace={workspace} backendError={backendError} />
            <nav className="flex border-b border-vsborder bg-vspanel px-2">
                {TABS.map((t) => (
                    <button
                        key={t.key}
                        className={
                            "px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors " +
                            (activeTab === t.key
                                ? "border-vslink text-vsfg"
                                : "border-transparent text-vsmuted hover:text-vsfg")
                        }
                        onClick={() => setTab(t.key)}
                    >
                        {t.label}
                    </button>
                ))}
            </nav>
            <main className="flex-1 overflow-hidden">
                {activeTab === "chat" && <ChatTab />}
                {activeTab === "council" && <CouncilTab />}
                {activeTab === "profiles" && <ProfilesTab />}
                {activeTab === "skills" && <SkillsTab />}
                {activeTab === "mcp" && <McpTab />}
                {activeTab === "hooks" && <HooksTab />}
                {activeTab === "dashboard" && <DashboardTab />}
            </main>
        </div>
    );
}

function Header({
    workspace,
    backendError,
}: {
    workspace: ReturnType<typeof useAppStore.getState>["workspace"];
    backendError: string | null;
}): JSX.Element {
    const fw = workspace?.framework || "未识别";
    const fwLabel = (() => {
        switch (fw) {
            case "qbcore":
                return "QBCore";
            case "qbox":
                return "QBox";
            case "esx":
                return "ESX";
            case "standalone":
                return "Standalone";
            case "unknown":
                return "未识别";
            default:
                return fw;
        }
    })();
    return (
        <header className="px-3 py-2 border-b border-vsborder bg-vspanel flex items-center gap-3">
            <div className="flex flex-col leading-tight">
                <div className="text-xs">
                    <span className="text-vsfg font-semibold">玄玑</span>
                    <span className="text-vsmuted ml-1">
                        v{workspace?.version || "?"}
                    </span>
                </div>
                <div className="text-[11px] text-vsmuted">
                    {workspace?.active_profile ? (
                        <span>profile: {workspace.active_profile}</span>
                    ) : (
                        <span className="text-vswarn">未配置 profile</span>
                    )}
                </div>
            </div>
            <div className="flex-1 text-[11px] text-vsmuted truncate">
                {workspace?.is_fivem_resource ? (
                    <>
                        <span className="text-vsfg">{fwLabel}</span>
                        <span className="mx-1">/</span>
                        <span>{workspace.inventory}</span>
                        <span className="mx-1">/</span>
                        <span>{workspace.target}</span>
                    </>
                ) : (
                    <span>当前不是 FiveM resource</span>
                )}
            </div>
            <button
                title="重启后端"
                className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg hover:opacity-90"
                onClick={() => postCommand("xuanji.restartBackend")}
            >
                重启
            </button>
            {backendError && (
                <span className="text-[11px] text-vserror truncate max-w-xs">
                    {backendError}
                </span>
            )}
        </header>
    );
}
