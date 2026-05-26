"""加载已 publish 的工厂工具。

`xuanji tool publish <slug>` 把代码复制到 `tool_published_dir()/<slug>.py`。
ServerRuntime 启动时调本模块的 `load_published_tools()`：

1. 扫该目录下所有 `*.py`（除 `__init__.py`）
2. 用 `importlib` 动态加载，命名空间放在 `xuanji.tools.published.<slug>` 下避免污染
3. 在模块里找 `Tool` 子类（必须是顶层 class，无必填 __init__ 参数）
4. 每个发现到的 Tool 类实例化一次，加进列表

容错：单个文件加载失败只警告 + 跳过，不让一个坏工具搞垮整个启动。
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from xuanji.capability.tool import Tool

logger = logging.getLogger(__name__)


def _load_module_from_file(slug: str, path: Path):  # type: ignore[no-untyped-def]
    """单文件 import 到独立 namespace，避免与项目内 import 冲突。"""
    mod_name = f"xuanji.tools.published.{slug}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法构造 spec：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _discover_tools_in_module(module) -> list[type[Tool]]:  # type: ignore[no-untyped-def]
    """找模块里直接定义的 Tool 子类（非 import 进来的）。"""
    found: list[type[Tool]] = []
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, Tool) or obj is Tool:
            continue
        # 只要在本模块里直接定义的（防 from xxx import 拉进来的基类被实例化）
        if obj.__module__ != module.__name__:
            continue
        # 必须有 name 属性才算合格 Tool
        if not getattr(obj, "name", None):
            continue
        found.append(obj)
    return found


def load_published_tools(published_dir: Path) -> list[Tool]:
    """扫 published 目录加载所有工具。返回实例列表。"""
    if not published_dir.exists():
        return []
    tools: list[Tool] = []
    for py_file in sorted(published_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        slug = py_file.stem
        try:
            module = _load_module_from_file(slug, py_file)
        except Exception as e:
            logger.warning("加载已发布工具 %s 失败：%s", slug, e)
            continue
        try:
            tool_classes = _discover_tools_in_module(module)
        except Exception as e:
            logger.warning("发现工具类时出错 %s：%s", slug, e)
            continue
        for cls in tool_classes:
            try:
                instance = cls()
            except TypeError as e:
                logger.warning(
                    "已发布工具 %s 的类 %s 不能无参实例化，跳过：%s",
                    slug, cls.__name__, e,
                )
                continue
            tools.append(instance)
    return tools


__all__ = ["load_published_tools"]
