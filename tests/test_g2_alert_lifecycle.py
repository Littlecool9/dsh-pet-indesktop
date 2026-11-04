# -*- coding: utf-8 -*-
"""G2 提醒生命周期收口：承载宠迁移 / 剩余 TTL / 有界队列 / 迁移与重启纪律。

裁决（本轮规范，逐条对应下面的用例）：

1. **承载宠可迁移**：一条有效提醒正在某只宠的气泡上呈现时，那只宠退出 / 逐只隐藏 /
   屏迁移（跟随器重建）→ 只要还有别的可见宠，整条提醒**交给新的可见目标**：
   同 event ID、同剩余 TTL、**不重新入队**、不出声、**恰好一份可见副本**。
2. **主位恢复不抢回**：slot0 回来（生成或显示）只影响**此后新产生**的事件；
   当前提醒继续留在仍然有效的承载宠上，不重挂、不重放。
3. **收口针对实际承载气泡**：``resolve_alert`` / ``hide_bubble`` / ``clear_alerts``
   收掉的是**真正在展示那条提醒**的气泡，而不是"当前动态目标"的空气泡。
4. **无宠 / 全隐藏**：不触碰已销毁的 QObject；current 可以留着待恢复，但
   ``resolved`` 必须**立即清掉且不复活**。
5. **限时提醒不永生**：非 sticky 提醒跨迁移按**剩余** TTL 重挂，绝不每次都重置整段时长。
6. **队列有界**：待处理条目上限 64（另加 1 条 current 展示位）；同 ID 更新不计增量；
   满时优先保高优先级（淘汰最低优先级里最旧的一条，或拒收更低优先级的新条），
   且必须可诊断（warning + 计数），不弹无限汇总、不新增设置项。
7. **迁移 / 重启纪律**：屏迁移后按 ID 既能收 current 也能收排队条目；
   同目录的新壳不会恢复旧壳的内存队列（队列不落盘）。

纪律：offscreen；真壳 + 真 PetSprite + 真 PetSpeechBubble；时间用注入时钟
（``shell._alert_clock``），事件用真事件循环轮询（不 sleep 赌时序）。
"""
from __future__ import annotations

import logging
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import click_sound  # noqa: E402
from pet.speech_bubble import PetSpeechBubble  # noqa: E402
from pet.sprite_bubble import sprite_anchor_rect_global  # noqa: E402
from tests.helpers.overlay_shell import _make_slot_shell  # noqa: E402

app = QApplication.instance() or QApplication([])

ALERT_TEXT = "Agent 需要你批准一条命令"
QUEUED_TEXT = "排队中的提醒"

#: 待处理队列基准（另有 1 条 current 展示位）：规范锁死的常数，实现必须一致。
QUEUE_LIMIT_BASELINE = 64


# ---------------------------------------------------------------- 脚手架
@pytest.fixture
def probes(monkeypatch):
    """记录全部 ``show_text``（含时长）与全部音效播放。

    音效统计**只算本用例自己提交的**：``SpriteSoundPlayer`` 把播放推迟到下一轮
    事件循环（``QTimer.singleShot(0)``，见 ``_submit``），而音效池是进程级的，
    上一条用例撞出来的那一声会落在本用例的事件循环里。先冲一次事件循环再清表，
    "迁移不得出声"这条断言测的才是本用例的动作。
    """
    shown: list[dict] = []
    sounds: list[object] = []
    original = PetSpeechBubble.show_text

    def recording_show_text(self, text, anchor, duration_ms=3200, **kwargs):
        shown.append({"bubble": self, "text": str(text), "duration_ms": int(duration_ms),
                      "sticky": bool(kwargs.get("sticky", False))})
        return original(self, text, anchor, duration_ms, **kwargs)

    monkeypatch.setattr(PetSpeechBubble, "show_text", recording_show_text)
    monkeypatch.setattr(click_sound.ClickSoundPool, "play_sound",
                        lambda self, path, volume=1.0: sounds.append(path) or True)
    app.processEvents()          # 冲掉上一条用例延后提交的播放
    sounds.clear()
    return shown, sounds


def _is_visible(bubble) -> bool:
    try:
        return bool(bubble is not None and bubble.isVisible())
    except RuntimeError:  # C++ 侧已销毁：不可见（且绝不因此炸掉用例）
        return False


