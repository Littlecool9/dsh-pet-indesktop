# -*- coding: utf-8 -*-
"""「网络信息」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action
from .config import SWITCH_KEY, SWITCH_OFF_REASON

MODULE_ID = "network_info"
LABEL = "网络信息"
ICON = "web"
UNRUNNING_REASON = "网络信息模块未运行"


def _host_reachable(pet) -> bool:
    """宿主是否接上了模块生命周期（AppShell / SpriteMenuFacade 都提供）。"""
    return callable(getattr(pet, "running_module", None))


def _running_module(pet):
    getter = getattr(pet, "running_module", None)
    if not callable(getter):
        return None
    try:
        return getter(MODULE_ID)
    except Exception:
        return None


def _switch_on(pet) -> bool:
    cfg = getattr(pet, "cfg", None)
    if cfg is None:
        return True
    return bool(cfg.get(SWITCH_KEY, True))


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
    return _running_module(pet) is not None and _switch_on(pet)


def _disabled_reason(pet=None) -> str:
    if pet is None:
        return SWITCH_OFF_REASON
    if _running_module(pet) is None:
        return _unavailable_reason(pet)
    if not _switch_on(pet):
        return SWITCH_OFF_REASON
    return ""


def _build(menu, pet):
    module = _running_module(pet)
    callback = module.open_dialog if module is not None else (lambda: None)
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
