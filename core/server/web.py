"""嵌入式 Web 前端 · 单页 HTML 切片。

不引入 Next.js / React 构建链——M3 阶段只用一个原生 HTML/CSS/JS 单页就够：
- WebSocket 接 /ws/chat
- 渲染流式文本、工具事件、HITL 弹窗
- 状态栏显示 active profile + 玄玑/用户称呼
- 这个页通过 GET / 直接返回，桌面端 Tauri 也能直接 serve 它

未来 M4+ 想升级到 React/Vue/Svelte 任意框架，把这个文件换成构建产物即可。
"""

INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>玄玑 · FiveM 智能体</title>
<style>
:root {
  --bg: #0c0a14;
  --panel: #1a1626;
  --border: #2a2440;
  --text: #e9e2f5;
  --muted: #8a82a3;
  --accent: #d8a7ff;
  --accent-2: #7ab6ff;
  --green: #6dd49b;
  --yellow: #f5c87b;
  --red: #ff7e8a;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font-family: ui-sans-serif, "PingFang SC", "Microsoft YaHei", sans-serif;
       height: 100vh; display: flex; flex-direction: column; }
header {
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 14px;
  background: var(--panel);
}
header .title { font-weight: bold; color: var(--accent); }
header .meta { color: var(--muted); font-size: 13px; }
header .status { margin-left: auto; font-size: 12px; color: var(--muted); }
header .status .dot { display: inline-block; width: 8px; height: 8px;
                      border-radius: 50%; background: var(--muted); margin-right: 4px; }
header .status.connected .dot { background: var(--green); }
header .status.error .dot { background: var(--red); }

main { flex: 1; overflow: auto; padding: 16px 18px; }
.bubble { margin: 12px 0; max-width: 88%; padding: 10px 14px;
          border-radius: 10px; line-height: 1.55; white-space: pre-wrap;
          word-break: break-word; }
