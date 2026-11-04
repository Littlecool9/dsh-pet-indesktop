# -*- coding: utf-8 -*-
"""SurfCore 客户端模块：提供 ``surfcore`` 服务并把事件/上下线转成宿主事件。

模块运行时不碰 Qt：轮询线程只调用 ``host.emit``（宿主实现保证排队到 GUI 线程），
后台 HTTP 调用由 :class:`~pet.modules.surfcore.service.SurfCoreService` 的单工作
线程负责。本阶段没有配置键；``apply_config`` 只负责确保轮询线程还活着（幂等）。

``host.get("surfcore")`` 现在拿到的是 ``SurfCoreService``（``.client`` 仍可直接拿
到 ``SurfCoreClient``）；``focus.changed`` 也由该服务订阅并同步给 SurfCore。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..base import ModuleHost, ModuleManifest
from .client import SurfCoreClient
from .events import EventPoller
from .service import SurfCoreService

SERVICE_NAME = "surfcore"
EVENT_TOPIC = "surfcore.event"
ONLINE_TOPIC = "surfcore.online"


class SurfCoreModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._client: SurfCoreClient | None = None
        self._poller: EventPoller | None = None
        self._service: SurfCoreService | None = None
        self._executor: ThreadPoolExecutor | None = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        if self._service is not None:
            # 重复 start 不再造第二个轮询线程 / 第二个服务对象。
            host.provide(SERVICE_NAME, self._service)
            return
        client = SurfCoreClient()
        poller = EventPoller(client, self._on_event, self._on_online_change)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="surfcore-call")
        service = SurfCoreService(client, host, executor=executor)
        self._host = host
        self._client = client
        self._poller = poller
        self._service = service
        self._executor = executor
        host.provide(SERVICE_NAME, service)
        poller.start()

    def apply_config(self, config: Any) -> None:
        # 还没有本模块的配置键；只保证轮询在跑（幂等，异常时由注册表隔离）。
        poller = self._poller
        if poller is not None and not poller.running:
            poller.start()

    def stop(self) -> None:
        poller = self._poller
        host = self._host
        service = self._service
        self._poller = None
        self._client = None
        self._host = None
        self._service = None
        self._executor = None
        if service is not None:
            service.stop()
        if poller is not None:
            poller.stop()
        if host is not None and service is not None:
            host.withdraw(SERVICE_NAME, service)

    # ---- 轮询回调（可能在轮询线程里执行）------------------------------------
    def _on_event(self, event: Any) -> None:
        host = self._host
        if host is not None:
            host.emit(EVENT_TOPIC, event)

    def _on_online_change(self, online: bool) -> None:
        service = self._service
        if service is not None:
            service.set_online(bool(online))
        host = self._host
        if host is not None:
            host.emit(ONLINE_TOPIC, bool(online))


def create(manifest: ModuleManifest) -> SurfCoreModule:
    return SurfCoreModule(manifest)


__all__ = ["SurfCoreModule", "create"]
