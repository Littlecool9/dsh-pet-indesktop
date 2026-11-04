# -*- coding: utf-8 -*-
"""SpriteSoundPlayer + shell 点击音效接线 offscreen 单测（4.1c）。

覆盖：点击音量走 click_sound_volume、80ms 节流、启用门在延迟回调前翻转即不发声、
开关关掉再打开能恢复（门与音源都不被缓存钉死）、解析失败静默降级、
shell 单击路由触发 click_feedback。
play_sound 全程打桩，不出声。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import click_sound
from pet.sprite_sound import SpriteSoundPlayer

app = QApplication.instance() or QApplication([])


class _Cfg:
    def __init__(self, values=None):
        self._v = dict(values or {})
        self.dir = None

    def get(self, key, default=None):
        return self._v.get(key, default)


def _pump():
    # 播放已改事件循环下一轮提交（tick 路径零阻塞）：抽干 0ms 定时器
    QApplication.processEvents()
    QApplication.processEvents()


def _player(monkeypatch, values=None, clock=None):
    plays = []
    monkeypatch.setattr(click_sound, "play_sound",
                        lambda path, volume: plays.append(volume) or True)
    monkeypatch.setattr(click_sound, "resolve_click_sound_candidates",
                        lambda pack, data_dir=None: ["/tmp/click.wav"])
    # 先把上一条用例延后提交的那一声抽干再清表：播放走
    # ``QTimer.singleShot(0)`` 且音效池是进程级的。
    _pump()
    plays.clear()
    player = SpriteSoundPlayer(_Cfg(values), clock=clock or (lambda: 1000.0))
    return player, plays


def test_click_volume_from_config(monkeypatch):
    player, plays = _player(monkeypatch, {"click_sound_volume": 0.3})
    player.on_click()
    _pump()
    assert plays == [0.3]


def test_throttle(monkeypatch):
    now = [1000.0]
    player, plays = _player(monkeypatch, clock=lambda: now[0])
    player.on_click()
    player.on_click()                               # 80ms 内第二次被节流
    _pump()
    assert len(plays) == 1
    now[0] += 0.1
    player.on_click()
    _pump()
    assert len(plays) == 2


def test_click_gate_off_is_silent(monkeypatch):
    player, plays = _player(monkeypatch, {"click_sound_enabled": False})
    player.on_click()
    _pump()
    assert plays == []


def test_resolve_failure_degrades(monkeypatch):
    plays = []
    monkeypatch.setattr(click_sound, "play_sound",
                        lambda path, volume: plays.append(volume))

    def boom(pack, data_dir=None):
        raise RuntimeError("no pack")

    monkeypatch.setattr(click_sound, "resolve_click_sound_candidates", boom)
    player = SpriteSoundPlayer(_Cfg())
    player.on_click()                               # 不抛异常
    _pump()
    assert plays == []


def _gated_player(monkeypatch, values=None):
    """记录 ``(path, volume)`` 的播放器；音源随 pack 身份变化（供缓存失效用例）。"""
    cfg = _Cfg(values)
    events = []
    monkeypatch.setattr(click_sound, "play_sound",
                        lambda path, volume: events.append((str(path), volume)) or True)
    monkeypatch.setattr(
        click_sound, "resolve_click_sound_candidates",
        lambda pack, data_dir=None: [
            "/tmp/%s.wav" % ((pack if isinstance(pack, dict) else {}) or {}).get("id", "default")])
    player = SpriteSoundPlayer(cfg, clock=lambda: 1000.0)
    return player, events, cfg


def test_enable_gate_defaults_on(monkeypatch):
    player, events, _ = _gated_player(monkeypatch)
    player.on_click()
    _pump()
    assert events == [("/tmp/default.wav", 0.70)]


def test_gate_reopen_plays_again(monkeypatch):
    """门关过再打开必须恢复：禁用/无音源都不得被缓存钉死。"""
    player, events, cfg = _gated_player(monkeypatch, {"click_sound_enabled": False})
    player.on_click()
    _pump()
    assert events == []
    cfg._v["click_sound_enabled"] = True
    player._last_play = 0.0
    player.on_click()
    _pump()
    assert len(events) == 1


def test_gate_flip_before_deferred_play_cancels(monkeypatch):
    """排队后、延迟回调执行前关掉门 → 不发声（旧实现门判在 play_sound 之前）。"""
    player, events, cfg = _gated_player(monkeypatch)
    player.on_click()                               # 已排队
    cfg._v["click_sound_enabled"] = False           # 回调执行前关掉
    _pump()
    assert events == []


def test_pack_change_resolves_new_source(monkeypatch):
    """音效包变化不复用旧音源（旧实现：window.py:3245）。"""
    player, events, cfg = _gated_player(
        monkeypatch, {"click_sound_pack": {"kind": "builtin", "id": "duck"}})
    player.on_click()
    _pump()
    assert events == [("/tmp/duck.wav", 0.70)]
    cfg._v["click_sound_pack"] = {"kind": "builtin", "id": "default"}
    player._last_play = 0.0
    player.on_click()
    _pump()
    assert events[-1] == ("/tmp/default.wav", 0.70)


def test_pack_id_mutated_in_place_resolves_new_source(monkeypatch):
    """config 里的 pack **原对象**被原地改 id → 不得复用旧音源。

    缓存键若持 pack 同一引用，``==`` 会拿对象和它自己比、判不出变化。
    """
    pack = {"kind": "builtin", "id": "duck"}
    events, seen = [], []
    monkeypatch.setattr(click_sound, "play_sound",
                        lambda path, volume: events.append((str(path), volume)) or True)

    def resolve(received, data_dir=None):
        seen.append(received)
        fields = received if isinstance(received, dict) else {}
        return ["/tmp/%s.wav" % (fields or {}).get("id", "default")]

    monkeypatch.setattr(click_sound, "resolve_click_sound_candidates", resolve)
    player = SpriteSoundPlayer(_Cfg({"click_sound_pack": pack}),
                               clock=lambda: 1000.0)
    player.on_click()
    _pump()
    assert events == [("/tmp/duck.wav", 0.70)]
    assert seen[0] is pack                          # 解析参数仍是原 pack
    pack["id"] = "default"                          # 原地改同一对象
    player._last_play = 0.0
    player.on_click()
    _pump()
    assert events[-1] == ("/tmp/default.wav", 0.70)


def test_click_volume_zero_is_silent(monkeypatch):
    """0% 是合法用户值（设置页 0~100%），不得被当作缺省回退成 0.70。"""
    player, plays = _player(monkeypatch, {"click_sound_volume": 0.0})
    player.on_click()
    _pump()
    assert plays == [0.0]


@pytest.mark.parametrize("bad", [None, "loud"])
def test_click_volume_unparsable_falls_back_to_default(monkeypatch, bad):
    """读不到的数按 config 既有缺省处理（同 ``_float_or_default`` 口径）。"""
    player, plays = _player(monkeypatch, {"click_sound_volume": bad})
    player.on_click()
    _pump()
    assert plays == [0.70]


def test_click_gate_picks_from_the_whole_candidate_list(monkeypatch, tmp_path):
    """点击门在多文件包里**现挑**，不再固定文件名排序第一那个（issue #308）。

    设置页对「自定义文件夹（随机）」的承诺就是随机播放；旧实现取 ``candidates[0]``，
    整个进程内永远播同一个文件。
    """
    files = [tmp_path / f"{index}.mp3" for index in range(3)]
    monkeypatch.setattr(click_sound, "resolve_click_sound_candidates",
                        lambda pack, data_dir=None: list(files))
    played = []
    monkeypatch.setattr(click_sound, "play_sound",
                        lambda path, volume: played.append((path, volume)) or True)
    picks: list[int] = []

    def choose(paths):
        picks.append(len(paths))
        return paths[len(picks) - 1]          # 每次换一个 → 证明真的走了现挑

    monkeypatch.setattr(click_sound, "choose_sound", choose)
    player = SpriteSoundPlayer(
        _Cfg({"click_sound_pack": {"kind": "folder", "path": str(tmp_path)}}),
        clock=lambda: 1000.0)
    for _ in range(3):
        player._last_play = 0.0
        player.on_click()
        _pump()

    assert picks == [3, 3, 3], "点击门必须把**整个**候选列表交给 choose_sound"
    paths = [str(path) for path, _ in played]
    assert len(set(paths)) > 1, f"多文件包点击必须换文件，实际：{paths}"


# ---------------------------------------------------------------- shell 接线
def test_shell_click_feedback_routing(tmp_path, monkeypatch):
    import tests.test_overlay_window_capabilities as cap

    shell = cap._make_shell(tmp_path)
    try:
        clicks = []
        shell.overlay.click_feedback = lambda: clicks.append(1)
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        sprite = shell.sprite
        center = sprite.rect().center()
        shell.overlay._mouse_grab = sprite
        shell.overlay._press_pos = QPointF(center)
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(center), QPointF(center),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        shell.overlay.behavior = type("B", (), {
            "on_sprite_clicked": lambda self, s: True})()
        shell.overlay.mouseReleaseEvent(event)
        assert clicks == [1]
        # 抽干 _submit 排到下一轮事件循环的延迟播放。
        _pump()
    finally:
        shell._delete_runtime_marker()
