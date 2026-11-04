# -*- coding: utf-8 -*-
"""模块配置 schema 的汇总入口（Qt-free，主进程与设置进程共用）。

模块清单里的 ``config_schema`` 是字符串入口（``"pkg.mod:SCHEMA"``），这里**惰性**
import 并缓存所有已登记模块的 :class:`~pet.modules.base.ModuleConfigSchema`：

- ``module_defaults()``：模块贡献的出厂默认值（``Config._initial_data`` 合并进来）；
- ``module_keys()``：模块拥有的配置键（``Config.reload`` / ``set`` 的白名单）；
- ``module_global_keys()``：其中属于全局面的键（落主 ``config.json``，不进每宠档案）；
- ``normalize_module_keys(data)``：逐 schema 就地清洗。

一个模块的 schema 加载失败只记日志并跳过——**绝不**因为一个坏模块让配置读不出来。
删除模块 = 删目录 + 删 ``MODULES`` 那一行：缓存重置后它的默认值 / 键 / 菜单动作
一起消失（``reset_cache`` 是测试与热重载用的显式口）。
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from .modules.base import ModuleConfigSchema, load_entry

logger = logging.getLogger(__name__)

_SCHEMAS: tuple[ModuleConfigSchema, ...] | None = None


def reset_cache() -> None:
    """作废 schema 缓存（测试 / 显式热重载后重新读 ``MODULES``）。"""
    global _SCHEMAS
    _SCHEMAS = None


def _schemas() -> tuple[ModuleConfigSchema, ...]:
    global _SCHEMAS
    if _SCHEMAS is not None:
        return _SCHEMAS
    from .modules import MODULES
    from .modules.registry import read_manifest

    schemas: list[ModuleConfigSchema] = []
    for package in MODULES:
        try:
            manifest = read_manifest(package)
        except Exception:
            logger.exception("模块 %s 的清单读取失败，跳过其配置 schema", package)
            continue
        if not manifest.config_schema:
            continue
        try:
            schema = load_entry(manifest.config_schema)
            if not isinstance(schema, ModuleConfigSchema):
                raise TypeError("入口不是 ModuleConfigSchema")
        except Exception:
            logger.exception("模块 %s 的配置 schema 加载失败，跳过", manifest.id)
            continue
        schemas.append(schema)
    _SCHEMAS = tuple(schemas)
    return _SCHEMAS


def module_defaults() -> dict[str, Any]:
    """模块贡献的默认配置（深拷贝；调用方可以随意改）。"""
    result: dict[str, Any] = {}
    for schema in _schemas():
        for key, value in schema.defaults.items():
            result[key] = copy.deepcopy(value)
    return result


def module_keys() -> tuple[str, ...]:
    """模块拥有的全部配置键（登记顺序，去重）。"""
    keys: list[str] = []
    seen: set[str] = set()
    for schema in _schemas():
        for key in schema.defaults:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return tuple(keys)


def module_global_keys() -> frozenset[str]:
    """模块声明为全局面的配置键（每宠档案路由必须把它们留在主配置）。"""
    keys: set[str] = set()
    for schema in _schemas():
        keys.update(schema.global_keys)
    return frozenset(keys)


def normalize_module_keys(data: dict) -> None:
    """按模块 schema 就地清洗配置；单个 schema 失败只记日志，不影响其它模块。"""
    if not isinstance(data, dict):
        return
    for schema in _schemas():
        normalizer = schema.normalize
        if normalizer is None:
            continue
        try:
            normalizer(data)
        except Exception:
            logger.exception("模块配置清洗失败（schema=%r）", schema)


def normalize_reload_keys(data: dict) -> None:
    """``Config.reload`` 专用：只清洗声明 ``normalize_on_reload`` 的模块 schema。

    默认模块保持旧口径（reload 存原值、下次 set/构造再清洗），避免把磁盘上的
    原始值与编辑基线悄悄归一化后让后续保存误判"没有差异"。
    """
    if not isinstance(data, dict):
        return
    for schema in _schemas():
        normalizer = schema.normalize
        if normalizer is None or not schema.normalize_on_reload:
            continue
        try:
            normalizer(data)
        except Exception:
            logger.exception("模块配置 reload 清洗失败（schema=%r）", schema)


__all__ = [
    "module_defaults", "module_global_keys", "module_keys",
    "normalize_module_keys", "normalize_reload_keys", "reset_cache",
]
