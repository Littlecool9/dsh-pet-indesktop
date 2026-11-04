# -*- coding: utf-8 -*-
"""SurfCore 模块：服务表 provide/withdraw、事件/上下线 emit、apply_config 幂等。"""
from __future__ import annotations

import threading
import time

import pytest

from pet.modules.surfcore import MANIFEST
from pet.modules.surfcore import module as surfcore_module


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        FakeClient.instances.append(self)


class FakePoller:
    instances: list["FakePoller"] = []

    def __init__(self, client, on_event, on_online_change, **kwargs) -> None:
        self.client = client
        self.on_event = on_event
        self.on_online_change = on_online_change
        self.kwargs = kwargs
        self.start_calls = 0
        self.stop_calls = 0
        self.stop_timeouts: list[float] = []
        FakePoller.instances.append(self)

    @property
    def running(self) -> bool:
        return self.start_calls > self.stop_calls

    def start(self) -> None:
        self.start_calls += 1

    def stop(self, timeout: float = 5.0) -> bool:
        self.stop_calls += 1
        self.stop_timeouts.append(timeout)
        return True

    def fire_event(self, event) -> None:
        self.on_event(event)

    def fire_online(self, online: bool) -> None:
        self.on_online_change(online)


@pytest.fixture(autouse=True)
def _reset_fakes():
    FakeClient.instances.clear()
    FakePoller.instances.clear()
    yield
    FakeClient.instances.clear()
    FakePoller.instances.clear()


def _pump_until(qapp, done: threading.Event, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not done.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        done.wait(0.01)
    return done.is_set()


def test_manifest_and_factory():
    assert MANIFEST.id == "surfcore"
    assert MANIFEST.name == "SurfCore 连接"
    assert MANIFEST.factory == "pet.modules.surfcore.module:create"
    instance = surfcore_module.create(MANIFEST)
    assert isinstance(instance, surfcore_module.SurfCoreModule)
    assert instance.manifest is MANIFEST


def test_module_provides_client_and_emits_on_host_thread(qapp, monkeypatch):
    monkeypatch.setattr(surfcore_module, "SurfCoreClient", FakeClient)
    monkeypatch.setattr(surfcore_module, "EventPoller", FakePoller)

    from pet.modules.host import ModuleHostBase

    host = ModuleHostBase()
    events: list[tuple[dict, int]] = []
    online: list[tuple[bool, int]] = []
    event_done = threading.Event()
    online_done = threading.Event()

    def on_event(payload):
        events.append((payload, threading.get_ident()))
        event_done.set()

    def on_online(payload):
        online.append((payload, threading.get_ident()))
        online_done.set()

    host.subscribe("surfcore.event", on_event)
    host.subscribe("surfcore.online", on_online)

    surface = surfcore_module.create(MANIFEST)
    surface.start(host)

    assert len(FakeClient.instances) == 1
    assert len(FakePoller.instances) == 1
    poller = FakePoller.instances[0]
    assert host.get("surfcore") is FakeClient.instances[0]
    assert poller.client is FakeClient.instances[0]
    assert poller.start_calls == 1

    worker = threading.Thread(
        target=lambda: poller.fire_event({"id": 1, "type": "reply", "text": "hi"}),
        daemon=True,
    )
    worker.start()
    worker.join(5.0)
    assert _pump_until(qapp, event_done)
    assert events == [({"id": 1, "type": "reply", "text": "hi"}, threading.get_ident())]

    online_worker = threading.Thread(target=lambda: poller.fire_online(True), daemon=True)
    online_worker.start()
    online_worker.join(5.0)
    assert _pump_until(qapp, online_done)
    assert online == [(True, threading.get_ident())]

    # 没有配置键：apply_config 只保证轮询在跑，幂等。
    surface.apply_config(None)
    surface.apply_config(None)
    assert len(FakePoller.instances) == 1
    assert poller.start_calls == 1

    surface.stop()
    assert poller.stop_calls == 1
    assert host.get("surfcore", None) is None
    surface.stop()
    assert poller.stop_calls == 1