def _all_bubbles(shell):
    """(owner_sprite, bubble)；主 sprite 记 ``shell.sprite``。"""
    pairs = []
    follower = getattr(shell, "_bubble_follower", None)
    if follower is not None and follower.bubble is not None:
        pairs.append((shell.sprite, follower.bubble))
    return pairs


def _copies(shell, text):
    """当前**可见**且正文等于 text 的气泡对象。"""
    return [bubble for _owner, bubble in _all_bubbles(shell)
            if _is_visible(bubble) and str(getattr(bubble, "_raw_text", "")) == text]


def _bubble_of(shell, sprite):
    follower = shell._bubble_for(sprite)
    return None if follower is None else follower.bubble


def _shown_count(shown, text) -> int:
    return sum(1 for item in shown if item["text"] == text)


def _drain(predicate=None, budget=2.0) -> bool:
    """跑真事件循环直到条件成立（宽预算；不用固定 sleep 猜时序）。"""
    deadline = time.monotonic() + budget
    while True:
        app.processEvents()
        if predicate is None or predicate():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)


def _cleanup(shell):
    try:
        shell.stop()
    finally:
        shell._delete_runtime_marker()


def _show_alert_on(shell, sprite, text, **kwargs):
    """让一条提醒落到**指定**的宠上（其余可见宠先藏起来，落定后再恢复）。"""
    others = [s for s in shell._all_sprites() if s is not sprite]
    for other in others:
        shell.set_sprite_visible(other, False)
    shell.show_alert(text, **kwargs)
    app.processEvents()
    for other in others:
        shell.set_sprite_visible(other, True)
    app.processEvents()


# ---------------------------------------------------------------- 1. 承载宠迁移






# ---------------------------------------------------------------- 4. 无宠 / 全隐藏




# ---------------------------------------------------------------- 5. 剩余 TTL


# ---------------------------------------------------------------- 6. 有界队列
def test_pending_queue_is_bounded_prefers_high_priority_and_is_diagnosable(tmp_path, probes, caplog):
    """待处理队列上限 64（另加 current）：同 ID 更新不增量，满时保高优先级，可诊断。"""
    from pet import window_alerts

    assert window_alerts.ALERT_QUEUE_LIMIT == QUEUE_LIMIT_BASELINE, "队列基准不得漂移"
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        # current = 优先级 0（审批级）；排队条目优先级 1 → 便于验证"满时保高优先级"
        shell.show_alert("当前提醒", alert_id="cur", sticky=True,
                         alert_type="approval", priority=0)
        for index in range(QUEUE_LIMIT_BASELINE):
            shell.show_alert(f"排队{index}", alert_id=f"q{index}", sticky=True,
                             alert_type="approval", priority=1)
        ids = [item["id"] for item in shell._alert_queue]
        assert ids == [f"q{i}" for i in range(QUEUE_LIMIT_BASELINE)]
        assert shell._alert_current["id"] == "cur"

        text_on_screen = shell._speech_bubble._raw_text
        overflow_before = getattr(shell, "_alert_overflow_count", 0)
        with caplog.at_level(logging.WARNING):
            shell.show_alert("更低优先级的新条", alert_id="low", sticky=True,
                             alert_type="watchdog", priority=2)
        assert [item["id"] for item in shell._alert_queue] == ids, \
            "队列已满时低优先级新条必须被拒收，不得挤掉别人"
        assert len(shell._alert_queue) == QUEUE_LIMIT_BASELINE
        assert shell._speech_bubble._raw_text == text_on_screen, "不得弹汇总/换掉当前气泡"
        assert "队列已满" in caplog.text, "拒收必须留下可诊断的 warning"
        assert getattr(shell, "_alert_overflow_count", 0) == overflow_before + 1

        # 同 ID 更新不增量（就地替换排队条目）
        shell.show_alert("排队5更新", alert_id="q5", sticky=True,
                         alert_type="approval", priority=1)
        assert len(shell._alert_queue) == QUEUE_LIMIT_BASELINE, "同 ID 更新不得增长队列"
        assert [item["text"] for item in shell._alert_queue if item["id"] == "q5"] == ["排队5更新"]

        # 更高优先级的新条进得来：淘汰最低优先级里最旧的一条
        shell.show_alert("更高的优先级", alert_id="crit", sticky=True,
                         alert_type="approval", priority=0)
        ids = [item["id"] for item in shell._alert_queue]
        assert len(ids) == QUEUE_LIMIT_BASELINE
        assert "crit" in ids
        assert "q0" not in ids, "满队列必须淘汰最低优先级里最旧的一条"
        assert "q1" in ids
    finally:
        _cleanup(shell)


