# -*- coding: utf-8 -*-
"""模块注册表：依赖排序、失败隔离、阻塞原因、配置下发、停止顺序、菜单 / 设置入口、事件总线。"""
from __future__ import annotations

import sys
import threading
import types

import pytest

from pet.modules.base import ModuleManifest, load_entry
from pet.modules.registry import (
    BLOCKED, FAILED, RUNNING, STOPPED, ModuleRegistry, dependency_order, read_manifest,
)

EVENTS: list[tuple[str, str]] = []


class _Recorder:
    def __init__(self, manifest, *, fail_start=False, fail_config=False, fail_stop=False):
        self.id = manifest.id
        self.fail_start = fail_start
        self.fail_config = fail_config
        self.fail_stop = fail_stop
        self.configs: list = []
        self.host = None

    def start(self, host):
        self.host = host
        EVENTS.append(("start", self.id))
        if self.fail_start:
            raise RuntimeError("boom")

    def apply_config(self, config):
        if self.fail_config:
            raise RuntimeError("bad config")
        self.configs.append(config)

    def stop(self):
        EVENTS.append(("stop", self.id))
        if self.fail_stop:
            raise RuntimeError("stop boom")


_FACTORY_FLAGS: dict[str, dict] = {}


def make(manifest):
    return _Recorder(manifest, **_FACTORY_FLAGS.get(manifest.id, {}))


def _m(mid, *, requires=(), optional=(), menu=None, page=None):
    return ModuleManifest(
        id=mid, name=mid.upper(), factory=f"{__name__}:make",
        requires=requires, optional=optional, menu_actions=menu, settings_page=page,
    )


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset():
    EVENTS.clear()
    _FACTORY_FLAGS.clear()
    yield
    EVENTS.clear()
    _FACTORY_FLAGS.clear()


class _Host:
    def provide(self, name, service): ...
    def get(self, name, default=None): return default
    def emit(self, topic, payload=None): ...
    def subscribe(self, topic, callback): return lambda: None


def test_manifest_validation():
    with pytest.raises(ValueError):
        ModuleManifest(id="Bad-Id", name="x", factory="a:b")
    with pytest.raises(ValueError):
        ModuleManifest(id="ok", name="", factory="a:b")
    with pytest.raises(ValueError):
        ModuleManifest(id="ok", name="x", factory="no_colon")
    with pytest.raises(ValueError):
        ModuleManifest(id="ok", name="x", factory="a:b", requires=("ok",))


def test_dependency_order_is_stable_and_respects_requires_and_optional():
    a, b, c, d = _m("a", requires=("c",)), _m("b"), _m("c", optional=("b",)), _m("d")
    assert [m.id for m in dependency_order([a, b, c, d])] == ["b", "c", "a", "d"]


def test_dependency_cycle_and_duplicate_are_rejected():
    with pytest.raises(ValueError, match="成环"):
        dependency_order([_m("a", requires=("b",)), _m("b", requires=("a",))])
    with pytest.raises(ValueError, match="重复"):
        dependency_order([_m("a"), _m("a")])


def test_start_failure_is_isolated_and_blocks_only_hard_dependents():
    _FACTORY_FLAGS["base"] = {"fail_start": True}
    reg = ModuleRegistry([_m("base"), _m("hard", requires=("base",)), _m("soft", optional=("base",)), _m("other")])
    reg.start_all(_Host(), config={"k": 1})
    assert reg.status("base").state == FAILED and "boom" in reg.status("base").reason
    assert reg.status("hard").state == BLOCKED and "BASE" in reg.status("hard").reason
    assert reg.running("soft") and reg.running("other")
    assert reg.get("base") is None and reg.get("hard") is None
    assert reg.unavailable_reason("hard").startswith("缺少依赖模块")
    assert reg.unavailable_reason("soft") == ""
    assert ("start", "hard") not in EVENTS


def test_unregistered_dependency_blocks_with_reason():
    reg = ModuleRegistry([_m("x", requires=("ghost",))])
    reg.start_all(_Host())
    assert reg.status("x").state == BLOCKED
    assert "ghost" in reg.status("x").reason
    assert reg.status("nope").state == BLOCKED


def test_config_is_applied_on_start_and_on_change_and_errors_are_contained():
    _FACTORY_FLAGS["bad"] = {"fail_config": True}
    reg = ModuleRegistry([_m("good"), _m("bad")])
    reg.start_all(_Host(), config="c1")
    reg.apply_config("c2")
    assert reg.get("good").configs == ["c1", "c2"]
    assert reg.running("bad")  # apply_config 出错不算启动失败


def test_stop_runs_in_reverse_dependency_order_and_survives_errors():
    _FACTORY_FLAGS["mid"] = {"fail_stop": True}
    reg = ModuleRegistry([_m("top", requires=("mid",)), _m("mid", requires=("low",)), _m("low")])
    reg.start_all(_Host())
    assert [e for e in EVENTS if e[0] == "start"] == [("start", "low"), ("start", "mid"), ("start", "top")]
    EVENTS.clear()
    reg.stop_all()
    assert EVENTS == [("stop", "top"), ("stop", "mid"), ("stop", "low")]
    assert all(reg.status(i).state == STOPPED for i in ("top", "mid", "low"))


