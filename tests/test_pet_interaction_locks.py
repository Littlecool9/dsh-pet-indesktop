# -*- coding: utf-8 -*-
"""弹弓几何（纯数学）与边缘探头点击音效抑制（sprite/overlay 宿主）。

旧 PetWindow 的锁定位 / SHIFT 拖拽 / 不透明度 / 弹弓会话由 overlay 的
``test_overlay_dead_switches`` 与 ``test_sprite_slingshot`` 覆盖；本文件保留
两条仍属于纯逻辑/overlay 接线的回归：
- 弹弓锚点与方向形变（``sprite_slingshot.trajectory_anchor`` /
  ``physics.slingshot_deformation``）；
- 探头消费点击时不播点击音效（``ShellOverlayWindow.mouseReleaseEvent``）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import physics
from pet.sprite_slingshot import trajectory_anchor

app = QApplication.instance() or QApplication([])


def test_slingshot_trajectory_anchor_starts_at_character_edge():
    character = QRect(10, 8, 100, 100)
    anchor = trajectory_anchor(character, QPointF(1, 1))
    # QRect's right/bottom are inclusive, so the ray exits at (109, 107).
    assert anchor == QPointF(109.0, 107.0)


def test_slingshot_geometry_uses_smooth_directional_deformation():
    horizontal = physics.slingshot_deformation(160.0, 0.0, 1.0)
    vertical = physics.slingshot_deformation(0.0, -160.0, 1.0)
    size = 100
    assert round(size * horizontal[0]) == round(size * 1.3)
    assert round(size * horizontal[1]) == round(size / 1.3)
    assert round(size * vertical[0]) == round(size / 1.3)
    assert round(size * vertical[1]) == round(size * 1.3)


def test_slingshot_band_points_use_visible_edge_and_mouse_endpoint():
    character = QRect(10, 8, 100, 100)
    center = character.center()
    mouse = QPointF(4.0, 57.0)
    start = trajectory_anchor(character, mouse - QPointF(center))
    assert start == QPointF(9.0, 57.0)
    assert (start, mouse) == (QPointF(9.0, 57.0), QPointF(4.0, 57.0))


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
