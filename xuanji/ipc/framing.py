"""LSP 风格的消息分帧。

Content-Length 头 + 空行 + JSON body，全程 utf-8。
read_message 是 async（await loop.run_in_executor 包装阻塞 readline）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, BinaryIO


def read_message_sync(stream: BinaryIO) -> dict[str, Any] | None:
    """同步读一个 LSP 风格消息。返回 None 表示对端关流。"""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, _, value = decoded.partition(":")
            headers[key.strip().lower()] = value.strip()
    length_str = headers.get("content-length")
    if not length_str:
        raise ValueError(f"缺少 Content-Length 头：{headers!r}")
    try:
        length = int(length_str)
    except ValueError as e:
        raise ValueError(f"非法 Content-Length：{length_str!r}") from e
    if length < 0 or length > 16 * 1024 * 1024:  # 16MB 上限防爆
        raise ValueError(f"Content-Length 越界：{length}")
    body = stream.read(length)
    if len(body) != length:
        raise ValueError(f"消息体不完整：期望 {length}，得到 {len(body)}")
    text = body.decode("utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"消息根节点必须是 object：{type(obj).__name__}")
    return obj


def write_message_sync(stream: BinaryIO, message: dict[str, Any]) -> None:
    """同步写一个 LSP 风格消息。"""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(header)
    stream.write(body)
    stream.flush()


async def read_message(stream: BinaryIO | None = None) -> dict[str, Any] | None:
    """异步读消息，run_in_executor 包阻塞 IO。"""
    s = stream or sys.stdin.buffer
    return await asyncio.get_event_loop().run_in_executor(
        None, read_message_sync, s,
    )


async def write_message(
    message: dict[str, Any],
    stream: BinaryIO | None = None,
) -> None:
    s = stream or sys.stdout.buffer
    await asyncio.get_event_loop().run_in_executor(
        None, write_message_sync, s, message,
    )


__all__ = [
    "read_message",
    "read_message_sync",
    "write_message",
    "write_message_sync",
]