.bubble.user { background: #1f2740; margin-left: auto; }
.bubble.assistant { background: var(--panel); border: 1px solid var(--border); }
.bubble .who { font-size: 11px; color: var(--muted); margin-bottom: 4px; }

.tool-event { margin: 6px 0; padding: 6px 10px; font-size: 13px;
              border-left: 3px solid var(--accent-2); color: var(--muted);
              background: #161324; border-radius: 4px; }
.tool-event.ok { border-left-color: var(--green); }
.tool-event.err { border-left-color: var(--red); color: var(--red); }
.tool-event.blocked { border-left-color: var(--yellow); color: var(--yellow); }
.tool-event code { color: var(--text); }

.hitl {
  margin: 10px 0; padding: 14px; border: 1px solid var(--yellow);
  border-radius: 8px; background: #2a230d;
}
.hitl h4 { margin: 0 0 6px; color: var(--yellow); font-size: 14px; }
.hitl pre { margin: 6px 0; padding: 8px; background: #1a1407;
            font-size: 12px; overflow-x: auto; }
.hitl button { padding: 6px 14px; border-radius: 4px; border: 0;
                cursor: pointer; margin-right: 8px; font-size: 13px; }
.hitl button.allow { background: var(--green); color: #07140d; }
.hitl button.deny { background: var(--red); color: #1a0508; }

footer {
  padding: 10px 16px; border-top: 1px solid var(--border);
  background: var(--panel);
  display: flex; gap: 10px;
}
footer textarea {
  flex: 1; min-height: 40px; max-height: 200px; resize: vertical;
  background: #14121e; border: 1px solid var(--border); color: var(--text);
  padding: 8px 12px; border-radius: 6px; font-family: inherit; font-size: 14px;
}
footer button {
  padding: 8px 18px; background: var(--accent); color: #1a0a26;
  border: 0; border-radius: 6px; font-weight: 600; cursor: pointer;
}
footer button:disabled { opacity: 0.5; cursor: not-allowed; }
.usage { font-size: 11px; color: var(--muted); text-align: right; padding: 0 10px; }
</style>
</head>
<body>
<header>
  <span class="title">玄玑</span>
  <span class="meta" id="meta">加载中…</span>
  <span class="status" id="status"><span class="dot"></span><span id="status-text">未连接</span></span>
</header>
<main id="main"></main>
<div class="usage" id="usage"></div>
<footer>
  <textarea id="input" placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"></textarea>
  <button id="send" disabled>发送</button>
</footer>

<script>
const $ = (id) => document.getElementById(id);
const main = $("main");
const input = $("input");
const sendBtn = $("send");
const statusEl = $("status");
const statusText = $("status-text");
const metaEl = $("meta");
const usageEl = $("usage");

let assistantAlias = "玄玑";
let userAlias = "用户";
let currentBubble = null;
let ws = null;

async function loadInfo() {
  try {
    const r = await fetch("/api/info");
    const info = await r.json();
    if (info.assistant_alias) assistantAlias = info.assistant_alias;
    if (info.user_alias) userAlias = info.user_alias;
    metaEl.textContent = info.active_profile
      ? `${info.active_profile} · ${info.active.kind} · ${info.active.default_model}`
      : "未激活 profile";
  } catch (e) {
    metaEl.textContent = "服务未连接";
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/chat`);
  ws.onopen = () => {
    statusEl.className = "status connected";
    statusText.textContent = "已连接";
    sendBtn.disabled = false;
  };
  ws.onclose = () => {
    statusEl.className = "status";
    statusText.textContent = "已断开";
    sendBtn.disabled = true;
  };
  ws.onerror = () => {
    statusEl.className = "status error";
    statusText.textContent = "连接异常";
  };
  ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
}

function appendBubble(who, text="") {
  const div = document.createElement("div");
  div.className = `bubble ${who === userAlias ? "user" : "assistant"}`;
  const w = document.createElement("div");
  w.className = "who";
  w.textContent = who;
  const c = document.createElement("div");
  c.className = "content";
  c.textContent = text;
  div.appendChild(w);
  div.appendChild(c);
  main.appendChild(div);
  main.scrollTop = main.scrollHeight;
  return c;
}

function appendToolEvent(text, kind="") {
  const div = document.createElement("div");
  div.className = `tool-event ${kind}`;
  div.innerHTML = text;
  main.appendChild(div);
  main.scrollTop = main.scrollHeight;
}

function appendHITL(req) {
  const div = document.createElement("div");
  div.className = "hitl";
  div.innerHTML = `
    <h4>司辰阁拦截 · 待确认（risk=${req.risk}）</h4>
    <div>工具：<code>${req.tool}</code></div>
    <div>原因：${req.reason}</div>
    <pre>${escapeHtml(JSON.stringify(req.args, null, 2))}</pre>
    <button class="allow">放行</button>
    <button class="deny">拒绝</button>
  `;
  main.appendChild(div);
  main.scrollTop = main.scrollHeight;
  div.querySelector(".allow").onclick = () => respondHITL(req.request_id, true, div);
  div.querySelector(".deny").onclick = () => respondHITL(req.request_id, false, div);
}

function respondHITL(request_id, approve, el) {
  ws.send(JSON.stringify({type: "hitl_response", request_id, approve}));
  el.style.opacity = "0.5";
  el.querySelectorAll("button").forEach(b => b.disabled = true);
  el.querySelector("h4").textContent = `司辰阁 · ${approve ? "已放行" : "已拒绝"}`;
}

function escapeHtml(s) {
  return s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}

function handleEvent(msg) {
  switch (msg.type) {
    case "session_started":
      assistantAlias = msg.assistant_alias || assistantAlias;
      userAlias = msg.user_alias || userAlias;
      appendToolEvent(`会话开始 · model=${msg.model}`);
      break;
    case "text_delta":
      if (!currentBubble) currentBubble = appendBubble(assistantAlias);
      currentBubble.textContent += msg.text;
      main.scrollTop = main.scrollHeight;
      break;
    case "tool_run_started": {
      const args = msg.args ? Object.entries(msg.args)
        .map(([k,v]) => `${k}=${typeof v==="string"?JSON.stringify(v):v}`).join(", ") : "";
      appendToolEvent(`→ <code>${msg.tool_name}</code>(${args})`);
      currentBubble = null;
      break;
    }
    case "tool_run_blocked":
      appendToolEvent(`× <code>${msg.tool_name}</code> 被拦截：${msg.reason}`, "blocked");
      break;
    case "tool_run_done":
      appendToolEvent(
        msg.ok
          ? `✓ <code>${msg.tool_name}</code> 完成 · ${msg.duration_ms}ms`
          : `× <code>${msg.tool_name}</code> 失败：${msg.error}`,
        msg.ok ? "ok" : "err",
      );
      break;
    case "message_done":
      currentBubble = null;
      if (msg.usage) {
        usageEl.textContent = `usage: in=${msg.usage.input_tokens} out=${msg.usage.output_tokens}`;
      }
      break;
    case "hitl_request":
      appendHITL(msg);
      break;
    case "error":
      appendToolEvent(`! ${msg.message}`, "err");
      break;
  }
}

function send() {
  const text = input.value.trim();
  if (!text || ws?.readyState !== 1) return;
  appendBubble(userAlias, text);
  ws.send(JSON.stringify({type: "user_input", text}));
  input.value = "";
  currentBubble = null;
}

sendBtn.onclick = send;
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

loadInfo();
connect();
</script>
</body>
</html>
"""

__all__ = ["INDEX_HTML"]