def test_start_all_is_idempotent():
    reg = ModuleRegistry([_m("a")])
    reg.start_all(_Host())
    reg.start_all(_Host())
    assert EVENTS.count(("start", "a")) == 1


MENU_A = {"act_a": "spec-a"}


def menu_b():
    return {"act_b": "spec-b"}


def test_menu_specs_and_settings_pages_are_collected_from_string_entries():
    reg = ModuleRegistry([
        _m("a", menu=f"{__name__}:MENU_A", page="pet.fake.page:build"),
        _m("b", menu=f"{__name__}:menu_b"),
        _m("c"),
    ])
    assert reg.menu_action_specs() == {"act_a": "spec-a", "act_b": "spec-b"}
    assert reg.settings_pages() == [("a", "pet.fake.page:build")]


def test_menu_action_id_conflict_is_an_error():
    reg = ModuleRegistry([_m("a", menu=f"{__name__}:MENU_A"), _m("b", menu=f"{__name__}:MENU_A")])
    with pytest.raises(ValueError, match="冲突"):
        reg.menu_action_specs()


def test_from_packages_can_tolerate_broken_packages(monkeypatch):
    good = types.ModuleType("pet_fake_mods.good")
    good.MANIFEST = _m("good")
    monkeypatch.setitem(sys.modules, "pet_fake_mods.good", good)
    missing = "pet_fake_mods.missing"

    tolerant = ModuleRegistry.from_packages(
        ("pet_fake_mods.good", missing), tolerant=True)
    assert tolerant.manifest("good") is not None
    assert tolerant.status("missing").state == FAILED
    assert "模块清单读取失败" in tolerant.status("missing").reason
    tolerant.start_all(_Host())
    assert tolerant.running("good")

    with pytest.raises(ImportError):
        ModuleRegistry.from_packages(("pet_fake_mods.good", missing))


def test_read_manifest_requires_matching_package_name(monkeypatch):
    pkg = types.ModuleType("pet_fake_mods.alpha")
    pkg.MANIFEST = _m("alpha")
    monkeypatch.setitem(sys.modules, "pet_fake_mods.alpha", pkg)
    assert read_manifest("pet_fake_mods.alpha").id == "alpha"
    wrong = types.ModuleType("pet_fake_mods.beta")
    wrong.MANIFEST = _m("alpha")
    monkeypatch.setitem(sys.modules, "pet_fake_mods.beta", wrong)
    with pytest.raises(ValueError, match="包名"):
        read_manifest("pet_fake_mods.beta")
    empty = types.ModuleType("pet_fake_mods.gamma")
    monkeypatch.setitem(sys.modules, "pet_fake_mods.gamma", empty)
    with pytest.raises(TypeError):
        read_manifest("pet_fake_mods.gamma")


def test_load_entry_resolves_dotted_attributes():
    assert load_entry("os.path:join") is __import__("os").path.join
    with pytest.raises(ValueError):
        load_entry("no-colon")


def test_registered_module_list_manifests_are_valid():
    """``pet.modules.MODULES`` 里登记的每个包都能读出清单，且依赖可排序。"""
    from pet.modules import MODULES

    ModuleRegistry.from_packages(MODULES)


def test_host_event_bus_delivers_on_host_thread_and_isolates_subscribers(qapp):
    from PySide6.QtCore import QCoreApplication

    from pet.modules.host import ModuleHostBase

    host = ModuleHostBase()
    seen: list = []
    done = threading.Event()
    host.subscribe("t", lambda payload: (_ for _ in ()).throw(RuntimeError("bad subscriber")))
    unsub = host.subscribe("t", lambda payload: (seen.append((payload, threading.get_ident())), done.set()))
    worker = threading.Thread(target=lambda: host.emit("t", 42))
    worker.start()
    worker.join()
    deadline = 200
    while not done.is_set() and deadline:
        QCoreApplication.processEvents()
        done.wait(0.01)
        deadline -= 1
    assert seen == [(42, threading.get_ident())], "回调必须在宿主（GUI）线程执行"
    unsub()
    host.emit("t", 43)
    QCoreApplication.processEvents()
    assert len(seen) == 1


def test_host_services_provide_get_withdraw(qapp):
    from pet.modules.host import ModuleHostBase

    host = ModuleHostBase()
    svc = object()
    host.provide("surfcore", svc)
    host.provide("surfcore", svc)  # 同一对象重复提供是幂等的
    assert host.get("surfcore") is svc
    with pytest.raises(ValueError):
        host.provide("surfcore", object())
    host.withdraw("surfcore", object())  # 不是同一个对象：不撤
    assert host.get("surfcore") is svc
    host.withdraw("surfcore", svc)
    assert host.get("surfcore", "none") == "none"
