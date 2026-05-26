"""同进程沙箱：直接 await Tool.execute，加超时与异常归一化。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.capability.tool import Tool, ToolCtx, ToolError, ToolResult


class InProcSandbox:
    """同进程执行。最轻量，零隔离——只对 SAFE / IO 类工具使用。"""

    async def run(
        self,
        tool: Tool,
        args: dict[str, Any],
        ctx: ToolCtx,
        *,
        timeout_sec: float = 30.0,
    ) -> ToolResult:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(tool.execute(args, ctx), timeout=timeout_sec)
        except TimeoutError:
            return ToolResult(
                ok=False,
                error=f"工具执行超时（{timeout_sec}s）",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except ToolError as e:
            return ToolResult(
                ok=False,
                error=str(e),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        if result.duration_ms == 0:
            result.duration_ms = duration_ms
        return result
