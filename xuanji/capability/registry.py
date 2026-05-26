"""工具注册器。"""

from __future__ import annotations

from collections.abc import Iterable

from xuanji.capability.tool import Tool


class ToolRegistry:
    """名字 → Tool 实例的注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具 {tool.name!r} 已注册")
        self._tools[tool.name] = tool

    def register_all(self, tools: Iterable[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
