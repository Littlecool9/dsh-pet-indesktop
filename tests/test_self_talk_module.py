# -*- coding: utf-8 -*-
"""自言自语模块：每小时一条 SurfCore 生成台词的降级矩阵。

用假 ``surfcore`` 服务（只暴露 ``online`` + ``submit``）挂在真实
``ModuleHostBase`` 上，模块经服务表取值；时钟注入推进 3600 秒，不 sleep。
覆盖：在线首槽用生成台词、小时内回落预设、成功时刻起算、任何失败/离线/
服务缺失/排队失败均回退本地、关闭时绝不 submit。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pet.modules.host import ModuleHostBase
from pet.modules.self_talk.module import (
    SURFCORE_INTERVAL_SECONDS,
    SelfTalkModule,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeConfig:
    def __init__(self, **overrides) -> None:
        self.values = {
            "self_talk_enabled": True,
            "self_talk_texts": ["本地台词"],
            "self_talk_duration_seconds": 1.0,
            "self_talk_min_interval": 5.0,
            "self_talk_max_interval": 5.0,
            "self_talk_image_chance": 0,
            "self_talk_image_dir": "",
            "self_talk_image_scale": 100,
        }
        self.values.update(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeService:
    def __init__(self, *, online=True, result=None, error=None, accepted=True,
                 auto=True) -> None:
        self.online = online
        self.result = result
        self.error = error
        self.accepted = accepted
        self.auto = auto
        self.calls: list[tuple[str, tuple, object]] = []
        self.on_done = None

    def submit(self, fn_name, *args, on_done=None, **kwargs):
        self.calls.append((fn_name, args, on_done))
        self.on_done = on_done
        if not self.accepted:
            return False
        if self.auto:
            on_done(self.result, self.error)
        return True

    def complete(self, result=None, error=None) -> None:
        self.on_done(result, error)


class FakeHost(ModuleHostBase):
    def __init__(self, config, service=None) -> None:
        super().__init__()
        self.config = config
        self.shown: list[dict] = []
        self.prepared: list[dict] = []
        self.ready = True
        self.accept_show = True
        if service is not None:
            self.provide("surfcore", service)

    def pet_config(self):
        return self.config

    def self_talk_ready(self) -> bool:
        return self.ready

    def prepare_self_talk(self, *, images, image_scale) -> None:
        self.prepared.append({"images": list(images), "image_scale": image_scale})

    def show_self_talk(self, *, text=None, image=None, duration_ms=3200,
                       image_scale=None) -> bool:
        self.shown.append({
            "text": text, "image": image,
            "duration_ms": duration_ms, "image_scale": image_scale,
        })
        return self.accept_show


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _make(config=None, service=None, clock=None):
    config = config or FakeConfig()
    host = FakeHost(config, service)
    module = SelfTalkModule(clock=clock or FakeClock())
    module.start(host)
    module.apply_config(config)
    return module, host


# ---------------------------------------------------------------- 成功路径
def test_first_due_slot_uses_surfcore_line(qapp):
    service = FakeService(result={"ok": True, "text": "  模型这一句。 "})
    module, host = _make(service=service)
    try:
        assert module.timer.isActive() is True
        module.handle_timeout()

        assert len(service.calls) == 1
        fn_name, args, _callback = service.calls[0]
        assert fn_name == "self_talk"
        assert args == ({"reason": "idle"},), "上下文只允许 reason=idle"
        assert host.shown[-1]["text"] == "模型这一句。"
        assert host.shown[-1]["duration_ms"] == 1000
        assert module.last_surfcore_at == 1000.0
        assert module.timer.interval() == 6000  # 5s + 显示 1s
    finally:
        module.stop()


def test_within_the_hour_next_slots_use_presets(qapp):
    service = FakeService(result={"ok": True, "text": "模型这一句。"})
    clock = FakeClock()
    module, host = _make(service=service, clock=clock)
    try:
        module.handle_timeout()
        assert len(service.calls) == 1

        clock.advance(100.0)
        module.handle_timeout()
        assert len(service.calls) == 1, "一小时内不得再次请求"
        assert host.shown[-1]["text"] == "本地台词"

        clock.advance(SURFCORE_INTERVAL_SECONDS - 100.0)
        module.handle_timeout()  # 恰好满一小时：允许下一句
        assert len(service.calls) == 2
        assert host.shown[-1]["text"] == "模型这一句。"
    finally:
        module.stop()


def test_hour_is_measured_from_last_success_not_from_attempts(qapp):
    service = FakeService(result={"ok": True, "text": "生成"})
    clock = FakeClock()
    module, _host = _make(service=service, clock=clock)
    try:
        module.handle_timeout()
        assert len(service.calls) == 1
        clock.advance(3000.0)
        module.handle_timeout()
        assert len(service.calls) == 1
        clock.advance(600.0)
        module.handle_timeout()
        assert len(service.calls) == 2
    finally:
        module.stop()


# ---------------------------------------------------------------- 降级路径
@pytest.mark.parametrize("error", [RuntimeError("network"), Exception("budget-blocked")])
def test_any_error_falls_back_to_local_line(qapp, error):
    service = FakeService(result=None, error=error)
    module, host = _make(service=service)
    try:
        module.handle_timeout()
        assert len(service.calls) == 1
        assert host.shown[-1]["text"] == "本地台词"
        assert module.last_surfcore_at is None, "失败不得占用每小时额度"
        assert module.timer.isActive() is True
    finally:
        module.stop()


def test_success_response_without_text_falls_back_to_local(qapp):
    service = FakeService(result={"ok": False, "code": "empty-reply"})
    module, host = _make(service=service)
    try:
        module.handle_timeout()
        assert host.shown[-1]["text"] == "本地台词"
        assert module.last_surfcore_at is None
    finally:
        module.stop()


def test_offline_service_never_submits(qapp):
    service = FakeService(online=False, result={"ok": True, "text": "不该出现"})
    module, host = _make(service=service)
    try:
        module.handle_timeout()
        assert service.calls == []
        assert host.shown[-1]["text"] == "本地台词"
    finally:
        module.stop()


def test_missing_service_never_submits(qapp):
    module, host = _make(service=None)
    try:
        module.handle_timeout()
        assert host.shown[-1]["text"] == "本地台词"
    finally:
        module.stop()


def test_submit_rejected_falls_back_without_stalling_timer(qapp):
    service = FakeService(accepted=False)
    module, host = _make(service=service)
    try:
        module.handle_timeout()
        assert len(service.calls) == 1
        assert host.shown[-1]["text"] == "本地台词"
        assert module.timer.isActive() is True
    finally:
        module.stop()


def test_disabled_self_talk_never_submits(qapp):
    config = FakeConfig(self_talk_enabled=False)
    service = FakeService(result={"ok": True, "text": "不该出现"})
    module, host = _make(config=config, service=service)
    try:
        assert module.timer.isActive() is False
        module.handle_timeout()
        assert service.calls == []
        assert host.shown == []
    finally:
        module.stop()


def test_hidden_pet_does_not_consume_surfcore_slot(qapp):
    service = FakeService(result={"ok": True, "text": "不该出现"})
    module, host = _make(service=service)
    try:
        host.ready = False
        module.handle_timeout()
        assert service.calls == []
        assert host.shown == []
        assert module.timer.isActive() is True
    finally:
        module.stop()


def test_visibility_toggle_stops_and_reschedules(qapp):
    module, _host = _make(service=FakeService(result={"ok": True, "text": "x"}))
    try:
        module.set_visible(False)
        assert module.timer.isActive() is False
        module.set_visible(True)
        assert module.timer.isActive() is True
    finally:
        module.stop()
