# -*- coding: utf-8 -*-
"""Phase 1 开关式加载门控测试（模块化后）。

验证目标：可选功能关闭时不构造/启动对应服务对象；启用时才懒装配。
Phase 2 起待办服务归 ``pet.modules.todo``：AppShell 不再持有它，模块的
``apply_config`` 负责启停。
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.modules.todo.module import TodoModule


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


def _module_for(cfg):
    module = TodoModule()
    module.start(SimpleNamespace(config=cfg, shell=SimpleNamespace(win=None)))
    module.apply_config(cfg)
    return module


def test_app_shell_has_no_todo_service_wiring_until_modules_start(tmp_path):
    from pet.app import AppShell

    app = _qapp()
    cfg = _disabled_config(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    # 待办服务归模块：AppShell 构造期不持有该服务，也不再有旧门控方法。
    assert not hasattr(shell, "todo_service")
    assert not hasattr(shell, "_sync_todo_service")
    assert shell.running_module("todo") is None


def test_todo_module_disabled_does_not_construct_service(tmp_path):
    module = _module_for(_disabled_config(tmp_path))
    try:
        assert module.todo_service is None
    finally:
        module.stop()


def test_todo_module_enabled_default_services_still_constructed(tmp_path):
    """默认配置（待办开）保持既有构造行为。"""
    module = _module_for(Config(base=tmp_path))
    try:
        assert module.todo_service is not None
    finally:
        module.stop()


def test_todo_module_stops_and_releases_service_when_disabled(tmp_path):
    cfg = Config(base=tmp_path)
    module = _module_for(cfg)
    try:
        module.apply_config(cfg)
        assert module.todo_service is not None
        cfg.set("todo_reminder_enabled", False)
        module.apply_config(cfg)
        assert module.todo_service is None
    finally:
        module.stop()
