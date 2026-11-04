# -*- coding: utf-8 -*-
"""「DeepSeek 余额」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action

MODULE_ID = "balance"
LABEL = "DeepSeek 余额"
ICON = "balance"
UNRUNNING_REASON = "余额模块未运行"


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


def _service_host(pet):
    """overlay 的菜单旁路把结果落到**发起 sprite**的呈现器；窗口路径就是 pet。"""
    maker = getattr(pet, "_service_host", None)
    if callable(maker):
        try:
            host = maker()
        except Exception:
            host = None
        if host is not None:
            return host
    return pet


def _available(pet) -> bool:
    if not _host_reachable(pet):
        return False
    chat_available = getattr(pet, "chat_available", None)
    return bool(chat_available) if chat_available is not None else True


def _enabled(pet) -> bool:
    return _running_module(pet) is not None


def _disabled_reason(pet=None) -> str:
    return _unavailable_reason(pet) if pet is not None else UNRUNNING_REASON


def _build(menu, pet):
    module = _running_module(pet)
    host = _service_host(pet)
    callback = (
        (lambda: module.show_balance(host)) if module is not None else (lambda: None)
    )
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
