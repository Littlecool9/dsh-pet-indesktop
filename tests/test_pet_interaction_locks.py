# -*- coding: utf-8 -*-
"""边缘探头点击音效抑制（sprite/overlay 宿主）。

旧 PetWindow 的锁定位 / SHIFT 拖拽 / 不透明度由 overlay 的
``test_overlay_dead_switches`` 覆盖；本文件保留探头消费点击时不播点击音效
（``ShellOverlayWindow.mouseReleaseEvent``）的回归。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def _click(shell, point):
    pos = QPointF(point)
    for event_type, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(
            event_type, pos, pos, Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        if event_type == QEvent.Type.MouseButtonPress:
            shell.overlay.mousePressEvent(event)
        else:
            shell.overlay.mouseReleaseEvent(event)


def test_edge_probe_click_does_not_play_click_sound(tmp_path, monkeypatch):
    """边缘探头激活时的点击被探头消费，不播点击音效；普通点击仍播放。"""
    import tests.test_sprite_edge_probe as probe_mod
    from pet.sprite_edge_probe import EDGE_ENTER_MS, EDGE_REST_SECONDS, PEEKING

    clock = probe_mod.FakeClock()
    shell = probe_mod._shell_with_probe(tmp_path, clock)
    sprite = shell.sprite
    try:
        sprite.bind_clip("idle1")
        sprite._rebuild_pixmap()
        bounds = QRect(shell._bounds)
        sprite.set_pos(QPointF(0.0, bounds.y() + 400.0))
        probe_mod._probe_ticks(
            shell._probe, clock, sprite,
            EDGE_REST_SECONDS + EDGE_ENTER_MS / 1000.0 + 0.2)
        assert shell._probe.mode_of(sprite) == PEEKING

        played: list = []
        shell.overlay.click_feedback = lambda: None
        monkeypatch.setattr(
            shell._sound, "on_click",
            lambda target=None: played.append(target))

        point = sprite.rect().center()
        _click(shell, point)
        assert played == [], "探头消费点击时不得播点击音效"

        # 探头未激活：普通点击照常播放（落点 = 被点 sprite）。
        shell._probe.cancel(sprite, "test")
        sprite._rebuild_pixmap()
        _click(shell, point)
        assert played == [sprite]
    finally:
        shell._delete_runtime_marker()


def test_drag_does_not_play_click_sound_but_click_does(tmp_path):
    """overlay 单击才触发点击音效通道；拖拽松手不得误响。"""
    import tests.test_sprite_menu_facade as fac

    shell, _lib = fac._make_shell(tmp_path)
    sprite = shell.sprite
    try:
        sprite.bind_clip("idle1")
        sprite._rebuild_pixmap()
        played: list = []
        shell.overlay.click_feedback = lambda: played.append(1)

        def press(pos):
            return QMouseEvent(
                QEvent.Type.MouseButtonPress, pos, pos,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)

        def move(pos):
            return QMouseEvent(
                QEvent.Type.MouseMove, pos, pos,
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)

        def release(pos):
            return QMouseEvent(
                QEvent.Type.MouseButtonRelease, pos, pos,
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier)

        center = QPointF(sprite.rect().center())
        shell.overlay.mousePressEvent(press(center))
        shell.overlay.mouseMoveEvent(move(center + QPointF(300, 60)))
        shell.overlay.mouseReleaseEvent(release(center + QPointF(300, 60)))
        assert played == [], "拖拽不得触发点击音效"

        sprite._rebuild_pixmap()
        center = QPointF(sprite.rect().center())
        shell.overlay.mousePressEvent(press(center))
        shell.overlay.mouseReleaseEvent(release(center))
        assert played == [1], "单击必须触发点击音效"
    finally:
        shell._delete_runtime_marker()
