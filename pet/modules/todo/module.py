# -*- coding: utf-8 -*-
"""「待办提醒」模块运行时：进程级提醒服务 + 非模态管理面板。

``apply_config`` 就是原来 ``AppShell._sync_todo_service`` 的语义：开关打开时
启动/刷新服务，关闭且面板没开时释放服务对象。服务与面板都只通过本模块的
小适配面（config / win / system_notify / 设置窗引用 / open_todo_panel）访问宿主，
``TodoReminderService`` / ``TodoPanelDialog`` 无需知道 AppShell 的存在。
"""
from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from ..base import ModuleHost, ModuleManifest
from .todo_panel import TodoPanelDialog
from .todo_reminder import TodoReminderService

logger = logging.getLogger(__name__)

MODULE_ID = "todo"


class TodoModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._service: TodoReminderService | None = None
        self._panel = None

    # ---- PetModule ---------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host

    def apply_config(self, config) -> None:
        wanted = bool(config.get("todo_reminder_enabled", True)) if config is not None else True
        if wanted:
            service = self._ensure_service()
            timer = getattr(service, "_timer", None)
            if timer is not None and callable(getattr(timer, "isActive", None)) and timer.isActive():
                # 已在运行：设置保存只刷新偏好/条目，不重置 30s tick。
                service.apply_config()
            elif callable(getattr(service, "start", None)):
                service.start()
        elif self._service is not None:
            try:
                self._service.stop()
            except Exception:
                logger.exception("停止待办提醒服务失败")
            # 面板持有服务引用并动态读取；面板还开着时保留对象。
            if self._panel is None:
                self._service = None

    def stop(self) -> None:
        service = self._service
        self._service = None
        if service is not None:
            try:
                service.stop()
            except Exception:
                logger.exception("停止待办提醒服务失败")
        panel = self._panel
        self._panel = None
        if panel is not None and shiboken6.isValid(panel):
            try:
                panel.close()
            except RuntimeError:
                logger.debug("待办面板关闭时已被销毁", exc_info=True)
        self._host = None

    # ---- 面板 --------------------------------------------------------------
    def open_panel(self) -> None:
        """打开待办管理面板（非模态单例；条目增删改即时落盘）。"""
        self._ensure_service()
        if self._panel is None or not shiboken6.isValid(self._panel):
            parent = getattr(self._shell, "win", None)
            dialog = TodoPanelDialog(
                self, parent=parent if isinstance(parent, QWidget) else None)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.finished.connect(self._panel_finished)
            self._panel = dialog
        presenter = getattr(self._host, "present_dialog", None)
        if callable(presenter):
            presenter(self._panel)
        else:
            self._panel.show()

    def _panel_finished(self, _result: int) -> None:
        self._panel = None

    # ---- TodoReminderService / TodoPanelDialog 的宿主适配面 ----------------
    @property
    def _shell(self):
        return getattr(self._host, "shell", None)

    @property
    def config(self):
        host = self._host
        cfg = getattr(host, "config", None)
        if cfg is not None:
            return cfg
        return getattr(self._shell, "config", None)

    @property
    def win(self):
        return getattr(self._shell, "win", None)

    def system_notify(self, title, message, *, on_click=None, duration_ms: int = 5000) -> None:
        notify = getattr(self._shell, "system_notify", None)
        if callable(notify):
            notify(title, message, on_click=on_click, duration_ms=duration_ms)

    @property
    def modern_settings_dialog(self):
        return getattr(self._shell, "modern_settings_dialog", None)

    @property
    def chat_settings_dialog(self):
        return getattr(self._shell, "chat_settings_dialog", None)

    @property
    def todo_service(self):
        return self._service

    def open_todo_panel(self) -> None:
        # 提醒通知的 on_click 指向这里（与旧 AppShell.open_todo_panel 同一语义）。
        self.open_panel()

    # ---- 内部 --------------------------------------------------------------
    def _ensure_service(self) -> TodoReminderService:
        if self._service is None:
            self._service = TodoReminderService(self)
        return self._service


def create(manifest: ModuleManifest) -> TodoModule:
    return TodoModule(manifest)


__all__ = ["TodoModule", "create"]
