"""MCP transport 层抽象。

stdio：spawn 一个 server 子进程，stdin/stdout 走 newline-delimited JSON。
http+sse：远程 server，0.6 暂留接口不实装。

为什么不复用 ipc/framing.py？
- IPC 是 LSP 风格 Content-Length 分帧
- MCP spec 用的是 NDJSON（每行一条 JSON），更轻
- 两套混用会引混乱，分开干净
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol


class McpTransport(Protocol):
    """transport 协议：双向 JSON 消息流。"""

    async def start(self) -> None: ...

    async def send(self, message: dict[str, Any]) -> None: ...

    async def receive(self) -> dict[str, Any] | None:
        """读一条消息。None 表示对端关闭。"""
        ...

    async def close(self) -> None: ...


class StdioTransport:
    """通过子进程的 stdin/stdout 收发 NDJSON。"""

    def __init__(
        self,
        command: str,
        args: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        merged_env = dict(os.environ)
        if self.env:
            merged_env.update(self.env)
        # 防止子进程被父进程的 PYTHONIOENCODING 拖累——MCP server 是 NDJSON，
        # 必须 utf-8 单字节
        merged_env["PYTHONIOENCODING"] = "utf-8"
        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=merged_env,
        )

    async def send(self, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("transport 未启动")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        async with self._write_lock:
            self._proc.stdin.write(line.encode("utf-8"))
            await self._proc.stdin.drain()

    async def receive(self) -> dict[str, Any] | None:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("transport 未启动")
        async with self._read_lock:
            raw = await self._proc.stdout.readline()
        if not raw:
            return None
        text = raw.decode("utf-8").strip()
        if not text:
            return None
        try:
            obj: Any = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"MCP server 发回非法 JSON：{e!r} {text!r}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"MCP 消息根节点必须是 object：{type(obj).__name__}")
        return obj

    async def read_stderr(self) -> bytes:
        """非阻塞读 stderr 残留（出错时给排错）。"""
        if self._proc is None or self._proc.stderr is None:
            return b""
        try:
            chunk = await asyncio.wait_for(self._proc.stderr.read(8192), timeout=0.1)
            return chunk
        except (TimeoutError, BrokenPipeError):
            return b""

    async def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None and not self._proc.stdin.is_closing():
                self._proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()
        self._proc = None


__all__ = ["McpTransport", "StdioTransport"]
