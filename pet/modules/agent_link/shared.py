# -*- coding: utf-8 -*-
"""进程级共享的 Agent 联动管理器（从 ``pet/multi_window_shared.py`` 迁移）。"""
from __future__ import annotations

import logging

from .agent_link import AgentLinkManager

log = logging.getLogger("dsh-pet-standalone")


class SharedAgentLinkManager(AgentLinkManager):
    """进程级共享的 ``AgentLinkManager``：呈现扇出 + 生命周期按「任窗仍存活」处理。

    与每窗独立 manager 的差别：
    - ``shutdown()`` / ``pause()`` / ``resume()`` 为 no-op——单个桌宠窗口关闭、
      隐藏、切换角色都不该停掉其它窗共享的监视器（否则一窗退、全局断）；
    - 真正的收口只在进程级 ``stop_all()``（由模块 ``stop`` 调用）。
    """

    def __init__(self, proxy, config, **kw) -> None:
        super().__init__(proxy, config, **kw)
        self._stopped = False

    @property
    def presentation(self):
        """Compatibility facade for callers of the pre-split presentation API."""
        return self

    def show_link_bubble(self, text: str, *, important: bool = False,
                         duration_ms: int = 4500) -> None:
        """Expose presentation's historical bubble entry point."""
        self._show_link_bubble(text, important=important, duration_ms=duration_ms)

    def pause(self) -> None:
        # 单窗隐藏不停共享监视器；呈现扇出已按「可见窗」过滤
        pass

    def resume(self) -> None:
        # 共享监视器不随单窗显隐启停（呈现扇出已按可见窗过滤），但恢复显示时必须
        # 把隐藏/无宠期间到达、当时无处可投的常驻交互补投出去。
        self.redeliver_pending_interactions()

    def shutdown(self) -> None:
        # 单窗关闭/切换角色不动共享监视器；全部退出由 stop_all() 收口。
        # 基类的 GC 安全收口必须继承（parent=None 的 C++ 对象过继给 QApplication）。
        AgentLinkManager._adopt_to_app_for_gc(self)

    def stop_all(self) -> None:
        """进程级收口：幂等，只真正关停监视器一次。"""
        if self._stopped:
            return
        self._stopped = True
        try:
            super().shutdown()
        except Exception:
            log.exception("关闭共享 Agent 管理器失败")


__all__ = ["SharedAgentLinkManager"]
