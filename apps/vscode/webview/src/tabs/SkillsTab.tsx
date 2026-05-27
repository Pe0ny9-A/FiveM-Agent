import { useEffect, useState } from "react";
import { rpcCall } from "../bridge";

interface SkillFile {
    name: string;
    description: string;
    triggers: string[];
    tools: string[];
    allowed_tools: string[];
    path: string;
}

interface SkillFileDetail extends SkillFile {
    metadata: Record<string, unknown>;
    body: string;
}

export function SkillsTab(): JSX.Element {
    const [items, setItems] = useState<SkillFile[]>([]);
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [root, setRoot] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [selected, setSelected] = useState<SkillFileDetail | null>(null);

    async function refresh(): Promise<void> {
        try {
            const out = await rpcCall<{
                items: SkillFile[];
                errors: Record<string, string> | string[];
                root: string;
            }>("skills.files.list");
            setItems(out.items);
            setRoot(out.root);
            setErrors(
                Array.isArray(out.errors)
                    ? Object.fromEntries(out.errors.map((e, i) => [String(i), e]))
                    : out.errors,
            );
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    useEffect(() => {
        void refresh();
    }, []);

    async function showSkill(name: string): Promise<void> {
        try {
            const detail = await rpcCall<SkillFileDetail>("skills.files.show", { name });
            setSelected(detail);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }

    return (
        <div className="h-full overflow-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">Skills</h2>
                <button
                    className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                    onClick={() => void refresh()}
                >
                    刷新
                </button>
            </div>
            {root && (
                <div className="text-[11px] text-vsmuted">
                    root: <span className="font-mono">{root}</span>
                </div>
            )}
            {error && <div className="text-[11px] text-vserror">{error}</div>}
            {Object.entries(errors).length > 0 && (
                <div className="border border-vserror rounded p-2">
                    <div className="text-[11px] text-vserror mb-1">解析错误：</div>
                    <ul className="text-[11px] text-vsmuted list-disc pl-4">
                        {Object.entries(errors).map(([k, v]) => (
                            <li key={k}>
                                <span className="font-mono">{k}</span>：{v}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {items.length === 0 ? (
                <div className="text-[11px] text-vsmuted italic">
                    skills 目录还是空的。新增 skill 在 root 下建子目录 + SKILL.md（YAML
                    frontmatter + body）。
                </div>
            ) : (
                <div className="space-y-2">
                    {items.map((s) => (
                        <div
                            key={s.name}
                            className="bg-vswidget border border-vsborder rounded p-2 cursor-pointer hover:border-vslink"
                            onClick={() => void showSkill(s.name)}
                        >
                            <div className="text-xs font-semibold">{s.name}</div>
                            <div className="text-[11px] text-vsmuted">
                                {s.description || <em>无描述</em>}
                            </div>
                            <div className="text-[10px] text-vsmuted mt-1">
                                triggers: {s.triggers.join(", ") || "-"} · tools:{" "}
                                {s.tools.join(", ") || "-"}
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {selected && <SkillModal detail={selected} onClose={() => setSelected(null)} />}
        </div>
    );
}

function SkillModal({
    detail,
    onClose,
}: {
    detail: SkillFileDetail;
    onClose: () => void;
}): JSX.Element {
    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
            <div className="bg-vsbg border border-vsborder rounded p-4 w-[640px] max-w-[90vw] max-h-[80vh] flex flex-col">
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold">{detail.name}</h3>
                    <button
                        onClick={onClose}
                        className="text-[11px] px-2 py-0.5 rounded bg-vssec text-vssecfg"
                    >
                        关闭
                    </button>
                </div>
                <div className="text-[11px] text-vsmuted">
                    path: <span className="font-mono">{detail.path}</span>
                </div>
                <div className="text-[11px] text-vsmuted">
                    triggers: {detail.triggers.join(", ") || "-"} · tools:{" "}
                    {detail.tools.join(", ") || "-"} · allowed:{" "}
                    {detail.allowed_tools.join(", ") || "-"}
                </div>
                <pre className="mt-3 flex-1 overflow-auto bg-vswidget p-2 rounded text-[11px] whitespace-pre-wrap font-mono">
                    {detail.body}
                </pre>
            </div>
        </div>
    );
}
