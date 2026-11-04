# -*- coding: utf-8 -*-
"""SurfCore 客户端模块：提供 ``surfcore`` 服务并把事件/上下线转成宿主事件。

模块运行时不碰 Qt：轮询线程只调用 ``host.emit``（宿主实现保证排队到 GUI 线程）。
本阶段没有配置键；``apply_config`` 只负责确保轮询线程还活着（幂等）。
"""
from __future__ import annotations

from typing import Any

from ..base import ModuleHost, ModuleManifest
from .client import SurfCoreClient
from .events import EventPoller

SERVICE_NAME = "surfcore"
EVENT_TOPIC = "surfcore.event"
ONLINE_TOPIC = "surfcore.online"


class SurfCoreModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._client: SurfCoreClient | None = None
        self._poller: EventPoller | None = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        if self._client is not None:
            # 重复 start 不再造第二个轮询线程 / 第二个服务对象。
            host.provide(SERVICE_NAME, self._client)
            return
        client = SurfCoreClient()
        poller = EventPoller(client, self._on_event, self._on_online_change)
        self._host = host
        self._client = client
        self._poller = poller
        host.provide(SERVICE_NAME, client)
        poller.start()

    def apply_config(self, config: Any) -> None:
        # 还没有本模块的配置键；只保证轮询在跑（幂等，异常时由注册表隔离）。
        poller = self._poller
        if poller is not None and not poller.running:
            poller.start()

    def stop(self) -> None:
        poller = self._poller
        client = self._client
        host = self._host
        self._poller = None
        self._client = None
        self._host = None
        if poller is not None:
            poller.stop()
        if host is not None and client is not None:
            host.withdraw(SERVICE_NAME, client)

    # ---- 轮询回调（可能在轮询线程里执行）------------------------------------
    def _on_event(self, event: Any) -> None:
        host = self._host
        if host is not None:
            host.emit(EVENT_TOPIC, event)

    def _on_online_change(self, online: bool) -> None:
        host = self._host
        if host is not None:
            host.emit(ONLINE_TOPIC, bool(online))


def create(manifest: ModuleManifest) -> SurfCoreModule:
    return SurfCoreModule(manifest)


__all__ = ["SurfCoreModule", "create"]
