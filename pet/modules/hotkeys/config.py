# -*- coding: utf-8 -*-
"""「全局快捷键」模块配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ... import hotkey_actions, hotkey_spec
from ..base import ModuleConfigSchema

#: 空串 = 未绑定。三个键是进程级（全局）配置，不进每宠档案。
DEFAULTS = {key: "" for key in hotkey_actions.ACTIONS.values()}


def _normalize(data: dict) -> None:
    # 与设置页/Config 同口径：把用户或手改配置收成规范写法，脏值一律清空。
    for key in DEFAULTS:
        data[key] = hotkey_spec.normalize(data.get(key))


SCHEMA = ModuleConfigSchema(
    defaults=DEFAULTS,
    normalize=_normalize,
    global_keys=tuple(DEFAULTS),
)

__all__ = ["DEFAULTS", "SCHEMA"]
