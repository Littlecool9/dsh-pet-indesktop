# -*- coding: utf-8 -*-
"""「网络信息」模块运行时：进程级单例弹窗。"""
from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from ..base import ModuleHost, ModuleManifest

logger = logging.getLogger(__name__)

MODULE_ID = "network_info"


class NetworkInfoModule:
    """一个进程只有一个网络信息弹窗；窗口销毁后下一次打开自愈。"""

    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._dialog = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host

    def apply_config(self, config) -> None:
        # 菜单条目在每次右键时读配置；这里没有常驻状态要同步。
        return None

    def stop(self) -> None:
        dialog = self._dialog
        self._dialog = None
        self._host = None
        if dialog is not None and shiboken6.isValid(dialog):
            try:
                dialog.close()
            except RuntimeError:
                logger.debug("网络信息弹窗关闭时已被销毁", exc_info=True)

    # ---- 打开 ---------------------------------------------------------------
    def open_dialog(self, parent=None) -> None:
        """打开（或前置）唯一弹窗；父窗带走子窗后照样能重开。"""
        from .dialog import NetworkInfoDialog

        dialog = self._dialog
        if dialog is not None and not shiboken6.isValid(dialog):
            # destroyed 信号可能还没送达（或父宠物先走一步带走子窗）。
            dialog = None
            self._dialog = None
        if dialog is None:
            if parent is None and self._host is not None:
                try:
                    parent = self._host.dialog_parent()
                except Exception:
                    logger.debug("取网络信息弹窗父窗失败", exc_info=True)
                    parent = None
            if not isinstance(parent, QWidget):
                parent = None
            dialog = NetworkInfoDialog(parent)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.finished.connect(self._dialog_finished)
            dialog.destroyed.connect(
                lambda *_args, target=dialog: self._dialog_destroyed(target))
            self._dialog = dialog
        self._present(dialog)

    def _present(self, dialog) -> None:
        """与 AppShell 原路径同义：延迟到菜单关闭后 show/raise/activate。"""
        host = self._host
        present = getattr(host, "present_dialog", None)
        if callable(present):
            try:
                present(dialog)
                return
            except Exception:
                logger.debug("宿主呈现弹窗失败，回退直接 show", exc_info=True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ---- 单例收口 -----------------------------------------------------------
    def _dialog_finished(self, _result: int) -> None:
        self._dialog = None

    def _dialog_destroyed(self, dialog) -> None:
        # 旧窗的 destroyed 可能晚于新窗创建：只认当前持有的那一个。
        if self._dialog is dialog:
            self._dialog = None


def create(manifest: ModuleManifest) -> NetworkInfoModule:
    return NetworkInfoModule(manifest)


__all__ = ["NetworkInfoModule", "create"]
