# -*- coding: utf-8 -*-
"""播放速率写入的帧交付节奏回归（菜单「播放速率」/ 设置页速率）。

根因：两个 clip 实现用 QTimer 的 ``setInterval`` / ``start(ms)`` 落地新间隔——
**对运行中的 QTimer 重设间隔会重开倒计时**（I1 真 QTimer 探针：每 64ms 写一次
同值 → 2s 只交付 31 帧，不写则 47 帧）。频繁改速率（滑杆/脚本/菜单）时若每次都
重开倒计时，帧交付会被一路推迟。

两条口径：
1. 同值写入不得重开倒计时；真变速（间隔真变）也只在下次 timeout 落地（当拍
   倒计时不被截断，新间隔照样生效）；
2. 未运行时写入照旧立即生效（``_switch`` 起播前设速率的老语义）。

纪律：真 QTimer + 真事件循环；断言用量级差而非精确时序，等待一律走事件循环的
singleShot 退出（不 sleep 赌时序）。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from pet import frameseq_provision
from pet.frameseq_clip import FrameSeqClip
from pet.webm_clip import WebMClip

app = QApplication.instance() or QApplication([])

REAL_WEBM = Path("assets/characters/shenshen/videos/idle/待机呼吸休闲.webm")


def _pump(ms: int) -> None:
    """真事件循环跑 ms 毫秒（真 QTimer 照常触发），不用 sleep 赌时序。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _make_frames(dir_path: Path, count: int = 120, size: tuple[int, int] = (32, 24)) -> None:
    """Qt 现场生成 count 帧 webp + meta.json（fps=24）。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    w, h = size
    for i in range(count):
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        for y in range(4):
            for x in range(4):
                img.setPixel(x, y, (0xFF << 24) | ((i % 200) << 16) | 0x3366)
        assert img.save(str(dir_path / f"f_{i + 1:04d}.webp"), "webp", 100)
    (dir_path / "meta.json").write_text(
        json.dumps({"fps": 24.0, "source": "x.webm", "frames": count,
                    "encoder": frameseq_provision.ENCODER_DESC}),
        encoding="utf-8")


# ---------------------------------------------------------------- 2 定时器口径
def test_webm_set_playback_speed_same_interval_keeps_countdown():
    """同值写入（间隔不变）不得重设 QTimer：倒计时读数不回到整间隔。"""
    clip = WebMClip(REAL_WEBM)
    try:
        clip.set_playback_speed(0.25)          # 慢速 → 大间隔，读数分辨力足够
        interval = clip._timer_interval()
        assert interval >= 100
        clip._timer.start()                    # 直接跑帧表（不起 reader）
        _pump(60)
        before = clip._timer.remainingTime()
        assert 0 < before <= interval
        clip.set_playback_speed(0.25)          # 同值重写：间隔未变
        after = clip._timer.remainingTime()
        clip._timer.stop()
        assert after <= before + 20, (
            f"同值重写重开了倒计时：{before}ms → {after}ms（整间隔 {interval}ms）")
    finally:
        clip.stop()


def test_webm_set_playback_speed_change_defers_and_then_applies():
    """真变速：间隔真变时不得截断当拍倒计时，但下次 timeout 必须落地新间隔。"""
    clip = WebMClip(REAL_WEBM)
    try:
        clip.set_playback_speed(0.25)
        slow = clip._timer_interval()
        clip._timer.start()
        _pump(60)
        before = clip._timer.remainingTime()
        clip.set_playback_speed(1.0)           # 真变速：间隔变小
        fast = clip._timer_interval()
        assert fast < slow
        mid = clip._timer.remainingTime()
        assert mid <= before + 20, f"变速截断了倒计时：{before}ms → {mid}ms"
        _pump(slow + 60)                       # 跨过至少一次 timeout
        assert clip._timer.interval() == fast, "新间隔未在下一次 timeout 落地"
    finally:
        clip.stop()


def test_webm_set_playback_speed_before_start_applies_immediately():
    """未运行的帧表：写入照旧立即落地（_switch 起播前设速率的老语义）。"""
    clip = WebMClip(REAL_WEBM)
    try:
        clip.set_playback_speed(2.0)
        assert clip._timer.interval() == clip._timer_interval()
        clip.set_playback_speed(0.5)
        assert clip._timer.interval() == clip._timer_interval()
    finally:
        clip.stop()


def test_frameseq_set_playback_speed_same_interval_keeps_countdown(tmp_path):
    """FrameSeqClip 同款：同值写入不得重开帧表倒计时，真变速同样只顺延落地。"""
    d = tmp_path / "clip"
    _make_frames(d, count=8)
    clip = FrameSeqClip(d)
    try:
        clip.set_playback_speed(0.25)
        slow = clip._interval_ms()
        assert slow >= 100
        assert clip.start() is True            # 起播：帧表按 slow 运行
        _pump(60)
        before = clip._timer.remainingTime()
        assert 0 < before <= slow

        clip.set_playback_speed(0.25)          # 同值重写：间隔未变
        same = clip._timer.remainingTime()
        assert same <= before + 20, (
            f"同值重写重开了倒计时：{before}ms → {same}ms（整间隔 {slow}ms）")

        clip.set_playback_speed(1.0)           # 真变速：间隔真变，仍不得截断当拍
        fast = clip._interval_ms()
        assert fast < slow
        mid = clip._timer.remainingTime()
        assert mid <= before + 20, f"变速截断了倒计时：{before}ms → {mid}ms"
        _pump(slow + 60)
        assert clip._timer.interval() == fast, "新间隔未在下一次 timeout 落地"
    finally:
        clip.close()
