# -*- coding: utf-8 -*-
"""「允许桌宠跨屏」开关：默认关、重启生效，关着时活动区只留启动那块屏。

用户口径（2026-10-17）：一张合成窗铺满整个虚拟桌面，**活动区**（宠能站的地方）
由**一个全局开关**控制，默认关（默认关 = 单显示器用户与旧行为逐位相同）；
关着时活动区只剩启动时那块屏，宠拖不过去；开关是**重启级**（进程内快照）。

位置持久化的数据语义（本文件盯住的那一条）：档案里的 ``screen_name`` 是
**屏归属**，只有有意把某只拖到另一块屏时才写（``_remember_sprite_screen``）；
位置自存（拖动收尾 / 退出 / 开局落位）只写比例与朝向。于是：

- 关掉跨屏、或原来那块屏临时不在线，都不会改写用户摆好的多屏归属；
- 重新开启并重启，各宠仍回到各自那块屏（round trip）；
- 单屏下普通拖动的比例持久化不受影响（不是"关闭时一律禁写"）。

纪律：offscreen；假屏只补**类级** ``QGuiApplication``（补实例属性会在 PySide6
对象上留影子，撤不干净）；全部断言走公开接缝（``hosts()`` / ``host_for_sprite``
/ ``move_sprite_to_screen`` / 真鼠标事件 / 真档案文件）。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
import pytest

from pet.config import Config
from pet.overlay_shell import OverlayShell
from pet.pet_sprite import PetSprite
from tests.test_overlay_hosts_multiscreen import (
    _hittable, _move, _press, _release)
from tests.helpers.overlay_shell import _SlotInstance, _teardown
from tests.test_overlay_screen_migration import FakeScreen

app = QApplication.instance() or QApplication([])

PRIMARY_GEO = (0, 0, 1920, 1080)
PRIMARY_AVAIL = (0, 0, 1920, 1040)
# 两块同高：拖拽用例沿 y 平移时身体中心仍落在副屏里（副屏比主屏矮时，从主屏
# 右下角出发的水平拖动会擦过副屏底边之下，"跨不过去"就成了位置问题而不是开关问题）。
SECONDARY_GEO = (1920, 0, 1920, 1080)
SECONDARY_AVAIL = (1920, 0, 1920, 1040)


def two_screens():
    return (FakeScreen(PRIMARY_GEO, PRIMARY_AVAIL, name="DISPLAY1"),
            FakeScreen(SECONDARY_GEO, SECONDARY_AVAIL, name="DISPLAY2"))


def _screen_of(sprite):
    """这只宠当前所在屏（由用例的壳提供，见 ``_shell`` 注入的 resolver）。"""
    return _CURRENT[0]._screen_of_sprite(sprite)


_CURRENT = [None]


def _install(monkeypatch, screens):
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: list(screens)))
    monkeypatch.setattr(QGuiApplication, "primaryScreen",
                        staticmethod(lambda: screens[0]))


def _config(tmp_path, *, allow_cross_screen=False, **values) -> Config:
    cfg = Config(base=tmp_path)
    cfg.set("allow_cross_screen", allow_cross_screen)
    for key, value in values.items():
        cfg.set(key, value)
    cfg.save()
    return cfg


def _activity_of(shell, screen):
    for candidate, rect in shell._main_host.activity:
        if candidate is screen:
            return rect
    raise AssertionError("screen not in activity")


def _profile(config_dir, instance_id):
    path = config_dir / f"config-{instance_id}.json"
    assert path.exists(), f"missing profile: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _shell(cfg, screen) -> OverlayShell:
    shell = OverlayShell(
        app, _SlotInstance(cfg), screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    _CURRENT[0] = shell
    return shell


def _seed_two_pets(config_dir, *, slot0_screen=None, slot1_screen=None):
    """预置两只活跃宠（slot0 + slot1）与各自的屏记忆，供复活路径读。

    ``config_dir`` 必须是 ``Config.dir``（= ``base/<应用目录>``）：档案、活跃清单
    与几何都落在这里，直接拿 ``tmp_path`` 是另一个目录。
    """
    from pet import pet_profiles

    for slot, screen_name in ((0, slot0_screen), (1, slot1_screen)):
        pet_profiles.write_profile_settings(config_dir, slot, {"scale": 0.5})
        if screen_name is not None:
            pet_profiles.write_profile_geometry(
                config_dir, slot, {"rx": 0.25, "ry": 0.75, "screen_name": screen_name})
    pet_profiles.save_active_set(config_dir, [0, 1], on_broken="backup-overwrite")


# ---------------------------------------------------------------- 1. 默认与重启级
def test_switch_defaults_off_and_the_shell_snapshots_it(tmp_path, monkeypatch):
    primary, _secondary = two_screens()
    _install(monkeypatch, [primary])
    cfg = _config(tmp_path)
    assert cfg.get("allow_cross_screen") is False, "出厂默认必须是关"
    shell = _shell(cfg, primary)
    try:
        assert shell._cross_screen_allowed is False
        assert len(shell.hosts()) == 1
        assert shell.overlay is shell.host_for_sprite(shell.sprite).overlay
    finally:
        _teardown(shell)




# ---------------------------------------------------------------- 2. 关闭 = 单屏一窗






# ---------------------------------------------------------------- 3. 位置持久化语义
def test_off_keeps_a_cross_screen_drag_inside_the_started_screen(tmp_path, monkeypatch):
    """真鼠标拖到缝的另一侧：宠被活动区（只剩启动那块屏）钳住，拖不过去。"""
    primary, secondary = two_screens()
    _install(monkeypatch, [primary, secondary])
    cfg = _config(tmp_path, allow_cross_screen=False)
    shell = _shell(cfg, primary)
    try:
        main = shell.sprite
        overlay = shell.overlay
        origin = QPointF(overlay.geometry().topLeft())
        _hittable(main)
        hit = QPointF(main.rect().center())
        overlay.mousePressEvent(_press(hit, origin + hit))
        cursor = origin + hit
        for _ in range(16):
            cursor = QPointF(cursor.x() + 40.0, cursor.y())
            overlay.mouseMoveEvent(_move(cursor - origin, cursor))
            assert _screen_of(main) is primary

        assert secondary.geometry().contains(cursor.toPoint())
        assert len(shell.hosts()) == 1
        assert [screen for screen, _r in shell._main_host.activity] == [primary]
        assert main in overlay.sprites
        body_center = QPointF(main.body_rect().center())
        assert primary.availableGeometry().contains(body_center.toPoint())

        overlay.mouseReleaseEvent(_release(cursor - origin, cursor))
        shell.save_position()
        profile = _profile(cfg.dir, "slot-0")
        assert 0.0 <= profile["rx"] <= 1.0 and 0.0 <= profile["ry"] <= 1.0
        assert profile.get("screen_name") is None
    finally:
        _teardown(shell)


def test_off_still_persists_ordinary_drag_ratios(tmp_path, monkeypatch):
    """关闭跨屏 ≠ 禁写位置：单屏普通拖动照旧逐次落盘（既有口径不受影响）。"""
    primary, _secondary = two_screens()
    _install(monkeypatch, [primary, _secondary])
    cfg = _config(tmp_path, allow_cross_screen=False)
    shell = _shell(cfg, primary)
    try:
        main = shell.sprite
        _drag_on_current_screen(shell, main)
        shell.save_position()
        profile = _profile(cfg.dir, "slot-0")
        body = main.body_rect()
        bounds = _activity_of(shell, primary)
        expected_rx = (body.x() + body.width() / 2.0 - bounds.left()) / bounds.width()
        assert profile["rx"] == pytest.approx(expected_rx, abs=0.01)
    finally:
        _teardown(shell)


def _drag_on_current_screen(shell, sprite, *, dx=-30.0, dy=-20.0, steps=6):
    """在这只当前所在那块屏的窗里真鼠标拖一段（会话与宿主同一个窗）。"""
    overlay = shell.host_for_sprite(sprite).overlay
    origin = QPointF(overlay.geometry().topLeft())
    _hittable(sprite)
    hit = QPointF(sprite.rect().center())
    overlay.mousePressEvent(_press(hit, origin + hit))
    cursor = origin + hit
    for _ in range(steps):
        cursor = QPointF(cursor.x() + dx, cursor.y() + dy)
        overlay.mouseMoveEvent(_move(cursor - origin, cursor))
    overlay.mouseReleaseEvent(_release(cursor - origin, cursor))
    return cursor










