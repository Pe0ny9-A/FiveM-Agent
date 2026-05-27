import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// webview 资源用相对路径——VS Code 的 asWebviewUri 才能正确解析
export default defineConfig({
    plugins: [react()],
    root: resolve(__dirname, "webview"),
    base: "./",
    build: {
        outDir: resolve(__dirname, "out", "webview"),
        emptyOutDir: true,
        sourcemap: true,
        rollupOptions: {
            input: resolve(__dirname, "webview", "index.html"),
            output: {
                entryFileNames: "assets/[name].js",
                chunkFileNames: "assets/[name].js",
                assetFileNames: "assets/[name][extname]",
            },
        },
    },
});
