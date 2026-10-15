"""Local smoke checks for elapsed focus time, end greeting and bounded notes."""
import json

from pet.focus_mode import FocusSession


def test_elapsed_focus_excludes_pauses_and_breaks_and_survives_stop():
    now = [0.0]
    state = FocusSession(clock=lambda: now[0])
    state.start({"work_minutes": 1})
    now[0] = 20
    state.pause()
    now[0] = 100
    state.resume()
    now[0] = 140
    assert state.tick()
    assert state.phase == "short_break"
    now[0] += 500
    state.tick()
    now[0] += 17
    state.stop()
    assert state.last_finished == {"focus_seconds": 77, "completed": 1}
    state.stop()
    assert state.last_finished["focus_seconds"] == 77
    state.start()
    now[0] += 3
    state.stop()
    assert state.last_finished["focus_seconds"] == 3


def test_memory_rejects_uncertain_claims_and_uses_literal_duration():
    from pet.focus_notes import FocusNotes, parse_work_memory
    notes = FocusNotes()
    notes.remember("on_task", "阅读 QTimer 文档", "这{focus_duration}也太费鱼脑袋啦，辛苦啦！", "shenshen")
    assert notes.closing(125, "shenshen") == "这2分5秒也太费鱼脑袋啦，辛苦啦！"
    assert "QTimer" not in notes.closing(125, "nova")  # Other personas do not inherit the cached wording.
    assert parse_work_memory('{"assessment":"uncertain","work_summary":"完成整个项目","closing_template":"干完啦"}') == ("", "")
    for index in range(20):
        notes.remember("on_task", f"阅读文档 {index}", "", "shenshen")
    assert len(notes.work) == 6


def test_a_complete_phase_counts_the_full_duration_with_a_real_advancing_clock():
    now = [0.0]
    def clock():
        now[0] += 0.001
        return now[0]
    state = FocusSession(clock=clock)
    state.start({"work_minutes": 1})
    now[0] = 100
    state.tick()
    state.stop()
    assert state.last_finished["focus_seconds"] == 60


def test_finished_history_is_small_and_preserves_a_broken_file(tmp_path):
    from pet.focus_notes import FocusHistory
    history = FocusHistory(tmp_path / "focus_sessions.json")
    for index in range(15):
        history.record({"focus_seconds": index, "completed": 0, "work_context": "写代码",
                        "observed_work": ["阅读文档"]})
    assert history.flush(10)
    data = json.loads(history.path.read_text(encoding="utf-8"))
    assert len(data["sessions"]) == 10
    assert data["sessions"][-1]["focus_seconds"] == 14
    assert history.path.stat().st_size < 32768
    history.path.write_text("broken", encoding="utf-8")
    history.record({"focus_seconds": 1})
    assert not history.flush(10)
    assert history.path.read_text(encoding="utf-8") == "broken"


def test_stop_uses_seen_work_without_an_extra_request_and_starts_fresh(tmp_path, monkeypatch):
    from PIL import Image
    from pet import vision
    from tests.test_focus_service import setup_controller, pump_until
    now = [0.0]
    cfg, state, target, controller = setup_controller(tmp_path, clock=lambda: now[0])
    calls = []
    monkeypatch.setattr("pet.focus_service.foreground_observation_available", lambda: True)
    monkeypatch.setattr(vision, "foreground_window_info", lambda: {"rect": (0, 0, 20, 20)})
    monkeypatch.setattr(vision, "capture_window_rect", lambda rect: Image.new("RGB", (20, 20)))
    def request(*args, **kwargs):
        calls.append(True)
        return json.dumps({"assessment": "on_task", "message": "看文档呢。", "work_summary": "阅读 QTimer 文档",
                           "closing_template": "陪你看了{focus_duration}的定时器文档，辛苦啦，鱼脑袋也要歇一下！"})
    monkeypatch.setattr(vision, "_post_vision_request", request)
    try:
        state.start()
        assert controller.request_observation()
        pump_until(lambda: not controller._busy)
        now[0] = 125
        state.stop()
        assert len(calls) == 1
        assert len(target.alerts) == 1
        assert "2分5秒" in target.alerts[0][0] and "定时器文档" in target.alerts[0][0]
        assert controller.history.flush(10)
        saved = json.loads((cfg.dir / "focus_sessions.json").read_text(encoding="utf-8"))["sessions"][-1]
        assert saved["observed_work"] == ["阅读 QTimer 文档"]
        assert saved["focus_seconds"] == 125
        state.stop()
        assert len(target.alerts) == 1
        state.start()
        now[0] += 5
        state.stop()
        assert "定时器文档" not in target.alerts[-1][0]
        assert "5秒" in target.alerts[-1][0]
    finally:
        controller.stop()
        target.close()


def test_quiet_and_application_shutdown_do_not_greet(tmp_path, monkeypatch):
    from tests.test_focus_service import setup_controller
    cfg, state, target, controller = setup_controller(tmp_path)
    monkeypatch.setattr("pet.window_alerts.quiet_blocked", lambda win: True)
    state.start()
    state.stop()
    assert target.alerts == target.messages == []
    state.start()
    monkeypatch.setattr("pet.window_alerts.quiet_blocked", lambda win: False)
    controller.stop()
    assert target.alerts == target.messages == []
    target.close()
