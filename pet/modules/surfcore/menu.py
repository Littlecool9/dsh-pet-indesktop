# -*- coding: utf-8 -*-
"""「快速对话」右键菜单条目（陪伴线；字符串入口，两个进程都可只读加载）。

条目本身不依赖模块实例：在线状态实时读运行中的 ``surfcore`` 模块。SurfCore
离线时置灰并写明原因（``disabled_reason``），绝不静默回退直连 API。
"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action
from .companion import OFFLINE_HINT

MODULE_ID = "surfcore"
ACTION_ID = "quick_chat"
LABEL = "快速对话"
ICON = "chat"
UNRUNNING_REASON = "SurfCore 模块未运行"


def _running_module(pet):
    getter = getattr(pet, "running_module", None)
    if not callable(getter):
        return None
    try:
        return getter(MODULE_ID)
    except Exception:
        return None


def _available(pet) -> bool:
    """宿主提供了打开快速对话的动作面才出现该条目。"""
    return callable(getattr(pet, "on_open_quick_chat", None))


def _online(pet) -> bool:
    module = _running_module(pet)
    return bool(getattr(module, "online", False))


def _enabled(pet) -> bool:
    return _available(pet) and _online(pet)


def _disabled_reason(pet=None) -> str:
    if pet is None:
        return OFFLINE_HINT
    getter = getattr(pet, "module_unavailable_reason", None)
    if callable(getter):
        try:
            reason = str(getter(MODULE_ID) or "")
        except Exception:
            reason = ""
        if reason:
            return reason
    if _running_module(pet) is None:
        return UNRUNNING_REASON
    return OFFLINE_HINT


def _build(menu, pet):
    opener = getattr(pet, "on_open_quick_chat", None)
    callback = opener if callable(opener) else (lambda: None)
    action = add_action(menu, LABEL, ICON, callback, close_on_trigger=True)
    if not _enabled(pet):
        action.setEnabled(False)
        action.setToolTip(_disabled_reason(pet))
    return action


def actions() -> dict[str, MenuActionSpec]:
    return {
        ACTION_ID: MenuActionSpec(
            _build,
            available=_available,
            enabled=_enabled,
            disabled_reason=_disabled_reason,
            label=LABEL,
            icon=ICON,
        ),
    }


__all__ = ["ACTION_ID", "actions"]
