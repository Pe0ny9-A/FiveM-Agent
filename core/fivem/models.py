"""FiveM 数据模型。

Framework / InventoryKind / TargetKind 为 StrEnum，便于 system prompt 注入与 schema 匹配。
FxManifest 是 fxmanifest.lua 的结构化呈现；FiveMContext 是 detector 综合判断后的"项目身份卡"。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Framework(StrEnum):
    """FiveM 主流 framework。"""

    QBCORE = "qbcore"
    QBOX = "qbox"
    ESX = "esx"
    STANDALONE = "standalone"  # 不依赖 framework 的纯插件
    UNKNOWN = "unknown"


class InventoryKind(StrEnum):
    """物品系统选择——影响"加可使用物品"的 API。"""

    OX_INVENTORY = "ox_inventory"
    QB_INVENTORY = "qb-inventory"
    ESX_INVENTORY = "esx_inventory"
    QS_INVENTORY = "qs-inventory"
    DEFAULT = "default"  # 用 framework 自带
    UNKNOWN = "unknown"


class TargetKind(StrEnum):
    """交互系统选择——影响"和 NPC 搭话"的 API。"""

    OX_TARGET = "ox_target"
    QB_TARGET = "qb-target"
    INTERACT = "interact"  # 第三方
    NONE = "none"
    UNKNOWN = "unknown"


class FxManifest(BaseModel):
    """fxmanifest.lua 的结构化解析结果。

    只解析关键字段——FiveM 的 fxmanifest 是 Lua 脚本，理论上能写任意逻辑，
    但实际项目 99% 都是声明式赋值。失败字段保持默认值，不抛错。
    """

    fx_version: str | None = None
    game: str | None = None
    name: str | None = None
    description: str | None = None
    author: str | None = None
    version: str | None = None
    lua54: bool = False

    client_scripts: list[str] = Field(default_factory=list)
    server_scripts: list[str] = Field(default_factory=list)
    shared_scripts: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    ui_page: str | None = None

    dependencies: list[str] = Field(default_factory=list)
    """声明式依赖。`dependency 'qb-core'` 与 `dependencies { 'qb-core', ... }` 都收到这里。"""

    raw: str = ""
    """原始文件内容，留给玄玑做 fallback 解析。"""


class FiveMContext(BaseModel):
    """项目身份卡——detector 给 system prompt 与 scaffold 的统一输入。"""

    is_fivem_resource: bool = False
    """当前目录是否是 FiveM resource（即含 fxmanifest.lua）。
    若是 server bundle 根目录则为 False（但 detected_resources 不空）。"""

    project_root: Path
    fxmanifest_path: Path | None = None
    manifest: FxManifest | None = None

    framework: Framework = Framework.UNKNOWN
    framework_confidence: float = 0.0
    """0~1。0.5 以下表示推断不可靠，玄玑应主动询问小宝。"""

    inventory: InventoryKind = InventoryKind.UNKNOWN
    target: TargetKind = TargetKind.UNKNOWN

    detected_resources: list[Path] = Field(default_factory=list)
    """如果 cwd 是 server bundle 根目录（resources/[xxx]/yyy 结构），列出能 detect 到的子 resource。"""

    notes: list[str] = Field(default_factory=list)
    """detector 在判断过程中的说明，会注入 system prompt 让玄玑知道为什么这么判。"""
