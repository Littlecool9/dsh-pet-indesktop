# -*- coding: utf-8 -*-
"""「待办提醒」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ..base import ModuleConfigSchema

ENABLED_KEY = "todo_reminder_enabled"
LEAD_KEY = "todo_reminder_lead_minutes"


def _float_or_default(value, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if number != number:  # NaN
        return default
    return max(minimum, min(maximum, number))


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
    data[ENABLED_KEY] = _bool_or_default(data.get(ENABLED_KEY), True)
    data[LEAD_KEY] = int(_float_or_default(data.get(LEAD_KEY), 5.0, 0.0, 60.0))


SCHEMA = ModuleConfigSchema(
    defaults={ENABLED_KEY: True, LEAD_KEY: 5},
    normalize=_normalize,
    global_keys=(ENABLED_KEY, LEAD_KEY),
)

__all__ = ["ENABLED_KEY", "LEAD_KEY", "SCHEMA"]
