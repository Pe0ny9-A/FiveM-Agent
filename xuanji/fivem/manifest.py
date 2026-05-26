"""fxmanifest.lua 解析。

策略：正则提取关键字段。FiveM 允许 fxmanifest 用任意 Lua 逻辑，
但实际项目几乎都是声明式：

    fx_version 'cerulean'
    game 'gta5'
    lua54 'yes'

    name 'my-resource'
    description '...'
    author '...'
    version '1.0.0'

    shared_scripts { '@ox_lib/init.lua' }
    client_scripts { 'client/*.lua' }
    server_scripts { 'server/*.lua' }

    dependencies { 'qb-core', 'ox_lib' }
    dependency 'oxmysql'

复杂的 Lua 逻辑解析不到——返回 raw，让玄玑 fallback。
"""

from __future__ import annotations

import re
from pathlib import Path

from xuanji.fivem.models import FxManifest

# 单值字段：fx_version 'X' / game "X"
_SINGLE_VALUE = re.compile(
    r"""^\s*(?P<key>fx_version|game|name|description|author|version|ui_page)\s+
        ['"](?P<val>[^'"]+)['"]\s*$""",
    re.MULTILINE | re.VERBOSE,
)

# lua54 'yes' / lua54 "no"
_LUA54 = re.compile(r"""^\s*lua54\s+['"](?P<val>yes|no|true|false)['"]\s*$""",
                     re.MULTILINE | re.IGNORECASE)

# 块表：scripts/files/dependencies { 'a', "b", ... }
# 多行匹配，允许中间空行 / 注释
_BLOCK = re.compile(
    r"""^\s*(?P<key>client_scripts|server_scripts|shared_scripts|files|dependencies)\s*\{
        (?P<body>.*?)
        \}""",
    re.MULTILINE | re.VERBOSE | re.DOTALL,
)

# 单行 dependency 'X' / dependency "X"
_SINGLE_DEP = re.compile(
    r"""^\s*dependency\s+['"](?P<val>[^'"]+)['"]\s*$""",
    re.MULTILINE,
)

# 块体内逐项：'a' / "a"
_QUOTED_STRING = re.compile(r"""['"]([^'"]+)['"]""")

# Lua 行注释，去掉再正则
_LUA_COMMENT = re.compile(r"--[^\n]*")


def parse_fxmanifest(text: str) -> FxManifest:
    """解析 fxmanifest.lua 文本，返回结构化 FxManifest。"""
    cleaned = _LUA_COMMENT.sub("", text)

    manifest = FxManifest(raw=text)

    # 单值字段
    for match in _SINGLE_VALUE.finditer(cleaned):
        key = match.group("key")
        val = match.group("val")
        if key == "fx_version":
            manifest.fx_version = val
        elif key == "game":
            manifest.game = val
        elif key == "name":
            manifest.name = val
        elif key == "description":
            manifest.description = val
        elif key == "author":
            manifest.author = val
        elif key == "version":
            manifest.version = val
        elif key == "ui_page":
            manifest.ui_page = val

    # lua54
    lua_match = _LUA54.search(cleaned)
    if lua_match:
        manifest.lua54 = lua_match.group("val").lower() in ("yes", "true")

    # 块表
    for match in _BLOCK.finditer(cleaned):
        key = match.group("key")
        body = match.group("body")
        items = _QUOTED_STRING.findall(body)
        if key == "client_scripts":
            manifest.client_scripts = items
        elif key == "server_scripts":
            manifest.server_scripts = items
        elif key == "shared_scripts":
            manifest.shared_scripts = items
        elif key == "files":
            manifest.files = items
        elif key == "dependencies":
            manifest.dependencies = items

    # 单行 dependency
    for match in _SINGLE_DEP.finditer(cleaned):
        dep = match.group("val")
        if dep not in manifest.dependencies:
            manifest.dependencies.append(dep)

    return manifest


def parse_fxmanifest_file(path: Path) -> FxManifest:
    """从文件加载并解析 fxmanifest.lua。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_fxmanifest(text)


__all__ = ["parse_fxmanifest", "parse_fxmanifest_file"]
