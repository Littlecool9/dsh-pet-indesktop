# -*- coding: utf-8 -*-
"""应用侧宿主：模块能碰到的唯一门。

``AppModuleHost`` 在通用服务表 / 事件总线（:class:`~pet.modules.host.ModuleHostBase`）
之上补应用能力：配置、QApplication、对话框父窗与主宠气泡。模块不 import
``pet.app`` / ``pet.overlay_shell``，只依赖这里真的用到的方法。
"""
from __future__ import annotations

import logging
from typing import Any

from .modules.host import ModuleHostBase

logger = logging.getLogger(__name__)


def module_service(shell, module_id: str, default: Any = None) -> Any:
    """从应用壳的模块宿主取一个服务；模块缺失/未启动时返回 ``default``。

    核心读模块能力（例如专注状态）只走这一个入口：拿不到服务 = 该功能关闭，
    与用户主动关掉同义——核心从不 import 具体模块。
    """
    host = getattr(shell, "_module_host", None)
    getter = getattr(host, "get", None)
    if not callable(getter):
        return default
    try:
        return getter(module_id, default)
    except Exception:
        logger.debug("读取模块 %s 的服务失败", module_id, exc_info=True)
        return default


class AppModuleHost(ModuleHostBase):
    def __init__(self, shell, parent=None) -> None:
        super().__init__(parent)
        self.shell = shell
        self.config = shell.config
        self.app = shell.app

    # ---- 应用能力 -----------------------------------------------------------
    def dialog_parent(self):
        """弹窗父窗：overlay 壳的合成窗（QWidget）；还没建壳时返回 None。"""
        from PySide6.QtWidgets import QWidget

        overlay_shell = getattr(self.shell, "_overlay_shell", None)
        widget = getattr(overlay_shell, "overlay", None)
        return widget if isinstance(widget, QWidget) else None

    def show_bubble(self, text: str, ms: int = 3200) -> bool:
        """在主宠头顶冒一条气泡；没有壳时静默 no-op（返回是否真的上屏）。"""
        overlay_shell = getattr(self.shell, "_overlay_shell", None)
        show = getattr(overlay_shell, "show_bubble", None)
        if not callable(show):
            return False
        try:
            return bool(show(str(text), int(ms)))
        except Exception:
            logger.debug("模块气泡展示失败", exc_info=True)
            return False

    def present_dialog(self, dialog: Any) -> None:
        """按应用既有路径呈现非模态窗（菜单关闭后再 show/raise）。"""
        instance = getattr(self.shell, "instance", None)
        present = getattr(instance, "_present_dialog", None)
        if callable(present):
            present(dialog)
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()


__all__ = ["AppModuleHost", "module_service"]
