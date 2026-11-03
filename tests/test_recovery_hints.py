# -*- coding: utf-8 -*-
"""“小白找不回来”开关的恢复提示回归测试（issue #74）。

覆盖危险方向：开启「鼠标穿透」后桌宠不可点击 → 应在开启瞬间提示去托盘/设置里恢复。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.window import PetWindow
from tests.test_window_pause import FakeLibrary


def _qapp():
    return QApplication.instance() or QApplication([])


def _make_win(tmp_path, monkeypatch):
    _qapp()
    win = PetWindow(FakeLibrary(), Config(base=tmp_path))
    # 避免穿透切换真的重建原生窗口/调用 Win32，本组测试只关心提示。
    monkeypatch.setattr(win, "_apply_effective_mouse_through", lambda enabled=None: None)
    return win


def test_enabling_mouse_through_shows_recovery_hint(tmp_path, monkeypatch):
    app = _qapp()
    win = _make_win(tmp_path, monkeypatch)
    try:
        hints = []
        monkeypatch.setattr(win, "isVisible", lambda: True)
        monkeypatch.setattr(win, "show_bubble", lambda text, **kw: hints.append(text))

        win.set_mouse_through(True)
        assert len(hints) == 1, "开启鼠标穿透应提示一次恢复位置"
        assert "鼠标穿透" in hints[0]

        # 关闭方向不需要提示；再次开启才提示。
        win.set_mouse_through(False)
        win.set_mouse_through(True)
        assert len(hints) == 2
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_enabling_mouse_through_hint_suppressed_when_hidden_or_suppressed(tmp_path, monkeypatch):
    app = _qapp()
    win = _make_win(tmp_path, monkeypatch)
    try:
        hints = []
        monkeypatch.setattr(win, "isVisible", lambda: True)
        monkeypatch.setattr(win, "show_bubble", lambda text, **kw: hints.append(text))

        win._bubble_suppressed = True
        win.set_mouse_through(True)
        assert hints == [], "设置窗口打开（气泡抑制）期间不应弹恢复提示"

        win._bubble_suppressed = False
        monkeypatch.setattr(win, "isVisible", lambda: False)
        win.set_mouse_through(False)
        win.set_mouse_through(True)
        assert hints == [], "桌宠隐藏时不应尝试在不可见窗口上弹提示"
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
