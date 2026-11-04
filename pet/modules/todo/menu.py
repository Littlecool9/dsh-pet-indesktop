# -*- coding: utf-8 -*-
"""「待办提醒」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action

MODULE_ID = "todo_panel"
LABEL = "待办提醒"
ICON = "todo"
UNRUNNING_REASON = "待办提醒模块未运行"


def _host_reachable(pet) -> bool:
    return callable(getattr(pet, "running_module", None))


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


def _available(pet) -> bool:
    return _host_reachable(pet)


def _enabled(pet) -> bool:
    return _running_module(pet) is not None


def _disabled_reason(pet=None) -> str:
    return _unavailable_reason(pet) if pet is not None else UNRUNNING_REASON


def _build(menu, pet):
    module = _running_module(pet)
    callback = module.open_panel if module is not None else (lambda: None)
    action = add_action(menu, LABEL, ICON, callback, close_on_trigger=True)
    if not _enabled(pet):
        action.setEnabled(False)
        action.setToolTip(_disabled_reason(pet))
    return action


def actions() -> dict[str, MenuActionSpec]:
    return {
        MODULE_ID: MenuActionSpec(
            _build,
            available=_available,
            enabled=_enabled,
            disabled_reason=_disabled_reason,
            label=LABEL,
            icon=ICON,
        ),
    }


__all__ = ["actions"]
