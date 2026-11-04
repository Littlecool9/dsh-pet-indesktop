# -*- coding: utf-8 -*-
"""模块宿主接线：AppShell 生命周期、菜单惰性合并、模块配置 schema、删模块的收口。

用 sys.modules 里的临时模块包（不是磁盘目录）驱动真实 ``ModuleRegistry`` /
``Config`` / ``MenuActionRegistry``，避免为测试往 ``pet/modules/`` 里加假模块
（架构测试要求目录与 ``MODULES`` 一一对应）。
"""
from __future__ import annotations

import json
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet import module_config
from pet.config import APP_DIR_NAME, Config
from pet.context_menus.registry import MENU_ACTIONS, MenuActionSpec
from pet.context_menus.shared import add_action
from pet.module_host import AppModuleHost
from pet.modules.base import ModuleConfigSchema, ModuleManifest
from pet.modules.registry import ModuleRegistry
from pet.settings_slot_config import SLOT_ROUTED_KEYS, route_settings_config

app = QApplication.instance() or QApplication([])

FAKE_ID = "p2_fake_mod"
FAKE_KEY = "p2_fake_enabled"
RUNTIME: "_FakeRuntime | None" = None


class _FakeRuntime:
    def __init__(self, manifest):
        self.manifest = manifest
        self.host = None
        self.started = 0
        self.stopped = 0
        self.configs: list = []

    def start(self, host):
        self.host = host
        self.started += 1

    def apply_config(self, config):
        self.configs.append(config)

    def stop(self):
        self.stopped += 1


def make_runtime(manifest):
    global RUNTIME
    RUNTIME = _FakeRuntime(manifest)
    return RUNTIME


def _normalize(data: dict) -> None:
    value = data.get(FAKE_KEY, True)
    if isinstance(value, str):
        value = value.strip().lower() not in {"false", "0", "off", "no"}
    data[FAKE_KEY] = bool(value)


FAKE_SCHEMA = ModuleConfigSchema(
    defaults={FAKE_KEY: True}, normalize=_normalize, global_keys=(FAKE_KEY,),
)


def menu_actions():
    return {
        "p2_fake_action": MenuActionSpec(
            lambda menu, pet: add_action(menu, "假动作", "web", lambda: None),
            label="假动作",
            icon="web",
            disabled_reason=lambda _pet: "假动作已关闭",
        ),
    }


def clashing_menu_actions():
    return {
        "chat": MenuActionSpec(
            lambda menu, pet: add_action(menu, "冲突", "web", lambda: None),
            label="冲突",
        ),
    }


def _fake_package(*, menu_entry=f"{__name__}:menu_actions"):
    pkg = types.ModuleType(FAKE_ID)
    pkg.MANIFEST = ModuleManifest(
        id=FAKE_ID,
        name="假模块",
        factory=f"{__name__}:make_runtime",
        menu_actions=menu_entry,
        config_schema=f"{__name__}:FAKE_SCHEMA",
    )
    return pkg


@pytest.fixture
def fake_modules(monkeypatch):
    import pet.modules as modules_mod

    monkeypatch.setitem(sys.modules, FAKE_ID, _fake_package())
    monkeypatch.setattr(modules_mod, "MODULES", (FAKE_ID,))
    _reset_caches()
    yield
    _reset_caches()


def _reset_caches():
    module_config.reset_cache()
    MENU_ACTIONS.reset_module_specs()


@pytest.fixture(autouse=True)
def _clean_caches_after():
    yield
    _reset_caches()


# ---------------------------------------------------------------- H1 宿主
def test_app_module_host_exposes_app_capabilities():
    class _Overlay:
        def __init__(self):
            self.bubbles: list = []
            self.widget = QWidget()

        def show_bubble(self, text, ms):
            self.bubbles.append((text, ms))
            return True

        @property
        def overlay(self):
            return self.widget

    class _Shell:
        config = object()
        app = object()
        instance = None
        _overlay_shell = _Overlay()

    shell = _Shell()
    host = AppModuleHost(shell)
    assert host.config is shell.config and host.app is shell.app
    assert host.dialog_parent() is shell._overlay_shell.widget
    assert host.show_bubble(" hello ", 1200) is True
    assert shell._overlay_shell.bubbles == [(" hello ", 1200)]
    shell._overlay_shell = None
    assert host.dialog_parent() is None
    assert host.show_bubble("gone") is False  # 没有壳 = 静默 no-op


