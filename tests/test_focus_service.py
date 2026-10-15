"""Real Qt event delivery; fake only capture/network boundaries."""
from __future__ import annotations

import threading

import pytest

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from pet.config import Config
from pet.focus_mode import FocusSession
from pet.focus_service import FocusController


app = QApplication.instance() or QApplication([])


class Presentation(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.messages = []
        self.alerts = []
        self.resolved = []
        self.label = QLabel(self)
        self.show()

    def has_presentation_target(self):
        return self.isVisible()

    def show_bubble(self, text, duration_ms=0):
        assert QThread.currentThread() == self.thread()
        self.label.setText(text)
        self.messages.append(text)

    def show_alert(self, text, **kwargs):
        assert QThread.currentThread() == self.thread()
        self.alerts.append((text, kwargs))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)


def pump_until(predicate, timeout=10000):
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout)
    if not predicate():
        loop.exec()
    poll.stop()
    deadline.stop()
    assert predicate(), "Qt event delivery did not complete within the CI budget"


def setup_controller(tmp_path, *, clock=None):
    cfg = Config(base=tmp_path)
    cfg.set("focus_mode", {"work_context": "开发 Python 桌面应用，查文档也属于工作"})
    state = FocusSession(clock=clock) if clock is not None else FocusSession()
    target = Presentation(cfg)
    controller = FocusController(cfg, target, session=state, parent=app)
    return cfg, state, target, controller


def test_phase_boundaries_play_once_and_automatically_cycle_in_real_event_loop(tmp_path, monkeypatch):
    from pet import click_sound
    now = [0.0]
    cfg, state, target, controller = setup_controller(tmp_path, clock=lambda: now[0])
    sounds = []
    def play(path, volume):
        assert QThread.currentThread() == target.thread()
        sounds.append((path.name, volume))
        return True
    monkeypatch.setattr(click_sound, "play_sound", play)
    try:
        state.start({"work_minutes": 1})
        assert sounds == [("start.wav", 0.65)]
        state.pause()
        state.resume()
        assert len(sounds) == 1
        now[0] = 61
        pump_until(lambda: state.phase == "short_break")
        assert sounds[-1] == ("done.wav", 0.65) and len(sounds) == 2
        assert controller.timer.isActive()
        assert target.alerts == target.messages == []
        now[0] += state.remaining_seconds()
        pump_until(lambda: state.focusing)
        assert sounds[-1] == ("start.wav", 0.65) and len(sounds) == 3
        state.stop()
        state.stop()
        assert sounds[-1] == ("done.wav", 0.65) and len(sounds) == 4
        assert not controller.timer.isActive()
    finally:
        controller.stop()
        target.close()


def test_quiet_and_application_shutdown_do_not_play_focus_sound(tmp_path, monkeypatch):
    from pet import click_sound
    sounds = []
    cfg, state, target, controller = setup_controller(tmp_path)
    monkeypatch.setattr(click_sound, "play_sound", lambda *a, **k: sounds.append(True))
    monkeypatch.setattr("pet.window_alerts.quiet_blocked", lambda win: True)
    state.start()
    state.stop()
    assert sounds == []
    monkeypatch.setattr("pet.window_alerts.quiet_blocked", lambda win: False)
    state.start()
    assert sounds == [True]
    controller.stop()
    assert sounds == [True]
    target.close()


