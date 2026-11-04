# -*- coding: utf-8 -*-
"""「Agent 联动」模块：清单 / 配置 schema / 宿主服务 / 模块缺失 = 联动关闭。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pet.config import Config
from pet.module_config import module_defaults, module_global_keys
from pet.module_host import module_service
from pet.modules.agent_link import MANIFEST
from pet.modules.agent_link import config as module_config
from pet.modules.agent_link import menu as module_menu
from pet.modules.agent_link import module as module_mod
from pet.modules.agent_link.shared import SharedAgentLinkManager
from pet.modules.base import ModuleManifest, load_entry


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_manifest_declares_schema_and_menu_actions():
    manifest = load_entry("pet.modules.agent_link:MANIFEST")
    assert isinstance(manifest, ModuleManifest)
    assert manifest.id == "agent_link"
    assert manifest.config_keys == (module_config.KEY,)
    assert manifest.config_schema == "pet.modules.agent_link.config:SCHEMA"
    assert manifest.menu_actions == "pet.modules.agent_link.menu:actions"
    assert module_menu.actions()["agent_link"].label == "Agent 联动"


def test_config_defaults_are_normalized_and_global(tmp_path):
    default = module_defaults()[module_config.KEY]
    assert default["dsh"] is False
    assert default["custom_agents"] == []
    assert module_config.KEY in module_global_keys()

    cfg = Config(base=tmp_path)
    assert cfg.get(module_config.KEY)["dsh"] is False
    cfg.set(module_config.KEY, {"dsh": False, "custom_agents": [{"key": "x", "path": "p"}]})
    value = cfg.get(module_config.KEY)
    assert value["dsh"] is False
    assert value["custom_agents"] == [{"key": "x", "name": "x", "path": "p"}]


def test_module_provides_shared_manager_service(qapp, tmp_path):
    from pet.app import AppShell

    shell = AppShell(qapp, Config(base=tmp_path))
    try:
        shell._start_modules()
        module = shell.running_module("agent_link")
        assert isinstance(module, module_mod.AgentLinkModule)
        manager = shell._module_host.get("agent_link")
        assert isinstance(manager, SharedAgentLinkManager)
        assert manager is module_service(shell, "agent_link")
        assert manager.monitors["dsh"]._running is False, "默认配置下读方不得启动"
        assert shell._overlay_shell is None  # 纯模块启动路径没有壳
    finally:
        shell._stop_modules()
        shell._shared.stop_all()


def test_removing_module_from_MODULES_leaves_core_agent_link_off(
        qapp, tmp_path, monkeypatch):
    import pet.modules as modules_mod
    from pet import module_config as core_module_config
    from pet.context_menus.registry import MENU_ACTIONS
    from pet.multi_window_shared import MultiWindowProxy

    packages = tuple(p for p in modules_mod.MODULES if p != "pet.modules.agent_link")
    monkeypatch.setattr(modules_mod, "MODULES", packages)
    core_module_config.reset_cache()
    MENU_ACTIONS.reset_module_specs()
    try:
        cfg = Config(base=tmp_path)
        assert module_config.KEY not in cfg.data
        assert cfg.get(module_config.KEY) is None

        from pet.app import AppShell

        shell = AppShell(qapp, cfg)
        try:
            shell._start_modules()
            assert shell.running_module("agent_link") is None
            assert module_service(shell, "agent_link") is None
            assert MultiWindowProxy(shell).agent_link_manager is None
            # 核心事件入口在模块缺席时静默 no-op（不会抛）。
            shell._on_agent_link_event({"kind": "dsh_state", "to": "working"})
        finally:
            shell._stop_modules()
            shell._shared.stop_all()
        assert "agent_link" not in MENU_ACTIONS.ids, "模块缺失 = 联动菜单入口一起消失"
    finally:
        core_module_config.reset_cache()
        MENU_ACTIONS.reset_module_specs()

def test_app_start_without_agent_link_module(qapp, tmp_path, monkeypatch):
    """模块被移除后，完整 AppShell.start() 仍能起来，联动读方/服务全为关闭。"""
    import pet.overlay_shell as overlay_shell_mod
    import pet.modules as modules_mod
    from pet import module_config as core_module_config
    from pet.app import AppShell

    packages = tuple(p for p in modules_mod.MODULES if p != "pet.modules.agent_link")
    monkeypatch.setattr(modules_mod, "MODULES", packages)
    core_module_config.reset_cache()

    class _FakeOverlayShell:
        def __init__(self, qapp_, instance, **kwargs):
            self.instance = instance
            self.kwargs = kwargs

        def start(self):
            pass

    monkeypatch.setattr(overlay_shell_mod, "OverlayShell", _FakeOverlayShell)
    monkeypatch.setattr("pet.app.QTimer.singleShot", lambda *a, **k: None)

    shell = AppShell(qapp, Config(base=tmp_path))
    shell.instance._apply_spawn_offset = lambda: None
    shell.instance._refresh_chat_windows = lambda: None
    shell._sync_dynamic_island = lambda: None
    shell._install_session_watcher = lambda: None
    try:
        shell.start()
        assert shell._overlay_shell is not None
        assert module_service(shell, "agent_link") is None
        assert shell._shared.agent_link is None
        assert shell._dsh_tracker_wanted() is False
    finally:
        shell._stop_modules()
        shell._shared.stop_all()
        shell._teardown_config_watcher()
        core_module_config.reset_cache()
