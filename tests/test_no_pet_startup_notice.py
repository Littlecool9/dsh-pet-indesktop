# -*- coding: utf-8 -*-
"""有宠物启动时不得打出「没有任何宠物」的 WARN（单宠 slot0 对照）。"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import tests.test_overlay_window_capabilities as cap
from pet.overlay_shell import OverlayShell

app = QApplication.instance() or QApplication([])


def _shell(tmp_path, screen):
    return OverlayShell(
        app, cap.CapInstance(cap.CapConfig(tmp_path, {"scale": 0.5})), screen=screen,
        sprite_factory=lambda lib, pos, scale: cap.CapSprite(lib, pos, scale))


def test_overlay_with_a_pet_keeps_quiet(tmp_path, caplog):
    """对照：有宠物时不打这条 WARN（否则日志噪音会把真现场埋掉）。"""
    screen = cap.FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    with caplog.at_level(logging.WARNING, logger="pet.overlay_shell"):
        shell = _shell(tmp_path, screen)
    try:
        assert shell._all_sprites(), "前提：默认档案下 slot0 应当建起来"
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("没有任何宠物" in message for message in warnings), warnings
    finally:
        shell.stop()
