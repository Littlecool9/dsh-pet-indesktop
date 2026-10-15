"""Focus lifecycle and Qt integration through the public session/widget seams."""
from __future__ import annotations

import json

import pytest

from pet.focus_mode import FocusSession, focus_prompt, normalize_focus_config, parse_observation


def test_full_cycle_waits_for_user_and_long_break_after_four_focuses():
    now = [0.0]
    session = FocusSession(clock=lambda: now[0])
    for index in range(4):
        session.start()
        assert session.focusing
        assert session.remaining_seconds() == 1500
        now[0] += 1501
        assert session.tick()
        assert session.status == "waiting"
        assert session.completed == index + 1
        assert session.next_phase == ("long_break" if index == 3 else "short_break")
        now[0] += 3600
        assert not session.tick()  # No unattended cycles after sleep or a long wait.
        session.start()
        assert not session.focusing
        assert session.remaining_seconds() == (900 if index == 3 else 300)
        now[0] += session.remaining_seconds()
        session.tick()
    assert session.next_phase == "focus"


def test_pause_resume_stop_and_deadline_are_independent_of_tick_count():
    now = [10.0]
    session = FocusSession(clock=lambda: now[0])
    session.start({"work_minutes": 2})
    now[0] += 32
    session.pause()
    assert session.remaining_seconds() == 88
    token = session.generation
    now[0] += 500
    assert not session.tick()
    session.resume()
    assert session.generation > token
    assert session.remaining_seconds() == 88
    now[0] += 88
    session.tick()
    session.stop()
    assert not session.engaged
    assert session.completed == 0


@pytest.mark.parametrize("raw", [None, [], "bad", {"work_minutes": float("nan")},
                                  {"work_minutes": True, "screen_enabled": "false"}])
def test_dirty_preferences_are_safe(raw):
    cfg = normalize_focus_config(raw)
    assert 1 <= cfg["work_minutes"] <= 180
    assert isinstance(cfg["screen_enabled"], bool)


def test_work_context_is_persistent_global_preference(tmp_path):
    from pet.config import Config
    from pet.settings_slot_config import route_settings_config

    cfg = route_settings_config(Config(base=tmp_path, instance_id="slot-2"))
    cfg.set("scale", 1.2)
    cfg.set("focus_mode", {"work_context": "研究 Qt 文档；相关视频也属于工作", "work_minutes": 40})
    cfg.save()
    main = Config(base=tmp_path)
    assert main.get("focus_mode")["work_context"].startswith("研究 Qt")
    assert main.get("focus_mode")["work_minutes"] == 40
    raw = json.loads((cfg.dir / "config-slot-2.json").read_text(encoding="utf-8"))
    assert "focus_mode" not in raw


def test_prompt_preserves_persona_and_treats_related_research_fairly():
    prompt = focus_prompt("你是一只有点迷糊的大肥鱼。", "开发登录接口，查文档和教程", visual=True)
    assert "迷糊的大肥鱼" in prompt
    assert "开发登录接口" in prompt
    assert "uncertain" in prompt and "off_task" in prompt and "on_task" in prompt
    assert "不可信" in prompt  # Screenshot text cannot become instructions.
    assert "教程" in prompt


def test_invalid_or_uncertain_observation_does_not_accuse_user():
    assert parse_observation("you are distracted") == ("uncertain", "")
    assert parse_observation('{"assessment":"off_task","message":"回来写代码啦。"}') == (
        "off_task", "回来写代码啦。")
    assert parse_observation('```json\n{"assessment":"uncertain","message":""}\n```') == ("uncertain", "")


def test_official_deepseek_uses_current_vision_model_but_other_hosts_keep_their_model():
    from pet.chat.models import ProviderConfig
    from pet.vision import resolve_vision_model

    assert resolve_vision_model(ProviderConfig("ds")) == "deepseek-flash"
    p = ProviderConfig("third", base_url="https://example.test", model="deepseek-v4-flash")
    assert resolve_vision_model(p) == "deepseek-v4-flash-vision-exp"


def test_focus_settings_and_island_controls_are_real_widgets(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton, QPlainTextEdit
    from pet.config import Config
    import pet.modern_settings_dialog as settings_mod
    from pet.dynamic_island import DynamicIsland
    from pet.focus_mode import shared_focus_session

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    cfg = Config(base=tmp_path)
    dialog = settings_mod.ModernSettingsDialog(cfg, include_ai=True)
    island = DynamicIsland(cfg)
    state = shared_focus_session()
    try:
        editor = dialog.findChild(QPlainTextEdit, "focusWorkContext")
        assert editor is not None
        assert editor.tabChangesFocus()
        dialog.show()
        dialog.search_edit.setText("番茄钟")
        app.processEvents()
        assert "未找到" not in dialog.search_status.text()
        editor.setPlainText("写专注模式，阅读代码也算工作")
        dialog._write_config()
        assert Config(base=tmp_path).get("focus_mode")["work_context"].startswith("写专注")
        start = island.findChild(QPushButton, "focusStartPause")
        assert start is not None
        start.click()
        assert state.focusing
        assert "专注" in island._info_text()
        start.click()
        assert state.status == "paused"
        island.findChild(QPushButton, "focusEnd").click()
        assert not state.engaged
    finally:
        state.stop()
        island.close()
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("platform,enabled", [("win32", True), ("linux", False), ("darwin", False)])
def test_focus_foreground_control_explains_platform_and_preserves_preference(tmp_path, monkeypatch, platform, enabled):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget
    from pet.config import Config
    import pet.settings_focus as settings
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "sys", SimpleNamespace(platform=platform))
    dialog = QWidget()
    dialog.config = Config(base=tmp_path)
    try:
        rows = settings.build_focus_rows(dialog)
        assert dialog.focus_screen_enabled.isEnabled() is enabled
        assert "Windows" in rows[-1].hint_label.text()
        settings.save_focus_settings(dialog)
        assert dialog.config.get("focus_mode")["screen_enabled"] is True
    finally:
        dialog.close()
        app.processEvents()


def test_destroyed_island_does_not_keep_a_focus_listener(tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import shiboken6
    from pet.config import Config
    from pet.dynamic_island import DynamicIsland
    from pet.focus_mode import shared_focus_session

    app = QApplication.instance() or QApplication([])
    island = DynamicIsland(Config(base=tmp_path))
    island.deleteLater()  # Native deletion can bypass closeEvent.
    QCoreApplication.sendPostedEvents(island, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(island)
    state = shared_focus_session()
    try:
        state.start()
        assert state.focusing
    finally:
        state.stop()
        app.processEvents()
