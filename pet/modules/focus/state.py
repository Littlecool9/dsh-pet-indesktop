# -*- coding: utf-8 -*-
"""专注模块对核心暴露的服务对象（只读状态 + UI 工厂）。

核心（灵动岛 / 行为 / 主动识屏 / 自言自语）不再直接 import 本模块的会话：
它们通过 ``shell._module_host.get("focus")`` 拿这个对象。模块缺失时拿不到
对象，调用方一律按“专注关闭”处理——与用户没开专注完全同义。
"""
from __future__ import annotations

from typing import Any

from .session import PHASE_NAMES


class FocusService:
    """``host.provide("focus", ...)`` 的服务对象。

    状态访问器只读；开始/暂停/结束供模块自己的菜单与岛卡片调用，核心读方
    不需要也不应该写状态。监听器回调用于卡片/岛的实时刷新。
    """

    def __init__(self, session, config: Any = None) -> None:
        self._session = session
        self.config = config

    # ---- 只读状态 -----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self._session.engaged)

    @property
    def engaged(self) -> bool:
        return bool(self._session.engaged)

    @property
    def focusing(self) -> bool:
        return bool(self._session.focusing)

    @property
    def owns_observation(self) -> bool:
        return bool(self._session.owns_observation)

    @property
    def phase(self) -> str:
        return str(self._session.phase)

    @property
    def status(self) -> str:
        return str(self._session.status)

    @property
    def completed(self) -> int:
        return int(self._session.completed)

    @property
    def observation(self) -> str:
        return str(self._session.observation)

    def remaining_seconds(self) -> int:
        return int(self._session.remaining_seconds())

    def label(self) -> str:
        return str(self._session.label())

    def phase_name(self) -> str:
        return PHASE_NAMES.get(self._session.phase, PHASE_NAMES["idle"])

    # ---- 刷新订阅 -----------------------------------------------------------
    def add_listener(self, callback) -> None:
        self._session.add_listener(callback)

    def remove_listener(self, callback) -> None:
        self._session.remove_listener(callback)

    # ---- 模块自己的 UI / 命令 ----------------------------------------------
    def create_controls(self, config, parent=None):
        from .ui import FocusControls

        return FocusControls(self, config, parent)

    def build_menu(self, menu, pet):
        from .ui import build_focus_menu

        return build_focus_menu(menu, pet, self)

    def toggle(self, config=None) -> None:
        cfg = config if config is not None else self.config
        session = self._session
        if session.status == "running":
            session.pause()
        else:
            focus_cfg = cfg.get("focus_mode") if hasattr(cfg, "get") else None
            session.start(focus_cfg)

    def stop(self) -> None:
        self._session.stop()


__all__ = ["FocusService"]
