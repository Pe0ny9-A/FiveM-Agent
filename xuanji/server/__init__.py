"""FastAPI 服务层。

桌面端（Tauri）/ Web 端共享的同一个内核暴露 HTTP/WebSocket。

路由：
- GET  /healthz                  健康检查
- GET  /api/info                 当前 active profile 概览
- GET  /api/profiles             列出 profile（脱敏）
- GET  /api/knowledge/stats      知识库统计
- GET  /api/memory/stats         记忆库统计
- POST /api/knowledge/search     搜索
- POST /api/memory/recall        召回
- WS   /ws/chat                  流式对话（小宝 → 玄玑 ⇄ 工具 → 流式 Delta）

把每条 Delta 用 JSON 文本帧推到 WebSocket，客户端按 type 渲染。

跑：
    uv run xuanji serve --host 127.0.0.1 --port 8765
"""

from core.server.app import create_app
from core.server.runtime import ServerRuntime

__all__ = ["ServerRuntime", "create_app"]
