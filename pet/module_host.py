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

    # ---- 自言自语（呈现/每宠配置/门禁由壳提供，模块不 import 壳）----------
    def pet_config(self) -> Any:
        """主宠那份每宠配置视图（自言自语等每宠键的真值在槽档案里）。"""
        overlay_shell = getattr(self.shell, "_overlay_shell", None)
        cfg = getattr(overlay_shell, "cfg", None)
        if cfg is not None and callable(getattr(cfg, "get", None)):
            return cfg
        return self.config

    def self_talk_ready(self) -> bool:
        """自言自语当前是否允许上屏（可见/抑制/专注/提醒让路/忙时）。"""
        fn = getattr(getattr(self.shell, "_overlay_shell", None), "self_talk_ready", None)
        if not callable(fn):
            return True
        try:
            return bool(fn())
        except Exception:
            logger.debug("自言自语门禁查询失败", exc_info=True)
            return False

    def prepare_self_talk(self, *, images, image_scale) -> None:
        """把模块选出的配图清单交给壳的预热缓存（GUI 线程零磁盘/解码税）。"""
        fn = getattr(getattr(self.shell, "_overlay_shell", None),
                    "prepare_self_talk", None)
        if callable(fn):
            try:
                fn(images=images, image_scale=image_scale)
            except Exception:
                logger.debug("自言自语配图预热失败", exc_info=True)

    def show_self_talk(self, *, text=None, image=None, duration_ms: int = 3200,
                       image_scale=None) -> bool:
        """用壳的既有气泡路径呈现一条自言自语；返回是否真的上屏。"""
        overlay_shell = getattr(self.shell, "_overlay_shell", None)
        fn = getattr(overlay_shell, "show_self_talk", None)
        if callable(fn):
            try:
                return bool(fn(
                    text=text, image=image,
                    duration_ms=int(duration_ms), image_scale=image_scale))
            except Exception:
                logger.debug("模块自言自语展示失败", exc_info=True)
                return False
        if text is None:
            return False
        return self.show_bubble(str(text), int(duration_ms))

    def set_self_talk_visible(self, visible: bool) -> None:
        """桌宠显隐变化：让模块停表/重排（旧壳的显隐对称语义）。"""
        getter = getattr(self.shell, "running_module", None)
        module = getter("self_talk") if callable(getter) else None
        setter = getattr(module, "set_visible", None)
        if callable(setter):
            try:
                setter(bool(visible))
            except Exception:
                logger.debug("自言自语显隐同步失败", exc_info=True)


__all__ = ["AppModuleHost", "module_service"]
