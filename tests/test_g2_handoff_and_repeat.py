# -*- coding: utf-8 -*-
"""G2 R7：合法重复文本不被去重误删（单宠 slot0）。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import click_sound  # noqa: E402
from pet.speech_bubble import PetSpeechBubble  # noqa: E402
from tests.helpers.overlay_shell import _make_slot_shell  # noqa: E402

app = QApplication.instance() or QApplication([])

ALERT_TEXT = "Agent 需要你批准一条命令"


@pytest.fixture
def probes(monkeypatch):
    shown: list[tuple[object, str]] = []
    sounds: list[object] = []
    original = PetSpeechBubble.show_text

    def recording_show_text(self, text, *args, **kwargs):
        shown.append((self, str(text)))
        return original(self, text, *args, **kwargs)

    def fake_play(self, path, volume=1.0):
        sounds.append(path)
        return True

    monkeypatch.setattr(PetSpeechBubble, "show_text", recording_show_text)
    monkeypatch.setattr(click_sound.ClickSoundPool, "play_sound", fake_play)
    return shown, sounds


def _visible_copies(shell, text):
    follower = getattr(shell, "_bubble_follower", None)
    bubble = follower.bubble if follower is not None else None
    if bubble is not None and bubble.isVisible() and getattr(bubble, "_raw_text", "") == text:
        return [bubble]
    return []


def _cleanup(shell):
    try:
        shell.stop()
    finally:
        shell._delete_runtime_marker()


def test_r7_same_text_distinct_ids_both_presented_in_order(tmp_path, probes):
    shown, _sounds = probes
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT, alert_id="a1")
        shell.show_alert(ALERT_TEXT, alert_id="a2")
        assert shell._alert_current["id"] == "a1"
        assert [q["id"] for q in shell._alert_queue] == ["a2"]
        assert [t for _b, t in shown].count(ALERT_TEXT) == 1

        shell.resolve_alert("a1")
        app.processEvents()
        assert shell._alert_current is not None
        assert shell._alert_current["id"] == "a2"
        assert [t for _b, t in shown].count(ALERT_TEXT) >= 2
        assert len(_visible_copies(shell, ALERT_TEXT)) == 1

        shell.resolve_alert("a2")
        app.processEvents()
        assert shell._alert_current is None
        assert not shell._alert_queue
        assert _visible_copies(shell, ALERT_TEXT) == []
    finally:
        _cleanup(shell)


def test_r7_resolving_queued_twin_keeps_current(tmp_path, probes):
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT, alert_id="a1")
        shell.show_alert(ALERT_TEXT, alert_id="a2")
        shell.resolve_alert("a2")
        assert shell._alert_current["id"] == "a1"
        assert not shell._alert_queue
        assert len(_visible_copies(shell, ALERT_TEXT)) == 1
    finally:
        _cleanup(shell)


def test_r7_same_id_merges(tmp_path, probes):
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT, alert_id="a1")
        shell.show_alert(ALERT_TEXT + "（更新）", alert_id="a1")
        assert shell._alert_current["id"] == "a1"
        assert shell._alert_current["text"] == ALERT_TEXT + "（更新）"
        assert not shell._alert_queue

        shell.show_alert("排队旧文案", alert_id="b1")
        shell.show_alert("排队新文案", alert_id="b1")
        assert [q["text"] for q in shell._alert_queue] == ["排队新文案"]
    finally:
        _cleanup(shell)


def test_r7_same_text_without_id_not_deduped(tmp_path, probes):
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT)
        shell.show_alert(ALERT_TEXT)
        assert shell._alert_current["text"] == ALERT_TEXT
        assert [q["text"] for q in shell._alert_queue] == [ALERT_TEXT]
    finally:
        _cleanup(shell)


def _make_link_mgr(tmp_path, agent_link_cfg=None):
    from pet.modules.agent_link.agent_link import AgentLinkManager
    from pet.config import Config

    bubbles: list[str] = []

    class DummyWin:
        cats = {"acts": ["写代码"]}
        idles = ["待机呼吸"]
        _bubble_busy_until = 0.0

        def isVisible(self):  # noqa: N802
            return True

        def _switch(self, name):
            pass

        def show_bubble(self, text, duration_ms=3000):
            bubbles.append(text)

        def _pick(self, lst):
            return lst[0]

        def request_link_anim(self, name):
            pass

        def request_link_idle(self):
            pass

    cfg = Config(base=tmp_path)
    data = cfg.data
    data["dialogue_mode"] = "custom"
    data["dialogue_phrases"] = {"activity.read": ["同一句过程汇报"]}
    if agent_link_cfg is not None:
        data["agent_link"] = {**data.get("agent_link", {}), **agent_link_cfg}
    cfg.save()
    clock = [1000.0]
    mgr = AgentLinkManager(DummyWin(), cfg, min_interval=2.0, clock=lambda: clock[0])
    return mgr, bubbles, clock


def test_r7_agent_link_identical_activity_after_cooldown_both_surface(tmp_path):
    mgr, bubbles, clock = _make_link_mgr(tmp_path)
    mgr._on_agent_activity("dsh", "read")
    assert bubbles == ["同一句过程汇报"]

    clock[0] += 30.0
    mgr._on_agent_activity("dsh", "read")
    assert len(bubbles) == 1

    clock[0] += mgr._ACTIVITY_SAME_LABEL + 1.0
    mgr._on_agent_activity("dsh", "read")
    assert bubbles == ["同一句过程汇报", "同一句过程汇报"]


def test_r7_agent_link_repeated_sound_after_cooldown_plays_again(tmp_path, monkeypatch):
    from pet.modules.agent_link import agent_link

    played: list[object] = []
    monkeypatch.setattr(agent_link, "play_sound",
                        lambda path, volume=1.0: played.append(path) or True)
    mgr, _bubbles, clock = _make_link_mgr(
        tmp_path, {"sound_enabled": True, "sound_cooldown_seconds": 2.0})
    if agent_link.resolve_builtin_sound("builtin:agent-done") is None:
        pytest.skip("内置 agent-done 音效缺失")
    mgr._emit_sound("done", "dsh")
    assert len(played) == 1
    clock[0] += 1.0
    mgr._emit_sound("done", "dsh")
    assert len(played) == 1
    clock[0] += 2.5
    mgr._emit_sound("done", "dsh")
    assert len(played) == 2
