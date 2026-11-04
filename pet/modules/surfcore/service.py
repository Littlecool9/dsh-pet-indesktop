# -*- coding: utf-8 -*-
"""提供给其它模块的 ``surfcore`` 服务对象（无 Qt 依赖）。

跨线程约定：

- ``submit`` 把 ``SurfCoreClient`` 的方法放到**单工作线程**上执行，所以阻塞的 HTTP
  永远不会占住 GUI 线程。完成后 ``host.emit("surfcore.result", SurfCoreResult)``；
  宿主的事件总线是 QueuedConnection，``on_done`` 在该事件的订阅者里执行，因此
  回到 GUI / 宿主线程。其它模块也可以直接订阅 ``surfcore.result``。
- ``focus.changed`` 由宿主在 GUI 线程投递进来：只记住最新状态，再交给工作线程发
  ``POST /focus``。同一时刻最多有一个同步任务，突发事件只会以最新状态收尾。
- ``set_online`` 记录轮询线程报告的上下线；从离线回到在线时把最新专注状态重发一次
  （SurfCore 可能重启过，``focus.json`` 已丢）。
- 所有后台失败只记错误码 / 异常类型，绝不抛回 GUI。

停止策略：``stop`` 取消尚未开始的任务并立即返回；正在跑的 HTTP 调用由客户端的
``timeout`` 兜底，不会让 ``stop`` 无限等待。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .client import SurfCoreClient, SurfCoreError

logger = logging.getLogger(__name__)

RESULT_TOPIC = "surfcore.result"
FOCUS_TOPIC = "focus.changed"
FOCUS_SOURCE = "desktop-pet"


@dataclass(frozen=True)
class SurfCoreResult:
    """一次后台调用的完成结果（``error`` 为空表示成功）。"""

    fn: str
    result: Any = None
    error: Exception | None = None
    callback: Callable[[Any, Exception | None], None] | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class _FocusState:
    enabled: bool
    phase: str | None
    ends_at: int | None


def parse_focus_state(payload: Any) -> _FocusState | None:
    """把 ``focus.changed`` 负载归一化；格式不对返回 ``None``（不猜状态）。"""
    if not isinstance(payload, Mapping):
        logger.warning("SurfCore 专注事件格式错误：%s", type(payload).__name__)
        return None
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        logger.warning("SurfCore 专注事件缺少 enabled：%s", type(payload).__name__)
        return None
    phase = payload.get("phase")
    if not isinstance(phase, str) or not phase:
        phase = None
    ends_at = payload.get("endsAt")
    if isinstance(ends_at, bool) or not isinstance(ends_at, (int, float)):
        ends_at = None
    else:
        ends_at = int(ends_at)
    return _FocusState(enabled=enabled, phase=phase, ends_at=ends_at)


class SurfCoreService:
    """``host.get("surfcore")`` 拿到的对象：客户端 + 上下线 + 后台调用 + 专注同步。

    ``executor`` 由 :class:`SurfCoreModule` 注入（模块拥有，``stop`` 时关闭）；
    独立使用 / 测试不传时会自建同样配置的单工作线程。
    """

    def __init__(
        self,
        client: SurfCoreClient,
        host: Any,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.client = client
        self.online = False
        self._host = host
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="surfcore-call"
        )
        self._lock = threading.Lock()
        self._stopped = False
        self._latest_focus: _FocusState | None = None
        self._pending_focus: _FocusState | None = None
        self._focus_scheduled = False
        self._unsubscribe: list[Callable[[], None]] = [
            host.subscribe(RESULT_TOPIC, self._on_result),
            host.subscribe(FOCUS_TOPIC, self._on_focus_changed),
        ]

    # ---- 公共接口 -----------------------------------------------------------
    def submit(
        self,
        fn_name: str,
        *args: Any,
        on_done: Callable[[Any, Exception | None], None] | None = None,
        **kwargs: Any,
    ) -> bool:
        """在后台线程调用 ``client.<fn_name>(*args, **kwargs)``。

        返回是否已排队（``stop`` 之后返回 ``False``）。完成结果通过宿主事件
        ``surfcore.result`` 投递；``on_done(result, error)`` 在该事件的订阅者里
        执行，因此运行在 GUI / 宿主线程。
        """
        with self._lock:
            if self._stopped:
                return False
            executor = self._executor
        try:
            executor.submit(self._run_call, fn_name, args, kwargs, on_done)
        except RuntimeError:
            return False
        return True

    def set_online(self, online: bool) -> None:
        """轮询线程报告上下线；离线 -> 在线时重发一次最新专注状态。"""
        value = bool(online)
        with self._lock:
            was_online = self.online
            self.online = value
            if not value or was_online or self._stopped:
                return
            latest = self._latest_focus
            if latest is None:
                return
            # 在线事件会唤醒正在等待的收尾任务；没有任务就排一个。
            self._pending_focus = latest
            executor = self._claim_focus_task_locked()
        self._start_focus_task(executor)

    def stop(self) -> None:
        """取消待执行的任务并关闭工作线程；不等待正在跑的 HTTP。"""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._pending_focus = None
            self._focus_scheduled = False
            executor = self._executor
            unsubscribes = self._unsubscribe
            self._unsubscribe = []
        for unsubscribe in unsubscribes:
            try:
                unsubscribe()
            except Exception:
                pass
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as error:
            logger.warning("SurfCore 工作线程停止异常：%s", type(error).__name__)

    # ---- 结果投递 -----------------------------------------------------------
    def _run_call(
        self,
        fn_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        on_done: Callable[[Any, Exception | None], None] | None,
    ) -> None:
        result: Any = None
        error: Exception | None = None
        try:
            method = getattr(self.client, fn_name)
            result = method(*args, **kwargs)
        except Exception as exc:  # 网络 / 协议 / 未知错误都只作为结果返回
            error = exc
        self._deliver(SurfCoreResult(fn_name, result, error, on_done))

    def _deliver(self, payload: SurfCoreResult) -> None:
        with self._lock:
            if self._stopped:
                return
        try:
            self._host.emit(RESULT_TOPIC, payload)
        except Exception as error:
            logger.warning("SurfCore 结果事件发送失败：%s", type(error).__name__)

    def _on_result(self, payload: Any) -> None:
        """宿主线程：调用 ``on_done``（异常不能打穿事件循环）。"""
        if not isinstance(payload, SurfCoreResult):
            return
        with self._lock:
            if self._stopped:
                return
        callback = payload.callback
        if callback is None:
            return
        try:
            callback(payload.result, payload.error)
        except Exception as error:
            logger.warning("SurfCore 完成回调异常：%s", type(error).__name__)

    # ---- 专注同步 -----------------------------------------------------------
    def _on_focus_changed(self, payload: Any) -> None:
        state = parse_focus_state(payload)
        if state is None:
            return
        with self._lock:
            self._latest_focus = state
            self._pending_focus = state
            executor = self._claim_focus_task_locked()
        self._start_focus_task(executor)

    def _claim_focus_task_locked(self) -> ThreadPoolExecutor | None:
        if self._stopped or self._focus_scheduled:
            return None
        self._focus_scheduled = True
        return self._executor

    def _start_focus_task(self, executor: ThreadPoolExecutor | None) -> None:
        if executor is None:
            return
        try:
            executor.submit(self._drain_focus)
        except RuntimeError:
            with self._lock:
                self._focus_scheduled = False

    def _drain_focus(self) -> None:
        """工作线程：不断取走最新待同步状态，突发事件自然合并成一次收尾。"""
        try:
            while True:
                with self._lock:
                    state = self._pending_focus
                    self._pending_focus = None
                    if state is None:
                        self._focus_scheduled = False
                        return
                self._sync_focus(state)
        except Exception as error:
            # 兜底：别让任务标志永远卡住，后续事件仍能同步。
            logger.warning("SurfCore 专注同步任务异常：%s", type(error).__name__)
            with self._lock:
                self._focus_scheduled = False

    def _sync_focus(self, state: _FocusState) -> None:
        try:
            self.client.set_focus(
                state.enabled,
                phase=state.phase,
                ends_at=state.ends_at,
                source=FOCUS_SOURCE,
            )
        except SurfCoreError as error:
            # 只记稳定错误码；令牌、URL、专注内容都不进日志。
            logger.warning("SurfCore 专注同步失败：%s", error.code)
        except Exception as error:
            logger.warning("SurfCore 专注同步异常：%s", type(error).__name__)


__all__ = [
    "FOCUS_SOURCE",
    "FOCUS_TOPIC",
    "RESULT_TOPIC",
    "SurfCoreResult",
    "SurfCoreService",
    "parse_focus_state",
]
