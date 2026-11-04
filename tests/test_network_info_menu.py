# -*- coding: utf-8 -*-
"""右键菜单「网络信息」入口与模块接线契约（issue #172 / 阶段 2）。

覆盖：模块清单的菜单入口、``MenuActionRegistry`` 惰性合并（label/icon/可调用
置灰原因）、开关关掉与模块不可用两种置灰、模块内单例弹窗（含父窗带走/静默销毁
后的自愈）、以及 AppShell 按 ``MODULES`` 启动后菜单拿得到运行中的模块。

真实菜单树端的覆盖在既有套件里：``tests/test_menu_layout.py`` 断言现代菜单
「工具与帮助」里有这一项；``tests/test_sprite_menu_parity.py`` 的树比对与
REQUIRED_LABELS 逐项包含它，并覆盖点击路由。

弹窗在本文件里一律替换成不发真实请求的替身（真探针的真实取数由实机验证覆盖）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
from PySide6.QtWidgets import QApplication, QMenu

from pet.config import Config
from pet.context_menus import registry as registry_mod
from pet.menu_layout import load_default_menu_layout
from pet.module_config import module_defaults, module_global_keys
from pet.modules.base import ModuleManifest, load_entry
from pet.modules.network_info import config as module_config
from pet.modules.network_info import dialog as dialog_mod
from pet.modules.network_info import menu as module_menu
from pet.modules.network_info.module import NetworkInfoModule

app = QApplication.instance() or QApplication([])


class _Cfg:
    def __init__(self, values: dict):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Pet:
    """菜单宿主替身：运行中模块 + 可选不可用原因。"""

    def __init__(self, values: dict | None = None, *, module=..., reason: str = ""):
        self.cfg = _Cfg(values or {})
        self.module = module
        self.reason = reason

    def running_module(self, _module_id):
        return self.module

    def module_unavailable_reason(self, _module_id):
        return self.reason


def _labels(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _find(menu, label: str):
    for action in menu.actions():
        if action.text() == label:
            return action
    raise AssertionError(f"菜单缺项 {label}；实际 = {_labels(menu)}")


# ---------------------------------------------------------------- 清单 / 注册表
def test_manifest_declares_menu_actions_config_schema_and_layout_node():
    manifest = load_entry("pet.modules.network_info:MANIFEST")
    assert isinstance(manifest, ModuleManifest)
    assert manifest.id == "network_info"
    assert manifest.menu_actions == "pet.modules.network_info.menu:actions"
    assert manifest.config_schema == "pet.modules.network_info.config:SCHEMA"
    assert manifest.config_keys == (module_config.SWITCH_KEY,)

    actions = module_menu.actions()
    spec = actions["network_info"]
    assert spec.label == "网络信息"
    assert spec.icon == "web"

    def ids(nodes) -> list[str]:
        found = []
        for node in nodes:
            if node.get("type") == "action":
                found.append(str(node.get("id")))
            found.extend(ids(node.get("children", [])))
        return found

    assert "network_info" in ids(load_default_menu_layout().get("nodes", []))


def test_registry_merges_module_label_icon_and_layout_node():
    registry = registry_mod.MENU_ACTIONS
    assert "network_info" in registry.ids
    assert registry.label("network_info") == "网络信息"
    assert registry.default_icon("network_info") == "web"
    # 旧核心的标签/图标表不再维护这一项（单一来源在模块）。
    assert "network_info" not in registry_mod.ACTION_LABELS
    assert "network_info" not in registry_mod.ACTION_ICONS


def test_gate_default_on_and_module_config_is_global():
    assert module_defaults()[module_config.SWITCH_KEY] is True
    assert module_config.SWITCH_KEY in module_global_keys()


def test_callback_gates_availability_and_switch_gates_enablement():
    """两条门各管一件事（CONTEXT.md 的 Runtime Disabled）：

    - 宿主没接上模块生命周期＝**能力不可用** → 从 available 里消失；
    - 模块在跑但开关关掉＝**运行时停用** → 仍在 available 里（保留布局位置），
      只是不在 enabled 里，渲染成"灰掉 + 说明"。
    """
    actions = registry_mod.MENU_ACTIONS
    module = object()
    assert "network_info" in actions.available_ids(_Pet(module=module))
    assert "network_info" in actions.available_ids(
        _Pet({"network_info_menu_enabled": False}, module=module)), "开关不该影响可用性"
    assert "network_info" not in actions.available_ids(object())

    assert "network_info" in actions.enabled_ids(_Pet(module=module))
    assert "network_info" not in actions.enabled_ids(
        _Pet({"network_info_menu_enabled": False}, module=module))


def test_unavailable_module_is_available_but_greyed_with_its_reason():
    pet = _Pet(module=None, reason="启动失败：RuntimeError: boom")
    actions = registry_mod.MENU_ACTIONS
    assert "network_info" in actions.available_ids(pet)
    assert "network_info" not in actions.enabled_ids(pet)
    assert actions.disabled_reason("network_info", pet) == "启动失败：RuntimeError: boom"
    # 没有 pet 的只读查询回落开关说明（不抛）。
    assert actions.disabled_reason("network_info") == module_config.SWITCH_OFF_REASON


def test_disable_reason_is_shared_by_registry_and_builder():
    class _Module:
        def open_dialog(self):
            raise AssertionError("置灰项不得触发回调")

    pet = _Pet({"network_info_menu_enabled": False}, module=_Module())
    actions = registry_mod.MENU_ACTIONS
    assert module_config.SWITCH_OFF_REASON
    assert actions.disabled_reason("network_info", pet) == module_config.SWITCH_OFF_REASON

    menu = QMenu()
    try:
        action = module_menu._build(menu, pet)
        assert action.isEnabled() is False
        assert action.toolTip() == module_config.SWITCH_OFF_REASON
    finally:
        menu.close()
        app.processEvents()


# ---------------------------------------------------------------- 建造函数
def test_build_action_opens_the_running_module():
    opened: list = []

    class _Module:
        def open_dialog(self):
            opened.append(True)

    menu = QMenu()
    try:
        action = module_menu._build(menu, _Pet(module=_Module()))
        assert action.text() == "网络信息"
        assert action.isEnabled() is True
        assert action.property("closeOnTrigger") is True
        action.trigger()
        assert opened == [True]
    finally:
        menu.close()
        app.processEvents()


def test_modern_registry_renders_entry_disabled_with_module_reason():
    nodes = ({"type": "action", "id": "network_info", "visible": True},)
    pet = _Pet(module=None, reason="缺少依赖模块：SurfCore 连接")
    menu = QMenu()
    try:
        registry_mod.MENU_ACTIONS.populate(
            menu, pet, nodes,
            enabled_actions=registry_mod.MENU_ACTIONS.enabled_ids(pet))
        action = _find(menu, "网络信息")
        assert action.isEnabled() is False
        assert action.toolTip() == "缺少依赖模块：SurfCore 连接"
    finally:
        menu.close()
        app.processEvents()


# ---------------------------------------------------------------- 模块内弹窗
class _QuietDialog(dialog_mod.NetworkInfoDialog):
    """不发真实请求的弹窗替身（只验证接线与单例语义）。"""

    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)
        self.refreshed = 0

    def refresh(self) -> None:  # 真探针要发外网请求，测试里一律跳过
        self.refreshed += 1


class _Host:
    def __init__(self):
        self.parent = None

    def dialog_parent(self):
        return self.parent

    def present_dialog(self, dialog):
        dialog.show()


def _quiet(monkeypatch):
    monkeypatch.setattr(dialog_mod, "NetworkInfoDialog", _QuietDialog)


def _open_quietly(monkeypatch) -> tuple[NetworkInfoModule, _Host]:
    _quiet(monkeypatch)
    module = NetworkInfoModule()
    module.start(_Host())
    return module, module._host


def test_open_dialog_is_single_instance(monkeypatch):
    module, _host = _open_quietly(monkeypatch)
    module.open_dialog()
    dialog = module._dialog
    assert isinstance(dialog, _QuietDialog)
    assert dialog.refreshed == 1, "弹窗显示时应当取一次数据"
    module.open_dialog()
    assert module._dialog is dialog, "非模态单例：再次点击复用同一窗"
    module.stop()
    assert module._dialog is None


def test_open_dialog_recovers_after_destroyed_with_parent(monkeypatch):
    """随父宠物销毁（不发 finished）后，单例不得仍指向失效对象。"""
    module, _host = _open_quietly(monkeypatch)
    module.open_dialog()
    first = module._dialog
    shiboken6.delete(first)  # 销毁不发 finished（destroyed 才发）
    app.processEvents()
    assert module._dialog is None, "销毁信号必须收口单例"

    module.open_dialog()
    second = module._dialog
    assert isinstance(second, _QuietDialog) and second is not first
    assert second.refreshed == 1, "重开的弹窗照常取数"
    module.stop()


def test_open_dialog_replaces_singleton_that_was_destroyed_silently(monkeypatch):
    """收口信号没到（时序缝隙）时，复用前自查失效对象，不得抛。"""
    module, _host = _open_quietly(monkeypatch)
    module.open_dialog()
    first = module._dialog
    shiboken6.delete(first)
    app.processEvents()
    module._dialog = first  # 人为塞回：模拟 destroyed 未送达
    module.open_dialog()
    second = module._dialog
    assert isinstance(second, _QuietDialog) and second is not first
    module.stop()


def test_stale_destroyed_signal_does_not_clear_new_dialog(monkeypatch):
    """旧窗晚到的 destroyed 不得清掉新实例（对象身份核对）。"""
    module, _host = _open_quietly(monkeypatch)
    module.open_dialog()
    first = module._dialog
    shiboken6.delete(first)
    app.processEvents()
    module.open_dialog()
    second = module._dialog
    assert second is not None and second is not first

    module._dialog_destroyed(first)  # 旧窗的收口信号晚到
    assert module._dialog is second
    module.stop()


# ---------------------------------------------------------------- AppShell 接线
def test_app_shell_starts_network_info_module(tmp_path, monkeypatch):
    from pet.app import AppShell

    _quiet(monkeypatch)
    shell = AppShell(app, Config(tmp_path))
    try:
        shell._start_modules()
        module = shell.running_module("network_info")
        assert isinstance(module, NetworkInfoModule)
        assert shell.module_unavailable_reason("network_info") == ""
        module.open_dialog()
        assert isinstance(module._dialog, _QuietDialog)
    finally:
        shell._stop_modules()
        shell._module_registry = None
