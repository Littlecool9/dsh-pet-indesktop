# -*- coding: utf-8 -*-
"""「专注模式」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。

``focus_mode`` 仍是全局配置（落主 ``config.json``，键名/路由不变），默认值与
清洗随功能一起搬进模块：删掉模块 = 删目录 + 删 ``MODULES`` 那一行。
"""
from __future__ import annotations

from ..base import ModuleConfigSchema
from .session import normalize_focus_config

KEY = "focus_mode"


def _normalize(data: dict) -> None:
    data[KEY] = normalize_focus_config(data.get(KEY))


SCHEMA = ModuleConfigSchema(
    defaults={KEY: normalize_focus_config(None)},
    normalize=_normalize,
    global_keys=(KEY,),
)

__all__ = ["KEY", "SCHEMA"]
