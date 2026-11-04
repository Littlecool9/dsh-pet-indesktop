# -*- coding: utf-8 -*-
"""「专注模式」模块运行时：进程级会话 + 专注陪伴控制器 + 宿主服务/事件。"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QCoreApplication

from ..base import ModuleHost, ModuleManifest
from .controller import FocusController
from .session import shared_focus_session
from .state import FocusService

MODULE_ID = "focus"
SERVICE_NAME = "focus"
CHANGED_TOPIC = "focus.changed"


class FocusModule:
    """进程级番茄钟：会话/控制器/服务都只有一份。"""

    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._config: Any = None
        self._session = None
        self._service: FocusService | None = None
        self._controller: FocusController | None = None
        self._last_state: dict | None = None

    @property
    def session(self):
        return self._session

    @property
    def controller(self) -> FocusController | None:
        return self._controller

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        self._config = getattr(host, "config", None)
        self._session = shared_focus_session()
        self._service = FocusService(self._session, self._config)
        self._controller = self._make_controller(host)
        host.provide(SERVICE_NAME, self._service)
        self._session.add_listener(self._state_changed)
        self._emit_state(force=True)

    def apply_config(self, config: Any) -> None:
        # 控制器每次读数都经 ``config.get("focus_mode")``；这里没有常驻状态要同步。
        self._config = config

    def stop(self) -> None:
        controller, self._controller = self._controller, None
        session = self._session
        host = self._host
        service = self._service
        if controller is not None:
            controller.stop()
        if session is not None:
            session.remove_listener(self._state_changed)
            self._emit_state()
        if host is not None and service is not None:
            host.withdraw(SERVICE_NAME, service)
        self._host = None
        self._service = None

    # ---- 菜单（menu_actions 入口调用）--------------------------------------
    def build_menu(self, menu, pet):
        if self._service is None:
            raise RuntimeError("专注模块尚未启动")
        return self._service.build_menu(menu, pet)

    # ---- 控制器 -------------------------------------------------------------
    def _make_controller(self, host: ModuleHost) -> FocusController | None:
        shell = getattr(host, "shell", None)
        if shell is None:
            # 纯模块单测（没有应用壳）：会话/事件照常，专注陪伴的呈现层缺席。
            return None
        from ...multi_window_shared import MultiWindowProxy

        identity = getattr(shell, "_chat_identity_config", None)
        identity_config = identity if callable(identity) else (lambda: self._config)
        return FocusController(
            self._config,
            MultiWindowProxy(shell),
            identity_config=identity_config,
            parent=QCoreApplication.instance(),
        )

    # ---- focus.changed ------------------------------------------------------
    def _state_changed(self) -> None:
        self._emit_state()

    def _snapshot(self) -> dict:
        session = self._session
        if session is None:
            return {"enabled": False, "phase": None, "endsAt": None}
        enabled = bool(session.engaged)
        ends_at = None
        if session.status == "running":
            ends_at = int(time.time() * 1000) + max(0, session.remaining_seconds()) * 1000
        return {
            "enabled": enabled,
            "phase": str(session.phase) if enabled else None,
            "endsAt": ends_at,
        }

    def _emit_state(self, *, force: bool = False) -> None:
        host = self._host
        if host is None:
            return
        payload = self._snapshot()
        if not force and payload == self._last_state:
            return
        self._last_state = payload
        host.emit(CHANGED_TOPIC, dict(payload))


def create(manifest: ModuleManifest) -> FocusModule:
    return FocusModule(manifest)


__all__ = ["CHANGED_TOPIC", "FocusModule", "SERVICE_NAME", "create"]
