# -*- coding: utf-8 -*-
"""「专注模式」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action

MODULE_ID = "focus"
ACTION_ID = "focus_mode"
LABEL = "专注模式"
ICON = "pause"
UNRUNNING_REASON = "专注模块未运行"


def _running_module(pet):
    getter = getattr(pet, "running_module", None)
    if not callable(getter):
        return None
    try:
        return getter(MODULE_ID)
    except Exception:
        return None


def _unavailable_reason(pet) -> str:
    getter = getattr(pet, "module_unavailable_reason", None)
    if not callable(getter):
        return UNRUNNING_REASON
    try:
        return str(getter(MODULE_ID) or "") or UNRUNNING_REASON
    except Exception:
        return UNRUNNING_REASON


def _disabled_reason(pet=None) -> str:
    if pet is None:
        return UNRUNNING_REASON
    if _running_module(pet) is None:
        return _unavailable_reason(pet)
    return ""


def _enabled(pet) -> bool:
    return _running_module(pet) is not None


def _build(menu, pet):
    module = _running_module(pet)
    if module is None:
        action = add_action(menu, LABEL, ICON, lambda: None, close_on_trigger=True)
        action.setEnabled(False)
        action.setToolTip(_disabled_reason(pet))
        return action
    return module.build_menu(menu, pet)


def actions() -> dict[str, MenuActionSpec]:
    return {
        ACTION_ID: MenuActionSpec(
            _build,
            enabled=_enabled,
            disabled_reason=_disabled_reason,
            label=LABEL,
            icon=ICON,
        ),
    }


__all__ = ["actions"]
