/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./webview/**/*.{html,ts,tsx}"],
    theme: {
        extend: {
            colors: {
                vsfg: "var(--vscode-foreground)",
                vsbg: "var(--vscode-editor-background)",
                vspanel: "var(--vscode-panel-background)",
                vsborder: "var(--vscode-panel-border)",
                vsmuted: "var(--vscode-descriptionForeground)",
                vslink: "var(--vscode-textLink-foreground)",
                vsaccent: "var(--vscode-button-background)",
                vsaccentfg: "var(--vscode-button-foreground)",
                vsaccenthov: "var(--vscode-button-hoverBackground)",
                vssec: "var(--vscode-button-secondaryBackground)",
                vssecfg: "var(--vscode-button-secondaryForeground)",
                vswidget: "var(--vscode-editorWidget-background)",
                vsinput: "var(--vscode-input-background)",
                vsinputfg: "var(--vscode-input-foreground)",
                vserror: "var(--vscode-errorForeground)",
                vswarn: "var(--vscode-editorWarning-foreground)",
                vsok: "var(--vscode-charts-green)",
            },
            fontFamily: {
                sans: ["var(--vscode-font-family)"],
                mono: ["var(--vscode-editor-font-family)"],
            },
        },
    },
    plugins: [],
};
