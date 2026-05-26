// 玄玑桌面端 Tauri 入口。
//
// 简化设计：纯外壳，所有逻辑都在 Python 后端跑，前端 webview 直连
// http://127.0.0.1:8765（由 build.beforeDevCommand 自动启 uv run xuanji serve）。
//
// 未来 M4+ 扩展点：
// - 用 #[tauri::command] 暴露原生权限弹窗，与司辰阁 HITLBridge 对接
// - 用 tauri::process 控制后端进程生命周期（显示/隐藏窗口时自动起停）

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("启动玄玑桌面端失败");
}
