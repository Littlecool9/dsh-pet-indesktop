# -*- coding: utf-8 -*-
"""窗口渲染链中仍由 overlay/sprite 拓扑复用的纯件测试。

旧 PetWindow 的 mask/帧重建语义已迁到 PetSprite（见 tests/test_sprite_dpr.py、
tests/test_pet_sprite_hardening.py、tests/test_pet_sprite_dirty_rect.py）。
本文件只保留两个仍然存在的平台侧件：

- ``pet.platform_win.WindowsPerPixelInputController``（逐像素命中）；
- ``pet.platform_win._set_windows_click_through``（保留其它扩展样式位）；
- ``pet.window_placement.visible_content_rect``（可见角色区换算全局坐标）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from pet import platform_win
from pet import window_placement


def _qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_input_controller_returns_pixel_hit_result():
    _qapp()

    class FakeWindow:
        def winId(self):
            return 123

        def mapFromGlobal(self, point):
            return point

        def _is_transparent_at(self, point):
            return point.x() >= 50

    fake = FakeWindow()
    fake.mouse_through = False
    fake._press_global = None
    fake.isVisible = lambda: True
    fake.width = lambda: 100
    fake.height = lambda: 80
    controller = object.__new__(platform_win.WindowsPerPixelInputController)
    controller._window = fake
    assert controller.should_click_through(QPoint(20, 20)) is False
    assert controller.should_click_through(QPoint(70, 20)) is True
    fake._press_global = QPoint(70, 20)
    assert controller.should_click_through(QPoint(70, 20)) is False


def test_windows_click_through_preserves_other_extended_styles():
    class FakeUser32:
        def __init__(self):
            self.style = 0x00080080  # WS_EX_LAYERED | WS_EX_TOOLWINDOW
            self.writes = []

        def GetWindowLongW(self, hwnd, index):
            assert (hwnd, index) == (123, platform_win.GWL_EXSTYLE)
            return self.style

        def SetWindowLongW(self, hwnd, index, style):
            self.style = style
            self.writes.append((hwnd, index, style))

    user32 = FakeUser32()
    assert platform_win._set_windows_click_through(123, True, user32) is True
    assert user32.style == 0x000800A0
    assert platform_win._set_windows_click_through(123, True, user32) is False
    assert len(user32.writes) == 1
    assert platform_win._set_windows_click_through(123, False, user32) is True
    assert user32.style == 0x00080080


def test_visible_content_rect_uses_character_region():
    _qapp()

    class FakeWithGeometry:
        def frameGeometry(self):
            return QRect(100, 100, 64, 36)

        def character_local_region(self):
            return QRect(4, 3, 20, 20)

        def mask(self):
            return QRegion()

    rect = window_placement.visible_content_rect(FakeWithGeometry())
    assert rect == QRect(104, 103, 20, 20)
