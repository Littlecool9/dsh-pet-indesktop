# -*- coding: utf-8 -*-
"""Windows 逐像素穿透轮询拖拽降频回归测试（B2）。

背景：WindowsPerPixelInputController 每 10ms 轮询 QCursor.pos() 更新穿透
样式，但拖拽（`_press_global` 非 None）期间 `should_click_through` 恒返回
False，轮询纯属空转。要求：拖拽期间降频（100ms），松手立即按光标位置重新
定档（M12b 两段式：盒内 10ms / 盒外 50ms，见
test_input_controller_poll_tiers.py）并强制刷新一次穿透状态；非拖拽时行为
不变；仅 Windows 路径受影响。

真实 overlay 窗口上的按-拖-放接线由 tests/test_overlay_window.py 的
``test_press_global_and_drag_polling_protocol`` 锁定（旧 PetWindow 路径已删除）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet import platform_win as platform_win_mod


def _qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class _FakeWindow:
    def winId(self):
        return 123

    def mapFromGlobal(self, point):
        return point

    def _is_transparent_at(self, point):
        return point.x() >= 50


def test_controller_drag_slows_polling_and_restores_on_release():
    """控制器自身：拖拽降频；松手恢复原频率并强制刷新一次穿透状态。"""
    _qapp()
    fake = _FakeWindow()
    fake.mouse_through = False
    fake._press_global = None
    fake.isVisible = lambda: True
    fake.width = lambda: 100
    fake.height = lambda: 80

    controller = object.__new__(platform_win_mod.WindowsPerPixelInputController)
    controller._window = fake
    controller._timer = QTimer()
    controller._timer.setInterval(
        platform_win_mod.WindowsPerPixelInputController.NORMAL_POLL_INTERVAL_MS
    )
    refreshes = []
    controller.refresh = lambda: refreshes.append(1)

    assert controller._timer.interval() == (
        platform_win_mod.WindowsPerPixelInputController.NORMAL_POLL_INTERVAL_MS
    )
    controller.set_drag_active(True)
    assert controller._timer.interval() == (
        platform_win_mod.WindowsPerPixelInputController.DRAG_POLL_INTERVAL_MS
    )
    assert refreshes == [], "降频本身不应触发额外刷新"

    controller.set_drag_active(False)
    assert controller._timer.interval() == (
        platform_win_mod.WindowsPerPixelInputController.NORMAL_POLL_INTERVAL_MS
    )
    assert refreshes == [1], "松手恢复频率时应强制刷新一次穿透状态"

    # 非拖拽状态重复恢复是 no-op：不重复刷新、不改变频率
    controller.set_drag_active(False)
    assert controller._timer.interval() == (
        platform_win_mod.WindowsPerPixelInputController.NORMAL_POLL_INTERVAL_MS
    )
    assert refreshes == [1]

    controller.set_drag_active(True)
    assert controller._timer.interval() == (
        platform_win_mod.WindowsPerPixelInputController.DRAG_POLL_INTERVAL_MS
    )
