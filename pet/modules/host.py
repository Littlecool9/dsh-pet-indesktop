# -*- coding: utf-8 -*-
"""模块宿主的通用部分：服务表 + 事件总线（跨线程一律排队到宿主线程）。

应用侧宿主（``pet.module_host.AppModuleHost``）继承它，再按模块需要加配置、气泡、
灵动岛等能力。事件总线用 Qt 信号：``emit`` 可以在任何线程调用，回调总在宿主对象
所在线程（GUI 线程）执行——模块不必自己 ``QTimer.singleShot`` 回主线程。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal

logger = logging.getLogger(__name__)


class ModuleHostBase(QObject):
    """服务表 + 事件总线。"""

    _event = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        # QueuedConnection：发射线程不等回调；同线程发射也排到下一轮事件循环，
        # 避免订阅者在发布者的调用栈里重入。
        self._event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    # ---- 服务表 --------------------------------------------------------------
    def provide(self, name: str, service: Any) -> None:
        if name in self._services and self._services[name] is not service:
            raise ValueError(f"服务 {name!r} 已由别的模块提供")
        self._services[name] = service

    def withdraw(self, name: str, service: Any | None = None) -> None:
        """模块 stop 时撤回自己提供的服务（传 service 时只撤回同一个对象）。"""
        if service is None or self._services.get(name) is service:
            self._services.pop(name, None)

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    # ---- 事件总线 ------------------------------------------------------------
    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        self._subscribers.setdefault(topic, []).append(callback)

        def unsubscribe() -> None:
            callbacks = self._subscribers.get(topic, [])
            if callback in callbacks:
                callbacks.remove(callback)

        return unsubscribe

    def emit(self, topic: str, payload: Any = None) -> None:
        self._event.emit(topic, payload)

    def _dispatch(self, topic: str, payload: Any) -> None:
        for callback in list(self._subscribers.get(topic, [])):
            try:
                callback(payload)
            except Exception:
                logger.exception("模块事件 %s 的订阅者出错", topic)


__all__ = ["ModuleHostBase"]
