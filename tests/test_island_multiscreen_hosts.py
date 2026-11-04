# -*- coding: utf-8 -*-
"""灵动岛在多窗（混合缩放）下的宿主绑定与「全体」可见性。

混合 DPI + 允许跨屏时一块屏一张合成窗（``OverlayShell._multi_window()``）：
「还有没有宠可见 / 显示桌宠」必须看**全部**宿主的成员：主窗空着而副屏有宠不算
"一只都没有"，反过来副屏那几只逐只藏光也不算"还有"。

本机通常只有一块屏，故这里用假屏驱动真实的宿主创建与壳层可见性判据。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from tests.test_overlay_hosts_multiscreen import (
    _install_screens,
    _make_shell,
    _two_screens,
)

app = QApplication.instance() or QApplication([])

def _mixed_shell(tmp_path, monkeypatch):
    """混合缩放双屏：A@100% + B@200%（= 每块屏一张合成窗）。"""
    a, b = _two_screens()
    b.set_rects((1920, 0, 1920, 1080), (1920, 0, 1920, 1040), dpr=2.0)
    _install_screens(monkeypatch, a, b)
    shell = _make_shell(tmp_path, a)
    assert len(shell.hosts()) == 2, "前提：混合缩放 = 每块屏一张窗"
    return shell, a, b


def _app_shell(shell) -> AppShell:
    """AppShell 桩：可见性判据只碰 ``_overlay_shell`` / ``_instances`` / ``island``。"""
    stub = AppShell.__new__(AppShell)
    stub._instances = []
    stub._overlay_shell = shell
    stub.island = None
    stub.island_chat = None
    return stub


def _cleanup(shell) -> None:
    shell.stop()
    QApplication.processEvents()


def _two_pets_a_and_b(shell, a, b):
    """主宠留在 A，新生那只有意搬到 B（两窗各有成员）。"""
    shell._show_all_hosts()
    shell.spawn_pet()
    child = shell._spawned[0]
    assert shell.move_sprite_to_screen(child, b) is True
    assert shell.host_for_sprite(shell.sprite).screen is a
    assert shell.host_for_sprite(child).screen is b
    return shell.sprite, child


# ---------------------------------------------------------------- 全体可见性
def test_main_window_pets_hidden_but_secondary_pet_visible(tmp_path, monkeypatch):
    """主窗的宠全隐藏、副屏仍有可见宠 → 仍算「有可见宠」。"""
    shell, a, b = _mixed_shell(tmp_path, monkeypatch)
    try:
        main, child = _two_pets_a_and_b(shell, a, b)
        stub = _app_shell(shell)

        shell.set_sprite_visible(main, False)

        assert main.visible is False
        assert child.visible is True
        assert shell._main_host.overlay.sprites == [main], "前提：主窗只剩这只（已藏）"
        assert AppShell._overlay_sprite_visible(shell) is True
        assert AppShell._aggregate_pet_visible(stub) is True
    finally:
        _cleanup(shell)


def test_every_pet_on_secondary_and_each_hidden_is_not_visible(tmp_path, monkeypatch):
    """全部宠都在副屏、逐只藏光 → 判「无可见宠」（主窗空 ≠ 一只都没有）。"""
    shell, a, b = _mixed_shell(tmp_path, monkeypatch)
    try:
        main, child = _two_pets_a_and_b(shell, a, b)
        stub = _app_shell(shell)
        assert shell.move_sprite_to_screen(main, b) is True
        assert shell._main_host.overlay.sprites == [], "前提：主窗已空"

        for sprite in (main, child):
            shell.set_sprite_visible(sprite, False)

        assert AppShell._overlay_sprite_visible(shell) is False
        assert AppShell._aggregate_pet_visible(stub) is False
    finally:
        _cleanup(shell)


def test_show_pets_from_island_chat_restores_secondary_pets(tmp_path, monkeypatch):
    """「显示桌宠」把**副屏**被藏的宠也叫回来（不只恢复主窗）。"""
    shell, a, b = _mixed_shell(tmp_path, monkeypatch)
    try:
        main, child = _two_pets_a_and_b(shell, a, b)
        stub = _app_shell(shell)
        assert shell.move_sprite_to_screen(main, b) is True
        for sprite in (main, child):
            shell.set_sprite_visible(sprite, False)
        main_host = shell.host_for_screen(b)
        assert AppShell._overlay_sprite_visible(shell) is False

        AppShell._show_pets_from_island_chat(stub)

        assert shell._any_host_visible(), "窗要回来"
        assert all(sprite.visible for sprite in main_host.overlay.sprites), (
            "副屏被藏的宠也必须恢复")
        assert AppShell._overlay_sprite_visible(shell) is True
    finally:
        _cleanup(shell)
