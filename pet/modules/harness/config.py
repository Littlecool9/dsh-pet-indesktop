# -*- coding: utf-8 -*-
"""「DeepSeek Harness」模块配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ..base import ModuleConfigSchema

AUTOSTART_KEY = "harness_autostart"
TARGET_KEY = "harness_launch_target"
LAUNCH_TARGETS = ("auto", "service", "web", "desktop")


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
    data[AUTOSTART_KEY] = _bool_or_default(data.get(AUTOSTART_KEY), False)
    target = str(data.get(TARGET_KEY) or "auto").strip().lower()
    data[TARGET_KEY] = target if target in LAUNCH_TARGETS else "auto"


SCHEMA = ModuleConfigSchema(
    defaults={AUTOSTART_KEY: False, TARGET_KEY: "auto"},
    normalize=_normalize,
    global_keys=(AUTOSTART_KEY, TARGET_KEY),
)

__all__ = ["AUTOSTART_KEY", "LAUNCH_TARGETS", "SCHEMA", "TARGET_KEY"]
