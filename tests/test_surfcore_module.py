# -*- coding: utf-8 -*-
"""SurfCore 模块：服务表 provide/withdraw、事件/上下线 emit、apply_config 幂等，
以及 ``surfcore`` 服务的后台调用与专注状态同步。"""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from pet.modules.host import ModuleHostBase
from pet.modules.surfcore import MANIFEST
from pet.modules.surfcore import module as surfcore_module
from pet.modules.surfcore.client import API_PREFIX, SurfCoreClient, SurfCoreError
from pet.modules.surfcore.service import RESULT_TOPIC, SurfCoreResult, SurfCoreService
from tests.test_surfcore_client import FakePetApi


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.focus_calls: list[dict] = []
        self.focus_event = threading.Event()
        FakeClient.instances.append(self)

    def set_focus(self, enabled, *, phase=None, ends_at=None, source="desktop-pet"):
        self.focus_calls.append(
            {
                "enabled": enabled,
                "phase": phase,
                "ends_at": ends_at,
                "source": source,
            }
        )
        self.focus_event.set()
        return {"ok": True, "focus": {"enabled": enabled}}


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


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    """轮询一个线程安全的状态；宽预算，不做固定 sleep 猜时序。"""
    deadline = time.monotonic() + timeout
    idle = threading.Event()
    while not predicate() and time.monotonic() < deadline:
        idle.wait(0.01)
    return predicate()