def test_front_window_only_and_persona_context_reach_visual_request(tmp_path, monkeypatch):
    from PIL import Image
    from pet import vision
    cfg, state, target, controller = setup_controller(tmp_path)
    calls = []
    monkeypatch.setattr("pet.focus_service.foreground_observation_available", lambda: True)
    monkeypatch.setattr(vision, "foreground_window_info", lambda: {"rect": (2, 3, 22, 23)})
    monkeypatch.setattr(vision, "capture_window_rect", lambda rect: Image.new("RGB", (20, 20)))

    def request(image, app_info, prompt, provider, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        assert kwargs["consume_budget"]()
        calls.append((image, prompt))
        return '{"assessment":"on_task","message":"认真看文档呢，我也陪着！"}'

    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        assert not controller.request_observation()
        assert not controller.timer.isActive()
        state.start()
        assert controller.timer.isActive()
        assert controller.request_observation()
        pump_until(lambda: not controller._busy)
        assert len(calls) == 1 and calls[0][0].startswith(b"\xff\xd8")
        assert "开发 Python" in calls[0][1]
        assert "大肥鱼" in calls[0][1]
        assert target.messages == ["认真看文档呢，我也陪着！"]
        state.pause()
        assert not controller.timer.isActive()
        assert not controller.request_observation()
    finally:
        controller.stop()


@pytest.mark.parametrize("transition", ["pause", "auto-break"])
def test_late_network_reply_cannot_speak_after_phase_change(tmp_path, monkeypatch, transition):
    from pet import vision
    now = [0.0]
    cfg, state, target, controller = setup_controller(tmp_path, clock=lambda: now[0])
    cfg.set("focus_mode", {"screen_enabled": False})
    entered = threading.Event()
    release = threading.Event()

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return "别忘了专注哦。"

    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        state.start()
        controller.request_observation()
        pump_until(entered.is_set)
        if transition == "pause":
            state.pause()
            state.resume()
        else:
            now[0] = 1500
            assert state.tick()
            assert state.phase == "short_break"
        assert not controller.request_observation()  # Still one worker, despite a new generation.
        release.set()
        pump_until(lambda: not controller._busy)
        assert target.messages == []
    finally:
        release.set()
        controller.stop()


def test_audio_device_failure_does_not_interrupt_automatic_cycle(tmp_path, monkeypatch):
    from pet import click_sound
    now = [0.0]
    cfg, state, target, controller = setup_controller(tmp_path, clock=lambda: now[0])
    def unavailable(*args, **kwargs):
        raise OSError("audio device unavailable")
    monkeypatch.setattr(click_sound, "play_sound", unavailable)
    try:
        state.start({"work_minutes": 1})
        assert controller.timer.isActive()
        now[0] = 61
        pump_until(lambda: state.phase == "short_break")
        assert controller.timer.isActive()
        assert target.alerts == []
    finally:
        controller.stop()
        target.close()


def test_context_edit_invalidates_in_flight_reply(tmp_path, monkeypatch):
    from pet import vision
    cfg, state, target, controller = setup_controller(tmp_path)
    cfg.set("focus_mode", {"screen_enabled": False, "work_context": "写代码"})
    release = threading.Event()
    entered = threading.Event()

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return "回来写代码。"

    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        state.start()
        controller.request_observation()
        pump_until(entered.is_set)
        cfg.set("focus_mode", {"screen_enabled": False, "work_context": "学习视频剪辑"})
        release.set()
        pump_until(lambda: not controller._busy)
        assert target.messages == []
    finally:
        release.set()
        controller.stop()


def test_pause_during_capture_prevents_a_new_http_request(tmp_path, monkeypatch):
    from PIL import Image
    from pet import vision
    cfg, state, target, controller = setup_controller(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    transmitted = []
    monkeypatch.setattr("pet.focus_service.foreground_observation_available", lambda: True)
    monkeypatch.setattr(vision, "foreground_window_info", lambda: {"rect": (0, 0, 20, 20)})

    def capture(rect):
        entered.set()
        assert release.wait(10)
        return Image.new("RGB", (20, 20))

    def request(*args, **kwargs):
        if kwargs["consume_budget"]():
            transmitted.append(True)
        return '{"assessment":"uncertain","message":""}'

    monkeypatch.setattr(vision, "capture_window_rect", capture)
    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        state.start()
        controller.request_observation()
        pump_until(entered.is_set)
        state.pause()
        release.set()
        pump_until(lambda: not controller._busy)
        assert transmitted == []
    finally:
        release.set()
        controller.stop()


def test_error_is_visible_and_does_not_stop_clock(tmp_path, monkeypatch):
    from pet import vision
    cfg, state, target, controller = setup_controller(tmp_path)
    cfg.set("focus_mode", {"screen_enabled": False})

    def request(*args, **kwargs):
        raise RuntimeError("model does not support images")

    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        state.start()
        controller.request_observation()
        pump_until(lambda: not controller._busy)
        assert "model does not support images" in state.observation
        assert state.focusing
        assert target.messages == []
    finally:
        controller.stop()


def test_off_task_speech_cooldown_and_uncertain_silence(tmp_path, monkeypatch):
    from types import SimpleNamespace
    now = [0.0]
    monkeypatch.setattr("pet.focus_service.time", SimpleNamespace(monotonic=lambda: now[0]))
    cfg, state, target, controller = setup_controller(tmp_path)
    try:
        state.start()
        controller._last_config = controller._preferences()
        controller._deliver(state.generation, "off_task", "回来工作啦。", "")
        controller._deliver(state.generation, "off_task", "再说一次。", "")
        now[0] += 301
        controller._deliver(state.generation, "uncertain", "", "")
        assert target.messages == ["回来工作啦。"]
        assert "不足以判断" in state.observation
    finally:
        controller.stop()
