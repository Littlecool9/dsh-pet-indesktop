# -*- coding: utf-8 -*-
"""托盘「AI 设置 / 桌宠设置」入口：菜单先关、回调延到菜单跟踪会话之后。

背景：托盘菜单此前是裸 ``menu.addAction(text, callback)``——回调在原生菜单跟踪
会话里**内联执行**。托盘菜单是系统原生菜单，跟踪会话中新建/激活
窗口会被系统抑制（issue #4 家族：点了没反应，再点一次才对；右键菜单路径早已
用 ``close_on_trigger`` + ``exec()`` 返回后派发解决，托盘菜单没有 ``exec()``
收口点，故走 ``shared.run_after_menu_closed``：菜单先关、等它真的不在了再执行）。

同一口径覆盖托盘菜单里**会改窗面**的其余条目（显示/隐藏、回到右下角、切换角色、
鼠标穿透、开机自启、灵动岛）：它们的旧接法是裸 ``menu.addAction``(回调) 或
``toggled``(回调)，都在菜单跟踪会话里内联执行——显示/隐藏要 ``show()`` 桌宠窗、
切换角色要重建角色窗面（与 issue #4 同病），其余条目改的是窗面/冒泡/系统登录项，
统一到「菜单先关、回调延后」这一条契约上。

验收口径：菜单可见期内回调不得执行；点击后菜单先关；菜单关闭后执行一次。
时序纪律：事件同步 + 宽预算轮询（``app.processEvents()``），不赌固定 sleep。
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pet.config import Config

app = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _entry(menu, label: str):
    for action in menu.actions():
        if action.text() == label:
            return action
    raise AssertionError(
        f"托盘菜单缺项 {label}；实际: {[a.text() for a in menu.actions()]}")


def _open_menu(menu) -> None:
    menu.show()
    app.processEvents()
    assert menu.isVisible(), "前提：菜单在显示态"


def _submenu(menu, label: str):
    for action in menu.actions():
        if action.text() == label and action.menu() is not None:
            return action.menu()
    raise AssertionError(
        f"托盘菜单缺子菜单 {label}；实际: {[a.text() for a in menu.actions()]}")


# ------------------------------------------------ overlay 托盘全条目：同一契约
def _overlay_tray(tmp_path):
    """overlay 拓扑的托盘 + 菜单（overlay 下用户**实际看到**的那一份）。

    overlay 不构造 PetWindow，托盘挂在 ``OverlayShell`` 上：先前这批修复只覆盖了
    legacy 的 ``AppShell._build_tray``，本文件的其余用例也都打在 legacy 托盘上——
    于是 overlay 拓扑下的裸 ``addAction`` / ``toggled`` 一直没被回归覆盖。
    """
    from tests.helpers.overlay_shell import _make_persistent_shell

    shell, _made = _make_persistent_shell(tmp_path)
    menu = shell.tray.contextMenu()
    assert menu is not None
    return shell, menu


def _close_overlay_tray(shell) -> None:
    """收口：菜单（生灭后可能已重建，故从托盘重取）+ 指令 watcher + 运行标记。"""
    if getattr(shell, "tray", None) is not None:
        menu = shell.tray.contextMenu()
        if menu is not None:
            try:
                menu.close()
            except RuntimeError:
                pass  # 菜单已随生灭重建销毁：跳过
        shell.tray.hide()
    shell._teardown_settings_command_watch()
    shell._delete_runtime_marker()
    app.processEvents()


def test_overlay_tray_show_hide_waits_for_menu_close(tmp_path):
    """overlay 托盘「显示 / 隐藏」：动的是合成窗，同样菜单先关再切。"""
    shell, menu = _overlay_tray(tmp_path)
    try:
        shell.overlay.show()
        app.processEvents()
        assert shell.overlay.isVisible(), "前提：合成窗可见"
        _open_menu(menu)

        _entry(menu, "显示 / 隐藏").trigger()
        assert shell.overlay.isVisible(), "菜单还开着，显隐动作不许内联执行"
        assert not menu.isVisible(), "点击后菜单必须先关"

        assert _wait_until(lambda: not shell.overlay.isVisible()), \
            "菜单关闭后必须切换一次显隐"
    finally:
        _close_overlay_tray(shell)


def test_overlay_tray_return_to_corner_waits_for_menu_close(tmp_path):
    """overlay 托盘「回到右下角」：移动主 sprite，同样不内联执行。"""
    shell, menu = _overlay_tray(tmp_path)
    try:
        expected = shell._default_corner_pos(shell._bounds, shell.sprite.rect())
        shell.sprite.set_pos(QPointF(0, 0))
        before = QPointF(shell.sprite.pos)
        _open_menu(menu)

        _entry(menu, "回到右下角").trigger()
        assert shell.sprite.pos == before, "菜单还开着，归位不许内联执行"
        assert not menu.isVisible(), "点击后菜单必须先关"

        assert _wait_until(lambda: shell.sprite.pos == expected), \
            "菜单关闭后必须归位一次"
    finally:
        _close_overlay_tray(shell)








def test_overlay_tray_menu_open_syncs_check_marks_without_side_effects(tmp_path):
    """overlay 托盘弹出只同步勾选态看相，绝不顺手执行副作用。

    旧接线（``toggled``）在弹出前那次程序化 ``setChecked`` 也会触发副作用：开一次
    菜单就把老鼠穿透的复合重算与系统登录项重写一遍。副作用改挂 ``triggered`` 后，
    程序化同步不发这个信号——勾选态接线不变，改动只落在"不再误触发"。
    """
    shell, menu = _overlay_tray(tmp_path)
    autostart_calls: list = []
    try:
        shell._instance._set_autostart = (
            lambda enabled, target=None: (autostart_calls.append(enabled), True)[1])
        shell._autostart_enabled = lambda: True
        shell._config.set("mouse_through", True)
        shell.overlay.mouse_through = False     # 前提：窗面尚未应用该意愿
        menu.aboutToShow.emit()
        app.processEvents()

        assert _entry(menu, "鼠标穿透").isChecked() is True, "勾选态跟着配置走"
        assert _entry(menu, "开机自启").isChecked() is True, "勾选态跟着系统登录项走"
        assert shell.overlay.mouse_through is False, "弹菜单不得动穿透开关"
        assert autostart_calls == [], "弹菜单不得写系统登录项"
    finally:
        _close_overlay_tray(shell)


def test_overlay_tray_quit_entry_stays_inline(tmp_path):
    """「退出」刻意不延迟派发：它不是窗面动作，legacy 托盘同为裸 addAction。

    这条把"有意不改"钉住：将来若有人顺手把它也改成延迟派发，本用例会提醒先想清楚
    ——退出发生在原生菜单跟踪会话里不需要系统菜单会话放行（会话随进程一起结束）。
    """
    shell, menu = _overlay_tray(tmp_path)
    quit_calls: list = []
    try:
        shell.app = SimpleNamespace(quit=lambda: quit_calls.append(1))
        shell._refresh_tray_menu()
        menu = shell.tray.contextMenu()
        _entry(menu, "退出").trigger()
        assert quit_calls == [1], "「退出」触发即生效（无延迟派发）"
    finally:
        _close_overlay_tray(shell)


def test_overlay_tray_settings_entry_waits_for_menu_close(tmp_path):
    """overlay 拓扑的同一个入口（``OverlayShell._refresh_tray_menu``）同口径。"""
    from tests.helpers.overlay_shell import _make_persistent_shell

    shell, _made = _make_persistent_shell(tmp_path)
    opened: list = []
    try:
        shell._instance.shell = SimpleNamespace(
            open_settings_process=lambda inst: (opened.append(inst), True)[1])
        menu = shell.tray.contextMenu()
        assert menu is not None
        menu.show()
        app.processEvents()
        assert menu.isVisible(), "前提：菜单在显示态"

        _entry(menu, "桌宠设置").trigger()
        assert opened == [], "菜单还开着，设置入口不许内联执行"
        assert not menu.isVisible(), "点击后菜单必须先关"
        assert _wait_until(lambda: len(opened) == 1), "菜单关闭后必须打开设置"
    finally:
        menu = shell.tray.contextMenu()
        if menu is not None:
            menu.close()
        shell._teardown_settings_command_watch()
        app.processEvents()
