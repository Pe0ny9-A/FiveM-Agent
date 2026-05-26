"""把 MCP 工具收编成百工坊 Tool。

适配规则：
- name: `mcp:<server_name>:<tool_name>`，避免与本地工具撞名
- description: 直接用 server 给的描述，前面加上 server 标签
- schema: 直接用 inputSchema（spec 要求 JSON Schema Draft 7）
- risk: 默认 NET（外部进程，未必只读），首次调用走 HITL 加白名单
- execute: 调 client.call_tool，把结果展平成字符串
"""

from __future__ import annotations

import time
from typing import Any

from xuanji.capability.tool import RiskTag, Tool, ToolCtx, ToolResult
from xuanji.mcp.client import McpClient, McpClientError
from xuanji.mcp.protocol import McpToolDef


class McpToolAdapter(Tool):
    """单个 MCP server 工具的运行时包装。

    实例化后即满足百工坊 Tool 协议，可直接 ToolRegistry.register。
    """

    # 父类 Tool 把 name/description/schema/risk 声明为 ClassVar，但 MCP 适配器
    # 必须按运行期发现的 server+tool 元数据动态填——这里把它们改成实例属性，
    # ToolRegistry 读 instance.name 而不是 type.name，所以行为正确，只是 mypy
    # 看到对 ClassVar 的实例赋值会报错，每行 type: ignore 关掉。
    def __init__(
        self,
        *,
        client: McpClient,
        server_name: str,
        tool_def: McpToolDef,
        risk: RiskTag = RiskTag.NET,
    ) -> None:
        self.name = f"mcp:{server_name}:{tool_def.name}"  # type: ignore[misc]
        self.description = (  # type: ignore[misc]
            f"[MCP·{server_name}] {tool_def.description}".strip()
            if tool_def.description
            else f"[MCP·{server_name}] {tool_def.name}"
        )
        self.schema = tool_def.inputSchema or {  # type: ignore[misc]
            "type": "object", "properties": {},
        }
        self.risk = risk  # type: ignore[misc]
        self._client = client
        self._server_name = server_name
        self._original_name = tool_def.name

    async def execute(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        start = time.monotonic()
        try:
            mcp_result = await self._client.call_tool(self._original_name, args)
        except McpClientError as e:
            return ToolResult(
                ok=False,
                error=f"MCP 调用失败：{e}",
                duration_ms=int((time.monotonic() - start) * 1000),
                extra={"server": self._server_name, "code": e.code},
            )
        text = McpClient.flatten_content(mcp_result.content)
        duration = int((time.monotonic() - start) * 1000)
        if mcp_result.isError:
            return ToolResult(
                ok=False,
                error=text or "MCP server 返回 isError=True",
                duration_ms=duration,
                extra={"server": self._server_name},
            )
        return ToolResult(
            ok=True,
            output=text,
            duration_ms=duration,
            extra={"server": self._server_name},
        )


__all__ = ["McpToolAdapter"]
