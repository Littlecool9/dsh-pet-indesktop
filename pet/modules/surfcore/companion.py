# -*- coding: utf-8 -*-
"""陪伴线（快速气泡 / 岛对话 / 主动搭话）的 SurfCore 侧。

本模块只做三件事，不碰 Qt：

- 把 GUI 的发送动作转成 ``Service.submit("chat", ...)``（后台工作线程）；
- 把 ``surfcore.online`` 的上下线变化转给气泡，让发送入口可用 / 置灰；
- 把 ``surfcore.event`` 里由 SurfCore 主动推来的消息（``proactive`` / 外部
  ``reply``）交给宿主的气泡呈现面，由宿主按既有门禁（免打扰 / 专注 / 全屏 /
  桌宠隐藏）决定是否真的上屏。

呈现面由 :class:`pet.module_host.AppModuleHost` 提供：
``show_companion_bubble(text)`` 会在门禁通过时冒一条可点的桌宠气泡（点击即
打开快速对话输入），被门禁拦下则返回 ``False``——模块不绕过宿主自己上屏。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

EVENT_TOPIC = "surfcore.event"
ONLINE_TOPIC = "surfcore.online"

#: 离线时各入口统一显示的可见原因（快速气泡 / 岛气泡 / 右键菜单共用）。
OFFLINE_HINT = "SurfCore 未连接：启动 DSH 后会自动连上"

_PUSH_TYPES = frozenset({"proactive", "reply"})
_LOCAL_REPLY_LIMIT = 32


class CompanionBridge:
    """``SurfCoreService.companion``：陪伴线发送 + 主动消息转呈。"""

    def __init__(self, host: Any, service: Any) -> None:
        self._host = host
        self._service = service
        self._online = bool(getattr(service, "online", False))
        self._listeners: list[Callable[[bool], None]] = []
        self._local_replies: list[str] = []
        self._unsubscribe: list[Callable[[], None]] = [
            host.subscribe(EVENT_TOPIC, self._on_event),
            host.subscribe(ONLINE_TOPIC, self._on_online),
        ]

    # ---- 状态 ---------------------------------------------------------------
    @property
    def online(self) -> bool:
        """实时在线状态以服务为准（上下线事件可能还在队列里）。"""
        return bool(getattr(self._service, "online", self._online))

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        """订阅上下线变化（宿主线程执行；用于刷新发送按钮与离线原因）。"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[bool], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    # ---- 发送 ---------------------------------------------------------------
    def send(self, text: str, on_done: Callable[[Any, Exception | None], None] | None = None) -> bool:
        """提交一次 ``/chat``；离线返回 ``False``（调用方显示可见原因）。"""
        if not self.online:
            return False
        submit = getattr(self._service, "submit", None)
        if not callable(submit):
            return False
        try:
            return bool(submit("chat", str(text), on_done=on_done, modality="text"))
        except Exception:
            logger.debug("SurfCore 聊天提交失败", exc_info=True)
            return False

    def note_local_reply(self, message_id: Any) -> None:
        """记下本气泡自己收到的回复 id，避免外部 ``reply`` 事件再冒一遍。"""
        value = str(message_id or "").strip()
        if not value:
            return
        self._local_replies.append(value)
        if len(self._local_replies) > _LOCAL_REPLY_LIMIT:
            del self._local_replies[: len(self._local_replies) - _LOCAL_REPLY_LIMIT]

    # ---- 事件（宿主线程）----------------------------------------------------
    def _on_online(self, payload: Any) -> None:
        value = bool(payload)
        if value == self._online:
            return
        self._online = value
        for callback in list(self._listeners):
            try:
                callback(value)
            except Exception:
                logger.warning("SurfCore 上下线订阅者失败：%s", type(callback).__name__)

    def _on_event(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        if event.get("type") not in _PUSH_TYPES:
            return
        text = str(event.get("text") or "").strip()
        if not text:
            return
        message_id = str(event.get("messageId") or "").strip()
        if message_id and message_id in self._local_replies:
            return
        show = getattr(self._host, "show_companion_bubble", None)
        if not callable(show):
            return
        try:
            show(text)
        except Exception:
            logger.warning("SurfCore 主动消息呈现失败：%s", type(show).__name__)

    # ---- 收口 ---------------------------------------------------------------
    def stop(self) -> None:
        unsubscribes, self._unsubscribe = self._unsubscribe, []
        for unsubscribe in unsubscribes:
            try:
                unsubscribe()
            except Exception:
                logger.debug("SurfCore 陪伴线退订失败", exc_info=True)
        self._listeners.clear()


__all__ = ["CompanionBridge", "EVENT_TOPIC", "OFFLINE_HINT", "ONLINE_TOPIC"]
