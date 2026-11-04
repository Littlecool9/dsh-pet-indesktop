# -*- coding: utf-8 -*-
"""「快捷启动」右键菜单条目与运行时（Qt 侧，按需加载）。"""
from __future__ import annotations

import os

from PySide6.QtCore import QFileInfo, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QFileIconProvider, QMenu

from ...context_menus.icons import fitted_application_icon, vector_menu_icon
from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_submenu, connect_action
from .config import DEFAULT_QUICK_LAUNCH_APPS

MODULE_ID = "quick_launch"
LABEL = "快捷启动"
ICON = "application"
DISABLED_REASON = "尚未配置快捷启动应用"


def configured_quick_apps(config) -> list[dict]:
    value = config.get("quick_launch_apps", DEFAULT_QUICK_LAUNCH_APPS)
    return [dict(item) for item in value if isinstance(item, dict)]


# 首次 QFileIconProvider 取应用图标可能较慢；按 (kind, path) 缓存结果
_QUICK_ICON_CACHE: dict[tuple[str, str], QIcon] = {}


def quick_app_icon(menu: QMenu, item: dict) -> QIcon:
    kind = str(item.get("kind") or "")
    path = str(item.get("path") or "")
    cache_key = (kind, path)
    cached = _QUICK_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if kind == "default_browser":
        icon = vector_menu_icon(menu, "web")
    else:
        icon = QFileIconProvider().icon(QFileInfo(path)) if path else QIcon()
        icon = fitted_application_icon(icon, 18, menu) if not icon.isNull() else vector_menu_icon(menu, "application")
    _QUICK_ICON_CACHE[cache_key] = icon
    return icon


def launch_quick_app(item: dict) -> bool:
    if item.get("kind") == "default_browser":
        return bool(QDesktopServices.openUrl(QUrl("https://www.google.com/")))
    path = os.path.abspath(os.path.expanduser(str(item.get("path") or "")))
    if not path:
        return False
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def add_quick_launch_menu(menu: QMenu, config) -> QMenu:
    apps = configured_quick_apps(config)
    submenu = add_submenu(menu, "快捷启动", "application")
    if not apps:
        placeholder = submenu.addAction("尚未配置快捷项")
        placeholder.setEnabled(False)
        return submenu
    for item in apps:
        action = submenu.addAction(quick_app_icon(submenu, item), str(item.get("name") or "应用"))
        action.setProperty("closeOnTrigger", True)
        connect_action(action, lambda item=dict(item): launch_quick_app(item))
    return submenu


def _pet_reachable(pet) -> bool:
    """所有菜单宿主（窗口 / sprite facade）都能给出 ``cfg``。"""
    return callable(getattr(getattr(pet, "cfg", None), "get", None))


def _enabled(pet) -> bool:
    cfg = getattr(pet, "cfg", None)
    return bool(configured_quick_apps(cfg)) if cfg is not None else False


def _build(menu, pet):
    return add_quick_launch_menu(menu, pet.cfg)


def actions() -> dict[str, MenuActionSpec]:
    return {
        MODULE_ID: MenuActionSpec(
            _build,
            available=_pet_reachable,
            enabled=_enabled,
            disabled_reason=DISABLED_REASON,
            label=LABEL,
            icon=ICON,
        ),
    }


__all__ = [
    "DISABLED_REASON", "LABEL", "MODULE_ID", "actions",
    "add_quick_launch_menu", "configured_quick_apps", "launch_quick_app",
    "quick_app_icon",
]
