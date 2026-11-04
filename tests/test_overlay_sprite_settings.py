# -*- coding: utf-8 -*-
"""config → sprite/behavior 同步点回归（DS 全量审查 M6/M7/M9/M10）。

M6：no_move/playback_speed 此前启动不读 config、refresh 不覆盖——开箱行为
不一致 + 重启即丢。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

import tests.test_overlay_window_capabilities as cap
import tests.test_sprite_menu_facade as fac
from pet.overlay_shell import OverlayShell
from pet.pet_sprite import PetSprite

app = QApplication.instance() or QApplication([])


def _make_shell(tmp_path, values=None):
    config = cap.CapConfig(tmp_path, values or {})
    instance = cap.CapInstance(config)
    screen = cap.FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    shell = OverlayShell(
        app, instance, screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    lib = fac.RichLibrary()
    shell.lib = lib
    shell.sprite.library = lib
    return shell, config


def test_config_syncs_to_sprite_at_build(tmp_path):
    """启动即按 config 应用：两键全部生效。"""
    shell, _config = _make_shell(tmp_path, {
        "no_move": True,
        "playback_speed": 1.5,
    })
    try:
        sprite = shell.sprite
        assert sprite.playback_speed == 1.5
        assert shell.behavior.no_move is True
        shell._delete_runtime_marker()
    finally:
        shell._delete_runtime_marker()


def test_refresh_settings_resyncs_sprite(tmp_path):
    """设置页改完经 refresh_settings 即生效（不重启）。"""
    shell, config = _make_shell(tmp_path, {})
    try:
        config.set("playback_speed", 0.5)
        shell.refresh_settings()
        assert shell.sprite.playback_speed == 0.5
        shell._delete_runtime_marker()
    finally:
        shell._delete_runtime_marker()




def test_stop_halts_self_talk_timer(tmp_path):
    """M9：shell.stop() 后 self_talk 定时器不再自我重排。"""
    shell, _config = _make_shell(tmp_path, {
        "self_talk_enabled": True,
        "self_talk_texts": ["台词"],
        "self_talk_min_interval": 5.0,
        "self_talk_max_interval": 5.0,
    })
    try:
        shell.overlay.show()
        assert shell._self_talk_timer.isActive() is True
        shell.start()
        shell.stop()
        assert shell._self_talk_timer.isActive() is False
        shell._delete_runtime_marker()
    finally:
        timer = getattr(shell, "_self_talk_timer", None)
        if timer is not None:
            timer.stop()
        shell._delete_runtime_marker()


