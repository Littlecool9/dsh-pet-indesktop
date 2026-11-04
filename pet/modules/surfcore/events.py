# -*- coding: utf-8 -*-
"""SurfCore /events 长轮询（守护线程，无 Qt 依赖）。

服务端语义（``pet-chat.js`` 的 ``poll``）：

- ``since`` 为空 → 只返回当前游标，不重放旧事件（插件重启后客户端先取水位）；
- 有事件 → 返回 ``cursor``（批次最大 id）与升序事件；
- 没事件 → 最多挂住 ``wait`` 毫秒再返回空批次。

停止策略：**短轮询超时 + join 上限**。每轮 ``wait`` 只取 ``poll_timeout_s``
（默认 2 秒），``stop(timeout)`` 置停止事件后最多等 ``timeout`` 秒；即使服务端
正挂着一个长轮询，连接也会在 ``poll_timeout_s`` 内自然返回，所以 ``stop()``
不会无限等下去（不依赖跨线程关闭 socket）。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

from .client import SurfCoreClient, SurfCoreError

logger = logging.getLogger(__name__)


class EventPoller:
    """在守护线程里长轮询 ``/events``，按顺序投递事件并在上下线变化时回调。"""

    def __init__(
        self,
        client: SurfCoreClient,
        on_event: Callable[[Any], None] | None,
        on_online_change: Callable[[bool], None] | None,
        *,
        backoff: Iterable[float] = (1, 2, 5, 10, 30),
        poll_timeout_s: float = 2.0,
    ) -> None:
        self._client = client
        self._on_event = on_event
        self._on_online_change = on_online_change
        self._backoff = tuple(max(0.0, float(item)) for item in backoff) or (1.0,)
        self._poll_timeout_s = max(0.1, float(poll_timeout_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor: int | None = None
        self._online = False

    @property
    def online(self) -> bool:
        return self._online

    @property
    def cursor(self) -> int | None:
        return self._cursor

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._online = False
        self._thread = threading.Thread(
            target=self._run, name="surfcore-events", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """请求停止并最多等 ``timeout`` 秒；返回线程是否已经退出。"""
        self._stop.set()
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(max(0.0, float(timeout)))
        return not thread.is_alive()

    # ---- 线程主体 -----------------------------------------------------------
    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                response = self._client.wait_events(self._cursor, self._poll_timeout_s)
            except SurfCoreError as error:
                self._set_online(False)
                logger.debug("SurfCore 事件轮询失败：%s", error.code)
                failures += 1
                if self._wait_backoff(failures):
                    return
                continue
            except Exception as error:  # 未预期异常也不让守护线程死掉
                self._set_online(False)
                logger.warning("SurfCore 事件轮询异常：%s", type(error).__name__)
                failures += 1
                if self._wait_backoff(failures):
                    return
                continue

            failures = 0
            self._set_online(True)
            try:
                events, cursor = self._parse(response)
            except SurfCoreError:
                self._set_online(False)
                failures = 1
                if self._wait_backoff(failures):
                    return
                continue

            for event in events:
                if self._stop.is_set():
                    return
                self._deliver_event(event)
            if cursor is not None:
                self._cursor = cursor

    def _wait_backoff(self, failures: int) -> bool:
        delay = self._backoff[min(max(0, failures - 1), len(self._backoff) - 1)]
        return self._stop.wait(delay)

    @staticmethod
    def _ordered(events: list[Any]) -> list[Any]:
        try:
            return sorted(events, key=lambda item: int(item["id"]))
        except (KeyError, TypeError, ValueError):
            return list(events)

    @staticmethod
    def _parse(response: Any) -> tuple[list[Any], int | None]:
        if not isinstance(response, dict):
            raise SurfCoreError("bad-response")
        raw_events = response.get("events")
        if raw_events is None:
            raw_events = []
        if not isinstance(raw_events, list):
            raise SurfCoreError("bad-response")
        raw_cursor = response.get("cursor")
        if raw_cursor is None:
            if raw_events:
                raise SurfCoreError("bad-response")
            cursor: int | None = None
        else:
            if isinstance(raw_cursor, bool) or not isinstance(raw_cursor, (int, float)):
                raise SurfCoreError("bad-response")
            cursor = int(raw_cursor)
        return EventPoller._ordered(raw_events), cursor

    def _deliver_event(self, event: Any) -> None:
        callback = self._on_event
        if callback is None:
            return
        try:
            callback(event)
        except Exception as error:
            # 事件内容可能含消息文本，只记录异常类型。
            logger.warning("SurfCore 事件回调异常：%s", type(error).__name__)

    def _set_online(self, value: bool) -> None:
        if value == self._online:
            return
        self._online = value
        callback = self._on_online_change
        if callback is None:
            return
        try:
            callback(value)
        except Exception as error:
            logger.warning("SurfCore 上下线回调异常：%s", type(error).__name__)


__all__ = ["EventPoller"]
