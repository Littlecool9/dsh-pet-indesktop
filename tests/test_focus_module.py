# -*- coding: utf-8 -*-
"""「专注模式」模块：事件负载、配置 schema、菜单接线与“模块缺失 = 专注关闭”。"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pet.config import Config
from pet.module_config import module_defaults, module_global_keys
from pet.module_host import module_service
from pet.modules.base import ModuleManifest, load_entry
from pet.modules.focus import MANIFEST
from pet.modules.focus import config as module_config
from pet.modules.focus import menu as module_menu
from pet.modules.focus import module as module_mod
from pet.modules.focus.session import FocusSession
from pet.modules.focus.state import FocusService
from pet.modules.host import ModuleHostBase


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _pump_until(qapp, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert predicate(), "focus.changed 未在预算内送达"


def _start_module(monkeypatch, session=None):
    state = session or FocusSession()
    monkeypatch.setattr(module_mod, "shared_focus_session", lambda: state)
    host = ModuleHostBase()
    module = module_mod.create(MANIFEST)
    module.start(host)
    return module, host, state


def test_manifest_declares_schema_and_menu_actions():
    manifest = load_entry("pet.modules.focus:MANIFEST")
    assert isinstance(manifest, ModuleManifest)
    assert manifest.id == "focus"
    assert manifest.config_keys == (module_config.KEY,)
    assert manifest.config_schema == "pet.modules.focus.config:SCHEMA"
    assert module_menu.actions()["focus_mode"].label == "专注模式"
    assert module_menu.actions()["focus_mode"].icon == "pause"


def test_config_defaults_are_normalized_and_global():
    default = module_defaults()[module_config.KEY]
    assert default["work_minutes"] == 25
    assert isinstance(default["screen_enabled"], bool)
    assert module_config.KEY in module_global_keys()


def test_module_provides_focus_service_and_emits_initial_state(qapp, monkeypatch):
    module, host, _state = _start_module(monkeypatch)
    events: list[dict] = []
    host.subscribe("focus.changed", events.append)
    # 订阅之前的首发事件已经排进队列；重发一次当前状态验证服务与订阅。
    module._emit_state(force=True)
    _pump_until(qapp, lambda: bool(events))
    service = host.get("focus")
    assert isinstance(service, FocusService)
    assert service.engaged is False
    assert events[-1] == {"enabled": False, "phase": None, "endsAt": None}
    module.stop()
    assert host.get("focus") is None


def test_focus_changed_payload_on_start_phase_pause_resume_and_stop(qapp, monkeypatch):
    now = [0.0]
    state = FocusSession(clock=lambda: now[0])
    module, host, _state = _start_module(monkeypatch, state)
    events: list[dict] = []
    host.subscribe("focus.changed", events.append)
    module._emit_state(force=True)
    _pump_until(qapp, lambda: bool(events))
    events.clear()

    def next_event():
        before = len(events)
        _pump_until(qapp, lambda: len(events) > before)
        payload = events[-1]
        assert set(payload) == {"enabled", "phase", "endsAt"}
        return payload

    state.start()
    started = next_event()
    assert started["enabled"] is True
    assert started["phase"] == "focus"
    assert isinstance(started["endsAt"], int) and started["endsAt"] > 0

    state.pause()
    paused = next_event()
    assert paused["enabled"] is True and paused["phase"] == "focus"
    assert paused["endsAt"] is None

    state.resume()
    resumed = next_event()
    assert resumed["enabled"] is True and isinstance(resumed["endsAt"], int)

    now[0] = state.remaining_seconds() + 1
    assert state.tick()
    break_started = next_event()
    assert break_started["enabled"] is True
    assert break_started["phase"] == "short_break"
    assert isinstance(break_started["endsAt"], int)

    state.stop()
    stopped = next_event()
    assert stopped == {"enabled": False, "phase": None, "endsAt": None}
    module.stop()


def test_missing_module_reads_as_focus_off(qapp, tmp_path):
    from types import SimpleNamespace

    from pet.dynamic_island import DynamicIsland
    from pet.module_host import module_service as lookup

    shell_without_host = SimpleNamespace()
    assert lookup(shell_without_host, "focus") is None
    shell_with_off_host = SimpleNamespace(
        _module_host=SimpleNamespace(get=lambda _name, default=None: default))
    assert lookup(shell_with_off_host, "focus") is None

    cfg = Config(base=tmp_path)
    island = DynamicIsland(cfg, focus=lookup(shell_with_off_host, "focus"))
    try:
        assert island._focus_controls is None
        assert "专注" not in island._info_text()
    finally:
        island.close()
        qapp.processEvents()

    from PySide6.QtCore import QRect

    from pet.sprite_behavior import BehaviorController

    controller = BehaviorController(QRect(0, 0, 100, 100))
    assert controller._focus_focusing() is False


def test_menu_builds_module_submenu_or_disabled_entry(qapp):
    from PySide6.QtWidgets import QMenu

    class _Pet:
        def __init__(self, module, reason=""):
            self.cfg = {}
            self.module = module
            self.reason = reason

        def running_module(self, _module_id):
            return self.module

        def module_unavailable_reason(self, _module_id):
            return self.reason

    state = FocusSession()
    service = FocusService(state)
    module = module_mod.FocusModule(MANIFEST)
    module._service = service

    menu = QMenu()
    try:
        built = module_menu._build(menu, _Pet(module))
        assert built is not None and built.title() == "专注模式"
        assert module_menu._enabled(_Pet(module)) is True
        assert module_menu._disabled_reason(_Pet(module)) == ""

        disabled = module_menu._build(menu, _Pet(None, "启动失败：RuntimeError: boom"))
        assert disabled.isEnabled() is False
        assert disabled.toolTip() == "启动失败：RuntimeError: boom"
    finally:
        menu.close()
        qapp.processEvents()

def test_app_shell_starts_focus_module_and_provides_service(qapp, tmp_path):
    from pet.app import AppShell

    shell = AppShell(qapp, Config(base=tmp_path))
    try:
        shell._start_modules()
        module = shell.running_module("focus")
        assert isinstance(module, module_mod.FocusModule)
        assert shell.module_unavailable_reason("focus") == ""
        service = shell._module_host.get("focus")
        assert isinstance(service, FocusService)
        assert service.engaged is False
    finally:
        shell._stop_modules()
        shell._module_registry = None

def test_removing_module_from_MODULES_leaves_core_focus_off(qapp, tmp_path, monkeypatch):
    import pet.modules as modules_mod
    from pet import module_config as core_module_config

    packages = tuple(p for p in modules_mod.MODULES if p != "pet.modules.focus")
    monkeypatch.setattr(modules_mod, "MODULES", packages)
    core_module_config.reset_cache()
    try:
        cfg = Config(base=tmp_path)
        assert "focus_mode" not in cfg.data
        from pet.app import AppShell

        shell = AppShell(qapp, cfg)
        try:
            shell._start_modules()
            assert shell.running_module("focus") is None
            assert module_service(shell, "focus") is None
        finally:
            shell._stop_modules()
            shell._module_registry = None
    finally:
        core_module_config.reset_cache()
