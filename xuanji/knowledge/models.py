"""知识库数据模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 源 namespace 命名规范：fivem.qbcore@1.x / fivem.ox_lib@3.x / fivem.natives@latest
# user.<project>@<ver> 留给用户私有项目文档
Namespace = str


class Source(BaseModel):
    """知识来源。一个 Source 内可以有多份 Chunk + Symbol。"""

    namespace: Namespace
    title: str
    url: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """文本切片，全文检索的最小单位。"""

    id: str  # 形如 'fivem.qbcore@1.x:functions/createuseableitem#0'
    namespace: Namespace
    source_title: str
    section: str | None = None  # 可选的小节标题
    text: str
    url: str | None = None


class Symbol(BaseModel):
    """API / 事件 / native 的结构化卡片。

    精准查询锚点。例如 `QBCore.Functions.CreateUseableItem` 命中 Symbol，
    再以该 symbol 为锚拉相关 chunk，避免纯模糊检索的语义漂移。
    """

    id: str  # 形如 'fivem.qbcore@1.x::QBCore.Functions.CreateUseableItem'
    namespace: Namespace
    name: str  # 完整限定名 QBCore.Functions.CreateUseableItem
    kind: Literal["function", "event", "export", "native", "module"]
    side: Literal["client", "server", "shared", "any"] = "any"
    signature: str | None = None  # 'CreateUseableItem(item, cb)'
    summary: str = ""
    params: list[dict[str, Any]] = Field(default_factory=list)
    returns: str | None = None
    example: str | None = None
    url: str | None = None
