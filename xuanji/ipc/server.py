"""stdio JSON-RPC 主循环。

设计要点：
- 同步读 → asyncio 派发 → 同步写。读写在 executor 里跑，不阻塞 event loop。
- 请求（有 id）→ 必须回响应；通知（无 id）→ 不回，仅记录。
- 异常一律转 JSON-RPC 错误对象，不让 server 因单条消息崩掉。
- shutdown 通知或 stdin EOF → 干净退出。

不做的事：
- 不做服务端推流（VS Code 端 P1 阶段不需要 LSP $/progress；P2 再加）
- 不做并发请求（单 client 单线程，串行处理足够；并发以后用 asyncio.gather 打开）
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from typing import Any, BinaryIO

from xuanji.ipc.dispatcher import RpcMethod, dispatch
from xuanji.ipc.errors import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PARSE_ERROR,
    RpcError,
)
from xuanji.ipc.framing import read_message, write_message


def _err_response(
    request_id: Any,
    code: int,
    message: str,
    data: object | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def _ok_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def _handle_one(
    methods: dict[str, RpcMethod],
    msg: dict[str, Any],
    log: BinaryIO,
) -> dict[str, Any] | None:
    """处理一条消息。返回响应或 None（通知不回）。"""
    request_id = msg.get("id")
    is_notification = "id" not in msg

    if msg.get("jsonrpc") != "2.0":
        if is_notification:
            return None
        return _err_response(request_id, INVALID_REQUEST, "jsonrpc 字段必须是 '2.0'")

    method = msg.get("method")
    if not isinstance(method, str):
        if is_notification:
            return None
        return _err_response(request_id, INVALID_REQUEST, "缺少 method 字段")

    params = msg.get("params") or {}
    if not isinstance(params, dict):
        if is_notification:
            return None
        return _err_response(request_id, INVALID_REQUEST, "params 必须是 object")

    try:
        result = await dispatch(methods, method, params)
    except RpcError as e:
        if is_notification:
            return None
        return _err_response(request_id, e.code, e.message, e.data)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.write(
            f"[ipc] 未捕获异常 method={method}: {e}\n{traceback.format_exc()}\n".encode(
                "utf-8", errors="replace",
            ),
        )
        log.flush()
        if is_notification:
            return None
        return _err_response(
            request_id, INTERNAL_ERROR, f"{type(e).__name__}: {e}",
        )

    if is_notification:
        return None
    return _ok_response(request_id, result)


async def run_stdio_server(
    methods: dict[str, RpcMethod],
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    stderr: BinaryIO | None = None,
) -> None:
    """跑主循环——直到 stdin EOF 或收到 shutdown 通知。"""
    in_stream = stdin or sys.stdin.buffer
    out_stream = stdout or sys.stdout.buffer
    err_stream = stderr or sys.stderr.buffer

    err_stream.write(b"[ipc] xuanji stdio server ready\n")
    err_stream.flush()

    while True:
        try:
            msg = await read_message(in_stream)
        except ValueError as e:
            err_stream.write(f"[ipc] 分帧错误：{e}\n".encode("utf-8", errors="replace"))
            err_stream.flush()
            await write_message(
                _err_response(None, PARSE_ERROR, f"frame: {e}"),
                out_stream,
            )
            continue
        except (OSError, EOFError):
            break

        if msg is None:
            break

        if msg.get("method") == "shutdown":
            request_id = msg.get("id")
            if request_id is not None:
                await write_message(_ok_response(request_id, {"ok": True}), out_stream)
            break

        response = await _handle_one(methods, msg, err_stream)
        if response is not None:
            try:
                await write_message(response, out_stream)
            except (OSError, BrokenPipeError):
                break


__all__ = ["run_stdio_server"]
