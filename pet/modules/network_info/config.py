# -*- coding: utf-8 -*-
"""「网络信息」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ..base import ModuleConfigSchema

SWITCH_KEY = "network_info_menu_enabled"
SWITCH_OFF_REASON = "已在设置里关闭「网络信息」菜单入口"


def _bool_or_default(value, default: bool) -> bool:
    """与 ``Config._bool_or_default`` 同口径：手改配置里的字符串布尔不得误开。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(default)


def _normalize(data: dict) -> None:
    data[SWITCH_KEY] = _bool_or_default(data.get(SWITCH_KEY), True)


SCHEMA = ModuleConfigSchema(
    defaults={SWITCH_KEY: True},
    normalize=_normalize,
    global_keys=(SWITCH_KEY,),
)

__all__ = ["SCHEMA", "SWITCH_KEY", "SWITCH_OFF_REASON"]
