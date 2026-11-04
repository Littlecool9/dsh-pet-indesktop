# -*- coding: utf-8 -*-
"""窗口位置持久化中仍然存在的 window_placement 件测试。

旧 PetWindow 的 restore/screen-retry 机器已随 pet/window.py 删除；跨屏落位
由 overlay 壳层负责（tests/test_overlay_spawn.py、tests/test_overlay_screen_migration.py
等锁定）。这里只保留仍被 overlay 复用的 ``save_position`` 与 ``screen_available``。
"""
from __future__ import annotations

from PySide6.QtCore import QRect

from pet import window_placement


class _Config(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value

    def save(self):
        pass


class _Screen:
    def __init__(self, name, geometry):
        self._name = name
        self._geometry = geometry

    def name(self):
        return self._name

    def availableGeometry(self):
        return self._geometry

    def devicePixelRatio(self):
        return 1.0


def test_save_position_records_secondary_screen():
    secondary = _Screen("secondary", QRect(1920, 0, 1920, 1080))

    class FakePet:
        cfg = _Config()
        facing = "left"
        scale = 1.0
        _w = 220
        _h = 260

        def _screen_available(self):
            return secondary

        def x(self):
            return 2500

        def y(self):
            return 500

    pet = FakePet()
    window_placement.save_position(pet)

    assert pet.cfg["screen_name"] == "secondary"


def test_named_screen_lookup_and_config_persistence(tmp_path, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from pet.config import Config

    primary = _Screen("primary", QRect(0, 0, 1920, 1080))
    secondary = _Screen("secondary", QRect(1920, 0, 1920, 1080))
    monkeypatch.setattr(
        QGuiApplication, "screens", staticmethod(lambda: [primary, secondary])
    )

    class FakePet:
        def screen(self):
            return primary

    assert window_placement.screen_available(FakePet(), "secondary") is secondary

    config = Config(tmp_path)
    config.set("screen_name", "secondary")
    config.save()
    from pet.settings_slot_config import route_settings_config

    assert route_settings_config(Config(tmp_path, instance_id="slot-0")).get("screen_name") == "secondary"


def test_save_position_skipped_while_awaiting_saved_screen():
    """等待副屏上线期间：save_position 不得把临时落脚屏的坐标/屏名写回配置。"""
    primary = _Screen("primary", QRect(0, 0, 1920, 1080))

    class FakePet:
        cfg = _Config(rx=0.5, ry=0.5, screen_name="secondary")
        facing = "left"
        scale = 1.0
        _w = 220
        _h = 260
        _awaiting_saved_screen = "secondary"  # 正在等副屏上线

        def _screen_available(self):
            return primary

        def x(self):
            return 100

        def y(self):
            return 200

    pet = FakePet()
    window_placement.save_position(pet)
    # 副屏坐标与屏名必须原样保留
    assert pet.cfg["screen_name"] == "secondary"
    assert pet.cfg["rx"] == 0.5 and pet.cfg["ry"] == 0.5

    pet._awaiting_saved_screen = None  # 恢复完成后正常保存
    window_placement.save_position(pet)
    assert pet.cfg["screen_name"] == "primary"
