# -*- coding: utf-8 -*-
"""「Agent 联动」模块运行时：进程级共享管理器 + 宿主服务 / 事件。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..base import ModuleHost, ModuleManifest
from .shared import SharedAgentLinkManager

logger = logging.getLogger(__name__)

MODULE_ID = "agent_link"
SERVICE_NAME = "agent_link"
EVENT_TOPIC = "agent_link.event"


class _FallbackConfig:
    """无应用壳的纯模块单测：没有配置目录/开关，所有联动都按关闭处理。"""

    dir = Path(".")

    def get(self, key, default=None):
        return default


class AgentLinkModule:
    """一个进程只有一份共享 Agent 联动管理器。"""

    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._config: Any = None
        self._manager: SharedAgentLinkManager | None = None

    @property
    def manager(self) -> SharedAgentLinkManager | None:
        return self._manager

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        self._config = getattr(host, "config", None) or _FallbackConfig()
        shell = getattr(host, "shell", None)
        proxy = self._presentation_target(shell) or host
        manager = SharedAgentLinkManager(proxy, self._config)
        manager.dsh_state_changed.connect(self._on_dsh_state_changed)
        self._manager = manager
        host.provide(SERVICE_NAME, manager)
        self._attach(shell, manager)

    def apply_config(self, config) -> None:
        self._config = config
        manager = self._manager
        if manager is None:
            return
        manager.cfg = config
        manager.apply_config()

    def stop(self) -> None:
        manager, self._manager = self._manager, None
        host, self._host = self._host, None
        shell = getattr(host, "shell", None) if host is not None else None
        if manager is not None:
            try:
                manager.stop_all()
            except Exception:
                logger.exception("关闭 Agent 联动模块失败")
            self._detach(shell, manager)
        if host is not None and manager is not None:
            host.withdraw(SERVICE_NAME, manager)

    # ---- 宿主呈现面 ---------------------------------------------------------
    @staticmethod
    def _presentation_target(shell):
        if shell is None:
            return None
        from ...multi_window_shared import MultiWindowProxy

        return MultiWindowProxy(shell)

    @staticmethod
    def _attach(shell, manager: SharedAgentLinkManager) -> None:
        """把共享 manager 接到壳的联动链/呈现面（app 启动时壳已就绪）。"""
        if shell is None:
            return
        shared = getattr(shell, "_shared", None)
        proxy = getattr(shared, "proxy", None)
        if proxy is not None:
            try:
                proxy.set_link_next_provider(manager._next_busy_anim)
            except Exception:
                logger.debug("接入共享联动链失败", exc_info=True)
        overlay = getattr(shell, "_overlay_shell", None)
        if overlay is not None:
            try:
                overlay.agent_link_manager = manager
            except Exception:
                logger.debug("注入联动呈现面失败", exc_info=True)

    @staticmethod
    def _detach(shell, manager: SharedAgentLinkManager) -> None:
        if shell is None:
            return
        shared = getattr(shell, "_shared", None)
        proxy = getattr(shared, "proxy", None)
        if proxy is not None:
            try:
                proxy.set_link_next_provider(None)
            except Exception:
                logger.debug("断开共享联动链失败", exc_info=True)
        overlay = getattr(shell, "_overlay_shell", None)
        if overlay is not None and getattr(overlay, "agent_link_manager", None) is manager:
            try:
                overlay.agent_link_manager = None
            except Exception:
                logger.debug("撤销联动呈现面失败", exc_info=True)

    # ---- agent_link.event ---------------------------------------------------
    def _on_dsh_state_changed(self, from_state: str, to_state: str) -> None:
        host = self._host
        if host is None:
            return
        host.emit(EVENT_TOPIC, {
            "kind": "dsh_state",
            "from": str(from_state),
            "to": str(to_state),
        })


def create(manifest: ModuleManifest) -> AgentLinkModule:
    return AgentLinkModule(manifest)


__all__ = ["AgentLinkModule", "EVENT_TOPIC", "MODULE_ID", "SERVICE_NAME", "create"]
