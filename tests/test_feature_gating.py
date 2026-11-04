# -*- coding: utf-8 -*-
"""Phase 1 开关式加载门控测试。

验证目标：可选功能关闭时不构造/启动对应服务对象；启用时才懒装配。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _disabled_config(tmp_path):
    cfg = Config(base=tmp_path)
    cfg.set("decode_broker_enabled", True)
    cfg.set("todo_reminder_enabled", False)
    cfg.set("click_sound_enabled", False)
    island = dict(cfg.get("dynamic_island", {}))
    island["enabled"] = False
    cfg.set("dynamic_island", island)
    cfg.set("auto_hide_fullscreen", False)
    return cfg


def test_petapp_disabled_optional_services_not_constructed(tmp_path):
    from pet.app import AppShell

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    # broker 已由进程内 fan-out hub 取代（批5.3）；todo 服务走 Phase 1
    # 懒门控（挂 AppShell 进程级）。
    assert shell.todo_service is None


def test_petapp_enabled_default_services_still_constructed(tmp_path):
    """默认配置（待办开）保持既有构造行为。"""
    from pet.app import AppShell

    app = _qapp()
    shell = AppShell(app, Config(tmp_path), enable_chat=False)
    assert shell.todo_service is not None
    # 共享解码 hub 仍为进程级（默认 enabled 取决于 flag/拓扑）。
    assert shell._decode_hub is not None


def test_petapp_start_disabled_services_stay_stopped(tmp_path, monkeypatch):
    import pet.app as app_mod
    from pet.app import AppShell

    app = _qapp()
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda *a, **k: None)
    cfg = _disabled_config(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    shell.instance._apply_spawn_offset = lambda: None
    shell._apply_balance_timer = lambda: None
    shell.start()
    assert shell.todo_service is None