# ---------------------------------------------------------------- 7. 迁移 / 重启
def test_full_queue_preemption_stays_bounded_and_keeps_screen_busy(tmp_path, probes, caplog):
    """满队列上高优先级抢占：队列不得超上限，抢占后屏幕不得空着（current 不留空）。"""
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert("被抢占的低优先级", alert_id="cur", sticky=True,
                         alert_type="watchdog", priority=3)
        for index in range(QUEUE_LIMIT_BASELINE):
            shell.show_alert(f"排队{index}", alert_id=f"q{index}", sticky=True,
                             alert_type="watchdog", priority=3)
        assert len(shell._alert_queue) == QUEUE_LIMIT_BASELINE

        with caplog.at_level(logging.WARNING):
            shell.show_alert("更急的审批", alert_id="crit", sticky=True,
                             alert_type="approval", priority=0)
        app.processEvents()

        assert len(shell._alert_queue) <= QUEUE_LIMIT_BASELINE, "抢占不得让队列超上限"
        assert shell._alert_current is not None, "抢占后屏幕不得空着（否则队列静默卡死）"
        assert shell._alert_current["id"] == "crit"
        assert shell._speech_bubble._raw_text == "更急的审批"
        assert "队列已满" in caplog.text, "越界淘汰必须留可诊断 warning"
    finally:
        _cleanup(shell)




def test_new_shell_in_same_config_dir_does_not_restore_old_queue(tmp_path, probes):
    """同目录新壳：只按各源当前有效状态重建，不恢复旧壳的内存提醒队列。"""
    shell, cfg = _make_slot_shell(tmp_path)
    second = None
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT, alert_id="old-cur")
        shell.show_alert(QUEUED_TEXT, alert_id="old-q")
        app.processEvents()
        assert shell._alert_current["id"] == "old-cur"
        assert [item["id"] for item in shell._alert_queue] == ["old-q"]
        _cleanup(shell)

        second, _cfg2 = _make_slot_shell(tmp_path)
        second.overlay.show()
        app.processEvents()
        assert second._alert_current is None, "重启后不得恢复旧队列的 current"
        assert list(second._alert_queue) == [], "重启后不得恢复旧队列的排队条目"
        assert not [p.name for p in cfg.dir.iterdir() if "alert" in p.name.lower()], \
            "提醒队列是内存态，不得落盘成第二真值"
    finally:
        if second is not None:
            _cleanup(second)


# ---------------------------------------------------------------- 3. hidden 链路守卫


def test_queued_alert_resumes_when_window_shows_again(tmp_path, probes):
    """整窗隐藏期排队等着的提醒：显示恢复时必须继续推进（不靠下一次新提醒捞它）。"""
    shell, _cfg = _make_slot_shell(tmp_path)
    try:
        shell.overlay.show()
        shell.show_alert(ALERT_TEXT, alert_id="q1")
        shell.show_alert(QUEUED_TEXT, alert_id="q2")
        app.processEvents()
        assert shell._alert_current["id"] == "q1"
        assert [item["id"] for item in shell._alert_queue] == ["q2"]

        shell.set_pet_visible(False)          # 整窗隐藏
        shell.resolve_alert("q1")             # 隐藏期把 current 收掉（DSH 侧解决了）
        app.processEvents()
        assert shell._alert_current is None
        assert [item["id"] for item in shell._alert_queue] == ["q2"], "隐藏期不得吞队列"

        shell.set_pet_visible(True)           # 显示恢复 → 队首必须接上
        _drain(lambda: (shell._alert_current or {}).get("id") == "q2")
        assert shell._alert_current is not None and shell._alert_current["id"] == "q2"
        assert not shell._alert_queue
        assert len(_copies(shell, QUEUED_TEXT)) == 1
    finally:
        _cleanup(shell)




# ---------------------------------------------------------------- 有界重试（4 次上限）