# ---------------------------------------------------------------- H2 AppShell
def test_app_shell_starts_applies_and_stops_modules(fake_modules, tmp_path):
    from pet.app import AppShell

    shell = AppShell(app, Config(tmp_path))
    try:
        shell._start_modules()
        runtime = shell.running_module(FAKE_ID)
        assert runtime is RUNTIME and runtime.started == 1
        assert isinstance(runtime.host, AppModuleHost)
        assert shell.module_unavailable_reason(FAKE_ID) == ""

        shell.config.set(FAKE_KEY, False)
        shell._apply_module_config()
        assert runtime.configs[-1] is shell.config

        shell._stop_modules()
        assert runtime.stopped == 1
        assert shell.running_module(FAKE_ID) is None
        assert shell.module_unavailable_reason(FAKE_ID) == "模块未启动"
    finally:
        shell._stop_modules()
        shell._module_registry = None


def test_app_shell_tolerates_a_broken_module_package(tmp_path, monkeypatch):
    import pet.app as app_mod
    import pet.modules as modules_mod

    monkeypatch.setattr(modules_mod, "MODULES", ("p2_missing_package",))
    _reset_caches()
    shell = app_mod.AppShell(app, Config(tmp_path))
    try:
        shell._start_modules()  # 不抛
        assert shell.running_module("p2_missing_package") is None
        reason = shell.module_unavailable_reason("p2_missing_package")
        assert "模块清单读取失败" in reason
    finally:
        shell._stop_modules()
        shell._module_registry = None


# ---------------------------------------------------------------- H3 菜单
def test_menu_registry_merges_module_specs_lazily(fake_modules):
    assert "p2_fake_action" in MENU_ACTIONS.ids
    assert MENU_ACTIONS.label("p2_fake_action") == "假动作"
    assert MENU_ACTIONS.default_icon("p2_fake_action") == "web"
    assert MENU_ACTIONS.disabled_reason("p2_fake_action", app) == "假动作已关闭"


def test_menu_registry_rejects_clash_with_builtin(monkeypatch):
    import pet.modules as modules_mod

    monkeypatch.setitem(
        sys.modules, FAKE_ID, _fake_package(menu_entry=f"{__name__}:clashing_menu_actions"))
    monkeypatch.setattr(modules_mod, "MODULES", (FAKE_ID,))
    _reset_caches()
    with pytest.raises(ValueError, match="冲突"):
        _ = MENU_ACTIONS.ids
    _reset_caches()


def test_removing_a_module_removes_menu_action_and_defaults(fake_modules, monkeypatch, tmp_path):
    import pet.modules as modules_mod

    assert FAKE_KEY in module_config.module_defaults()
    assert Config(tmp_path / "before").get(FAKE_KEY) is True
    assert "p2_fake_action" in MENU_ACTIONS.ids

    monkeypatch.setattr(modules_mod, "MODULES", ())
    _reset_caches()

    assert FAKE_KEY not in module_config.module_defaults()
    assert FAKE_KEY not in Config(tmp_path / "after").data
    assert "p2_fake_action" not in MENU_ACTIONS.ids
    assert MENU_ACTIONS.label("p2_fake_action") == "p2_fake_action"  # 回退 id，不抛


# ---------------------------------------------------------------- H4 配置
def test_module_schema_defaults_normalize_and_global_routing(fake_modules, tmp_path):
    cfg = Config(base=tmp_path)
    assert cfg.get(FAKE_KEY) is True

    cfg_dir = tmp_path / APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, FAKE_KEY: "off"}, ensure_ascii=False), encoding="utf-8")
    assert Config(base=tmp_path).get(FAKE_KEY) is False

    cfg.set(FAKE_KEY, "off")
    assert cfg.get(FAKE_KEY) is False

    assert FAKE_KEY in module_config.module_global_keys()
    assert FAKE_KEY not in SLOT_ROUTED_KEYS
    routed = route_settings_config(Config(base=tmp_path, instance_id="slot-1"))
    routed.set(FAKE_KEY, False)
    assert routed.save() is True
    on_disk = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    assert on_disk[FAKE_KEY] is False, "模块 global 键必须落主 config.json"
    slot_path = cfg_dir / "config-slot-1.json"
    if slot_path.exists():
        assert FAKE_KEY not in json.loads(slot_path.read_text(encoding="utf-8"))