def _write_host(path, base_url: str, token: str = "token-a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "baseUrl": base_url,
                "token": token,
                "api": API_PREFIX,
                "pluginVersion": "test",
                "updatedAt": "2026-11-04T00:00:00.000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


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
    service = host.get("surfcore")
    assert isinstance(service, SurfCoreService)
    assert service.client is FakeClient.instances[0]
    assert service.online is False
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
    assert service.online is True

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


def test_module_syncs_focus_and_resends_after_reconnect(qapp, monkeypatch):
    monkeypatch.setattr(surfcore_module, "SurfCoreClient", FakeClient)
    monkeypatch.setattr(surfcore_module, "EventPoller", FakePoller)

    host = ModuleHostBase()
    surface = surfcore_module.create(MANIFEST)
    surface.start(host)
    client = FakeClient.instances[0]
    poller = FakePoller.instances[0]
    try:
        host.emit("focus.changed", {"enabled": True, "phase": "work", "endsAt": 123})
        assert _pump_until(qapp, client.focus_event)
        assert client.focus_calls == [
            {"enabled": True, "phase": "work", "ends_at": 123, "source": "desktop-pet"}
        ]

        # 离线 -> 在线：把已知的最新专注状态重发一次。
        client.focus_event.clear()
        poller.fire_online(False)
        poller.fire_online(True)
        assert _pump_until(qapp, client.focus_event)
        assert client.focus_calls[-1] == client.focus_calls[0]
        assert len(client.focus_calls) == 2
    finally:
        surface.stop()


# ---- surfcore 服务：后台调用与专注同步 --------------------------------------


def _pump_until_wait(qapp, wait, timeout: float = 5.0) -> bool:
    """在 GUI 线程泵事件，同时让另一个线程等真实条件（Event/Condition）。"""
    done = threading.Event()

    def waiter() -> None:
        if wait(timeout):
            done.set()

    threading.Thread(target=waiter, name="test-surfcore-wait", daemon=True).start()
    return _pump_until(qapp, done, timeout)


def _pump_until_server(qapp, api, predicate, timeout: float = 5.0) -> bool:
    return _pump_until_wait(qapp, lambda budget: api.wait_for(predicate, budget), timeout)


def _pump_until_calls(qapp, client, count: int, timeout: float = 5.0) -> bool:
    return _pump_until_wait(
        qapp, lambda budget: client.wait_for_calls(count, budget), timeout
    )


def _focus_bodies(requests: list[dict]) -> list[dict]:
    return [row["body"] for row in requests if row["route"] == "/focus"]


class RecordingFocusClient:
    """记录 ``set_focus`` 关键字参数；可切换成失败，方便测失败隔离。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self._cond = threading.Condition()
        self.calls: list[dict] = []

    def set_focus(self, enabled, *, phase=None, ends_at=None, source="desktop-pet"):
        call = {
            "enabled": enabled,
            "phase": phase,
            "ends_at": ends_at,
            "source": source,
        }
        with self._cond:
            self.calls.append(call)
            self._cond.notify_all()
            should_fail = self.fail
        if should_fail:
            raise SurfCoreError("network")
        return {"ok": True, "focus": {"enabled": enabled}}

    def snapshot(self) -> list[dict]:
        with self._cond:
            return list(self.calls)

    def wait_for_calls(self, count: int, timeout: float = 5.0) -> bool:
        with self._cond:
            deadline = time.monotonic() + timeout
            while len(self.calls) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True


def test_submit_runs_off_gui_thread_and_completion_arrives_on_gui_thread(qapp):
    gui_thread = threading.get_ident()
    started = threading.Event()
    release = threading.Event()
    calls: list[tuple[int, int]] = []

    class SlowClient:
        def slow(self, value):
            calls.append((value, threading.get_ident()))
            started.set()
            release.wait(5.0)
            return {"ok": True, "value": value}

    host = ModuleHostBase()
    service = SurfCoreService(SlowClient(), host)
    completed = threading.Event()
    completions: list[tuple[object, object, int]] = []
    events: list[SurfCoreResult] = []
    host.subscribe(RESULT_TOPIC, events.append)

    def on_done(result, error):
        completions.append((result, error, threading.get_ident()))
        completed.set()

    try:
        assert service.submit("slow", 7, on_done=on_done) is True
        assert started.wait(5.0)
        assert calls and calls[0][1] != gui_thread
        qapp.processEvents()
        assert not completed.is_set()  # 调用还阻塞着，但 GUI 没被同步占住

        release.set()
        assert _pump_until(qapp, completed)
        assert completions == [({"ok": True, "value": 7}, None, gui_thread)]
        assert events and isinstance(events[0], SurfCoreResult)
        assert events[0].fn == "slow"
        assert events[0].result == {"ok": True, "value": 7}
        assert events[0].error is None
    finally:
        release.set()
        service.stop()


def test_submit_error_is_delivered_without_raising(qapp):
    gui_thread = threading.get_ident()

    class FailingClient:
        def explode(self):
            raise SurfCoreError("network")

    host = ModuleHostBase()
    service = SurfCoreService(FailingClient(), host)
    completed = threading.Event()
    completions: list[tuple[object, object, int]] = []

    def on_done(result, error):
        completions.append((result, error, threading.get_ident()))
        completed.set()

    try:
        assert service.submit("explode", on_done=on_done) is True
        assert _pump_until(qapp, completed)
        result, error, thread_id = completions[0]
        assert result is None
        assert isinstance(error, SurfCoreError)
        assert error.code == "network"
        assert thread_id == gui_thread
    finally:
        service.stop()


def test_focus_changed_posts_expected_body(tmp_path, qapp):
    api = FakePetApi()
    host_path = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host_path, timeout=2.0)
    host = ModuleHostBase()
    service = SurfCoreService(client, host)
    expected = {
        "enabled": True,
        "source": "desktop-pet",
        "phase": "work",
        "endsAt": 1700000000000,
    }
    def expected_is_last(rows: list[dict]) -> bool:
        bodies = _focus_bodies(rows)
        return bool(bodies) and bodies[-1] == expected

    try:
        host.emit(
            "focus.changed",
            {"enabled": True, "phase": "work", "endsAt": 1700000000000},
        )
        assert _pump_until_server(qapp, api, expected_is_last)
        assert _focus_bodies(api.snapshot())[-1] == expected
    finally:
        service.stop()
        api.close()


def test_focus_burst_ends_with_latest_state(tmp_path, qapp):
    api = FakePetApi()
    host_path = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host_path, timeout=2.0)
    host = ModuleHostBase()
    service = SurfCoreService(client, host)
    states = [
        {"enabled": True, "phase": f"phase-{index}", "endsAt": 1700000000000 + index}
        for index in range(4)
    ]
    states.append({"enabled": False, "phase": None, "endsAt": None})
    expected = {"enabled": False, "source": "desktop-pet"}

    def latest_is_last(rows: list[dict]) -> bool:
        bodies = _focus_bodies(rows)
        return bool(bodies) and bodies[-1] == expected

    try:
        for state in states:
            host.emit("focus.changed", state)
        assert _pump_until_server(qapp, api, latest_is_last)
        bodies = _focus_bodies(api.snapshot())
        # 突发事件允许合并，但最后一次必须是最新状态（可能只发 1 次）。
        assert 1 <= len(bodies) <= len(states)
        assert bodies[-1] == expected
    finally:
        service.stop()
        api.close()


def test_online_after_offline_resends_latest_focus_once(qapp):
    host = ModuleHostBase()
    client = RecordingFocusClient()
    service = SurfCoreService(client, host)
    state = {"enabled": True, "phase": "work", "endsAt": 1700000000000}
    expected = {
        "enabled": True,
        "phase": "work",
        "ends_at": 1700000000000,
        "source": "desktop-pet",
    }
    try:
        host.emit("focus.changed", state)
        assert _pump_until_calls(qapp, client, 1)
        assert client.snapshot() == [expected]

        assert service.online is False
        service.set_online(False)  # 本来就是离线：不算变化
        service.set_online(True)
        assert _pump_until_calls(qapp, client, 2)
        assert client.snapshot() == [expected, expected]

        # 已经是在线：再报一次在线不是状态变化，不重复重发。
        service.set_online(True)
        assert client.snapshot() == [expected, expected]
    finally:
        service.stop()


def test_failing_focus_is_logged_with_code_and_contained(qapp, caplog):
    caplog.set_level(logging.WARNING)
    host = ModuleHostBase()
    client = RecordingFocusClient(fail=True)
    service = SurfCoreService(client, host)
    first = {"enabled": True, "phase": "work", "endsAt": 1700000000000}
    second = {"enabled": False, "phase": None, "endsAt": None}
    try:
        host.emit("focus.changed", first)
        assert _pump_until_calls(qapp, client, 1)
        assert _wait_until(
            lambda: any(
                "SurfCore 专注同步失败：network" in record.getMessage()
                for record in caplog.records
            )
        )

        # 失败后服务还活着：后续事件照常同步，GUI 没收到异常。
        client.fail = False
        host.emit("focus.changed", second)
        assert _pump_until_calls(qapp, client, 2)
        assert client.snapshot()[-1] == {
            "enabled": False,
            "phase": None,
            "ends_at": None,
            "source": "desktop-pet",
        }

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "SurfCore 专注同步失败：network" in logged
        # 只记稳定错误码，不把 hint / URL / 令牌 / 专注内容带进日志。
        assert "暂时连不上 SurfCore" not in logged
        assert "token-a" not in logged
        assert not any("订阅者出错" in message for message in logged.splitlines())
    finally:
        service.stop()


def test_stop_is_prompt_with_pending_work(qapp):
    class BlockingClient:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()
            self.calls = 0

        def work(self):
            self.calls += 1
            self.started.set()
            self.release.wait(5.0)
            self.finished.set()
            return "ok"

    host = ModuleHostBase()
    client = BlockingClient()
    service = SurfCoreService(client, host)
    try:
        assert service.submit("work") is True
        assert service.submit("work") is True  # 排在阻塞中的任务后面
        assert client.started.wait(5.0)

        started = time.monotonic()
        service.stop()
        elapsed = time.monotonic() - started
        assert elapsed < 2.0
        assert service.submit("work") is False
    finally:
        client.release.set()
        assert client.finished.wait(5.0)
        assert client.calls == 1  # 待执行的任务被取消，没有跑第二次
        service.stop()
