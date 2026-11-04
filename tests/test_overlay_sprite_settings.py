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


def test_spawned_sprite_gets_config_sync(tmp_path):
    """spawn 的子肥鱼同样按 config 应用（不是只吃构造默认）。"""
    shell, _config = _make_shell(tmp_path, {"playback_speed": 0.75})
    try:
        shell._spawn_slot(7)
        spawned = shell._spawned[-1]
        assert spawned.playback_speed == 0.75
        lib = shell._spawned_libs.pop(spawned)
        shutdown = getattr(lib, "shutdown", None)
        if callable(shutdown):
            shutdown()
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


def test_scale_applies_at_runtime(tmp_path):
    """设置页改大小 → refresh_settings 即生效；子宠按**它自己**的 slot 配置取源。

    B7b 改写：原断言锁"子宠 scale 本批不动（归 B7b）"——那是 B7a 的过渡口径。
    新契约 = 旧版"每只宠各读自己那份 config"：子宠的缩放/速率由它自己的
    ``config-slot-N.json`` 决定，主宠的设置不再拖走子宠，反之亦然。
    """
    from tests.helpers import overlay_shell as toggle
    from pet import overlay_spawn_state as ovs

    shell, cfg = toggle._make_slot_shell(tmp_path, scale=0.5)
    try:
        assert shell.sprite.scale == pytest.approx(0.5)
        # 主宠的"大小"同样是每宠键：真值在 ``config-slot-0.json``（生产里设置页经
        # SlotRoutedConfig 写它；裸 ``Config.set`` 只改全局那份，全局保存会把每宠键
        # 过滤掉，改不动任何一只宠）。
        assert ovs.write_slot_setting(cfg.dir, 0, "scale", 1.0,
                                      user_customized=True)
        shell.refresh_settings()
        assert shell.sprite.scale == pytest.approx(1.0)

        shell.spawn_pet()
        child = shell._spawned[0]
        # 这只子肥鱼自己的设置页保存了 0.5 → 只有它按 0.5 走
        assert ovs.write_slot_setting(cfg.dir, 1, "scale", 0.5,
                                      user_customized=True)
        shell._on_settings_command_dir_changed(str(cfg.dir))
        assert child.scale == pytest.approx(0.5)
        assert shell.sprite.scale == pytest.approx(1.0)

        # slot0 档案再改：主宠跟着变，子宠按自己那份不变
        assert ovs.write_slot_setting(cfg.dir, 0, "scale", 0.72,
                                      user_customized=True)
        shell.refresh_settings()
        assert shell.sprite.scale == pytest.approx(0.72)
        assert child.scale == pytest.approx(0.5)
    finally:
        toggle._teardown(shell)
