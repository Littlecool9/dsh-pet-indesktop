# -*- coding: utf-8 -*-
"""低优先级预热 pause / 代次作废回归测试。

保留覆盖：
1. pause_warm（隐藏/切角色）代次作废旧批次：旧角色/旧库的预热不会复活；
2. 低优先级批次去重：同一时间最多一个在飞批次，timer/50ms 重试/resume 重排
   的并发触发不会重复起批、不会重复启动 ffmpeg；
3. 认领时捕获代次（N2）、线程启动失败回滚在飞标志（N3）；
4. 高优先级预热在暂停时 sleep 前整批放弃 / 中途作废排队 clip。

交互让路（begin/end_interaction）已随 PetWindow 删除，对应窗口钩子测试
一并移除；sprite 侧的等价行为覆盖见 tests/test_sprite_behavior.py。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import pet.library as library_mod
from pet import catalog


class FakeClip:
    """极简假 WebMClip：记录预热调用（含次数），不碰 ffmpeg/Qt。"""

    def __init__(self, path, parent=None):
        self.path = Path(path)
        self.warmed_meta = False
        self.warmed_frame = False
        self.meta_calls = 0
        self.frame_calls = 0

    def warm_meta(self):
        self.meta_calls += 1
        self.warmed_meta = True

    def warm_first_frame(self):
        self.frame_calls += 1
        self.warmed_frame = True


class BlockableClip(FakeClip):
    """warm_meta 可阻塞/可放行的假 clip，用于观测让路与放弃时机。"""

    def __init__(self, path, parent=None):
        super().__init__(path, parent)
        self.meta_entered = threading.Event()
        self.meta_release = threading.Event()

    def warm_meta(self):
        self.meta_calls += 1
        self.warmed_meta = True
        self.meta_entered.set()
        # CI 慢 runner 上，从 meta_entered 到测试完成编舞步骤（begin_interaction、
        # 打闸门补丁、放行）可能超过 5s；放行前超时会让 worker 先行通过闸门，
        # 破坏「让路/放弃」断言。放宽到 30s：正常路径由测试显式放行，超时只是
        # 防挂死兜底。
        self.meta_release.wait(30.0)


class _GateObjectsLib(library_mod.MovieLibrary):
    """在 _warm_objects 入口加屏障，复现"线程启动后、进入预热前"的窗口，
    用于验证快速 pause/resume 不会让旧批次把新代次误认成自己的批次。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.objects_entered = threading.Event()
        self.objects_release = threading.Event()

    def _warm_objects(self, clips, workers, *, generation=None, cancelled=None,
                      include_frames=True):
        self.objects_entered.set()
        self.objects_release.wait(5.0)
        return super()._warm_objects(
            clips, workers,
            generation=generation,
            cancelled=cancelled,
            include_frames=include_frames,
        )


def _make_lib(tmp_path, monkeypatch, clip_cls=FakeClip, lib_cls=None):
    lib_cls = lib_cls or library_mod.MovieLibrary
    monkeypatch.setattr(library_mod, "WebMClip", clip_cls)
    videos = tmp_path / "videos"
    folders = {
        # 批10-A3：idle/move 移入低优先级池后，本文件的编舞（BlockableClip 逐段
        # 阻塞放行「写代码/吃白饭」）会被前置的 idle/move 假 clip 打乱——这里
        # 锁定的是让路/代次闸门机制，与池构成无关，故夹具只保留交互核 + 随机池。
        # 池构成的拆分断言由 test_library_priority_warm.py 专项覆盖。
        "turn": ["东张西望.webm"],
        "click": ["点击回应 - 开心跃动.webm"],
        "drag": ["被鼠标拖拽悬空反馈.webm"],
        "random": ["写代码.webm", "吃白饭.webm"],
    }
    for folder, files in folders.items():
        directory = videos / folder
        directory.mkdir(parents=True)
        for name in files:
            (directory / name).write_bytes(b"fake")
    # 本文件锁定的是让路/代次机制（含首帧阶段），用 full 档保持旧预热语义；
    # 档位对首帧的门控由 test_library_priority_warm.py 专项覆盖。
    return lib_cls(asset_dir=videos, prewarm_policy="full")


def _wait_until(predicate, timeout=30.0):
    # CI 预算：本文件是已知的高负载 flake（批10-A3 缩池后让路场景结构性变化），
    # 预热 worker 由守护线程承载，在 CI 满载/慢 runner 上从「批次认领」到
    # 「首个 clip 进入 warm_meta / 批次收尾」可能超过 10s（实测本地重载机也会
    # 偶发超 10s）。断言业务强度不变（仍是「最终必须满足 predicate」），只放宽
    # 等待上界。
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"等待超时: {predicate!r}")


def _wait_never(predicate, timeout=0.4, app=None):
    """有界负向等待：窗口内若 predicate 成立立即失败（用于"不应发生"断言）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            raise AssertionError(f"不应满足: {predicate!r}")
        time.sleep(0.01)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 库侧闸门
def test_low_warm_batch_dedup_in_flight(tmp_path, monkeypatch):
    """P1：批次去重——timer 到点/重试/resume 重排的并发触发不得重复起批。"""
    lib = _make_lib(tmp_path, monkeypatch, BlockableClip)
    # CI 顺序无关：按真实池顺序取前两个（目录枚举顺序跨平台/跨文件系统不同）
    _, low = lib._priority_names()
    first, second = low[0], low[1]
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._movies[first].meta_entered.is_set())
    assert lib._low_warm_in_flight is True

    lib._warm_low_priority_background()  # 模拟 timer 重入：不得再起一批
    assert lib._low_warm_in_flight is True, "已有批次在飞时必须去重"

    lib._movies[first].meta_release.set()
    lib._movies[second].meta_release.set()
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._low_warm_in_flight is False
    # 同一批 clip 只被预热一次：没有重复批次重复启动 ffmpeg
    assert lib._movies[first].meta_calls == 1
    assert lib._movies[second].meta_calls == 1
    assert lib._movies[first].frame_calls == 1
    assert lib._movies[second].frame_calls == 1


def test_completed_flag_stable_after_completion(tmp_path, monkeypatch):
    """P2：完成标志在批次收尾后保持稳定——遗留 timer/重复排期不再起批覆盖。"""
    lib = _make_lib(tmp_path, monkeypatch)
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._low_warm_in_flight is False

    lib._warm_low_priority_background()  # 遗留 timer 触发：已完整跑完 → 跳过
    assert lib._low_warm_in_flight is False
    assert lib._low_first_frames_done is True
    assert lib._movies["写代码"].meta_calls == 1
    assert lib._movies["吃白饭"].meta_calls == 1


def test_pause_warm_aborts_stale_batch_no_revival(tmp_path, monkeypatch):
    lib = _make_lib(tmp_path, monkeypatch, BlockableClip)
    # CI 顺序无关：低优池顺序来自目录枚举（平台相关），按真实池顺序取前两个
    _, low = lib._priority_names()
    first, second = low[0], low[1]
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._movies[first].meta_entered.is_set())

    lib.pause_warm()  # 隐藏/切角色：代次作废旧批次
    lib._movies[first].meta_release.set()

    _wait_until(lambda: not lib._low_warm_in_flight)  # 旧 worker 真正收尾（不猜时序）
    assert lib._movies[second].warmed_meta is False, "旧代次批次必须放弃，不得复活"
    assert lib._low_first_frames_done is False

    # 恢复显示后重新排期：新代次批次完整跑完
    lib.resume_warm()
    lib._movies[second].meta_release.set()  # 新批次遇到阻塞 clip 时直接放行
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._movies[second].warmed_meta is True
    assert lib._movies[second].warmed_frame is True


def test_fast_pause_resume_aborts_batch_via_captured_generation(tmp_path, monkeypatch):
    """P2：代次只在批次启动时捕获一次——线程启动后、进入预热前的快速
    pause/resume 必须作废旧批次，不能把新代次误认成自己的批次继续预热。"""
    lib = _make_lib(tmp_path, monkeypatch, FakeClip, lib_cls=_GateObjectsLib)
    lib._warm_low_priority_background()
    _wait_until(lib.objects_entered.is_set)  # worker 已进入 _warm_objects 前屏障

    lib.pause_warm()
    lib.resume_warm()
    lib.objects_release.set()  # 放行：旧批次拿的是 pause 前的代次，应整体放弃

    _wait_until(lambda: not lib._low_warm_in_flight)
    assert lib._movies["写代码"].warmed_meta is False, "旧代次批次不得在新代次下继续预热"
    assert lib._movies["吃白饭"].warmed_meta is False
    assert lib._low_first_frames_done is False

    # 恢复后的新代次批次可完整跑完
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._movies["写代码"].warmed_meta is True
    assert lib._movies["写代码"].warmed_frame is True


def test_fast_pause_resume_after_claim_before_worker_start_aborts(tmp_path, monkeypatch):
    """N2 回归：代次必须在 GUI 线程认领批次那一刻捕获并随批次传入 worker——
    认领后、worker 真正开始预热前的快速 pause/resume 不得让旧批次把新代次
    误认成自己的代次而复活。用 worker run() 屏障同步（只拦 worker、不拦
    主线程），不用 sleep 猜时序。"""
    lib = _make_lib(tmp_path, monkeypatch)

    worker_entered = threading.Event()
    worker_release = threading.Event()
    real_run = threading.Thread.run

    def gated_run(self, *args, **kwargs):
        worker_entered.set()
        worker_release.wait(5.0)
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "run", gated_run)
    lib._warm_low_priority_background()  # GUI 线程：认领批次（此刻捕获代次）并启动 worker
    assert worker_entered.wait(5.0), "worker 必须在执行预热前被屏障拦截（认领已完成）"

    lib.pause_warm()  # 隐藏：换代
    lib.resume_warm()  # 恢复显示：新代次
    worker_release.set()  # 放行 worker：它必须用认领时捕获的旧代次 → 整体放弃

    _wait_until(lambda: not lib._low_warm_in_flight)
    assert lib._movies["写代码"].warmed_meta is False, "认领后换代的旧批次不得复活"
    assert lib._movies["吃白饭"].warmed_meta is False
    assert lib._low_first_frames_done is False

    # 恢复后的新代次批次可完整跑完（屏障已放行，不再拦截）
    lib._warm_low_priority_background()
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._movies["写代码"].warmed_meta is True
    assert lib._movies["写代码"].warmed_frame is True


def test_thread_start_failure_clears_in_flight_flag(tmp_path, monkeypatch):
    """N3 回归：认领批次后 threading.Thread.start() 抛异常（如资源耗尽）必须
    回滚 _low_warm_in_flight，否则后续排期被永久去重、低优先级预热彻底停摆。"""
    lib = _make_lib(tmp_path, monkeypatch)

    real_start = threading.Thread.start
    calls = {"n": 0}

    def failing_start(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("can't start new thread")
        return real_start(self, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", failing_start)
    lib._warm_low_priority_background()  # 首次启动失败
    assert lib._low_warm_in_flight is False, "线程启动失败必须回滚认领标志"

    lib._warm_low_priority_background()  # 第二次排期可正常启动并跑完
    _wait_until(lambda: lib._low_first_frames_done)
    assert lib._movies["写代码"].warmed_meta is True
    assert lib._movies["吃白饭"].warmed_meta is True


def test_high_priority_warm_skipped_while_paused(tmp_path, monkeypatch):
    """P2：高优先级预热在暂停（隐藏/切角色）时整批放弃——sleep 前门控。"""
    lib = _make_lib(tmp_path, monkeypatch)
    lib.pause_warm()

    lib._warm_all_meta_background()
    assert lib._movies[catalog.CLICKS[0]].warmed_meta is False
    assert lib._movies[catalog.CLICKS[0]].warmed_frame is False
    assert lib._movies[catalog.TURN].warmed_meta is False
    assert lib._movies[catalog.DRAG].warmed_meta is False


def test_high_priority_warm_aborts_when_paused_during_sleep(tmp_path, monkeypatch):
    """P2：高优先级预热的随机错峰 sleep 期间被 pause_warm（隐藏/切角色）——
    sleep 后必须检查 _warm_paused/代次并作废本批，不得拉起 ffmpeg 继续预热。

    用 fake sleep 在 sleep 窗口内同步触发 pause_warm（不猜时序），验证门控。
    """
    lib = _make_lib(tmp_path, monkeypatch)
    real_sleep = library_mod.time.sleep
    sleep_calls = {"n": 0}

    def pausing_sleep(seconds):
        sleep_calls["n"] += 1
        lib.pause_warm()  # 模拟 sleep 期间隐藏/切角色：换代

    monkeypatch.setattr(library_mod.time, "sleep", pausing_sleep)
    lib._warm_all_meta_background()
    assert sleep_calls["n"] == 1, "高优先级预热必须经历随机错峰 sleep"
    assert lib._movies[catalog.CLICKS[0]].warmed_meta is False, "sleep 期间暂停，本批必须作废"
    assert lib._movies[catalog.CLICKS[0]].warmed_frame is False
    assert lib._movies[catalog.TURN].warmed_meta is False
    assert lib._movies[catalog.DRAG].warmed_meta is False

    # 恢复后新代次批次可正常预热（门控不放错、不误伤）
    monkeypatch.setattr(library_mod.time, "sleep", real_sleep)
    lib.resume_warm()
    lib._warm_all_meta_background()
    assert lib._movies[catalog.CLICKS[0]].warmed_meta is True
    assert lib._movies[catalog.CLICKS[0]].warmed_frame is True
    assert lib._movies[catalog.TURN].warmed_meta is True


def test_high_priority_warm_aborts_mid_batch_when_paused(tmp_path, monkeypatch):
    """P2：高优先级预热中途（metadata 解码期间）被 pause_warm——尚未开始的
    clip 不得再拉起 ffmpeg（非阻塞中途作废），首帧阶段整段跳过。"""
    lib = _make_lib(tmp_path, monkeypatch, clip_cls=BlockableClip)
    # 批10-A3 后高优池 = clicks+turns+drag 共 3 素材 → workers=min(3,3)=3，
    # 「排队中的 clip」场景结构性消失，使下方 skipped 断言沦为空洞通过。
    # 本测要验证「pause 作废排队中的 clip」，故给高优池补 2 个假 clip：
    # 高优至 5、workers 仍为 3，留下 2 个真实排队项。
    queued_names = ["排队夹甲", "排队夹乙"]
    for name in queued_names:
        lib._movies[name] = BlockableClip(tmp_path / "videos" / f"{name}.webm")
    real_priority_names = lib._priority_names

    def five_high_priority_names():
        high, low = real_priority_names()
        return high + queued_names, low

    monkeypatch.setattr(lib, "_priority_names", five_high_priority_names)

    results: dict = {}
    t = threading.Thread(
        target=lambda: (lib._warm_all_meta_background(), results.setdefault("done", True)),
        name="test-high-warm",
    )
    t.start()
    # 第一批（并发 3）已进入 warm_meta 阻塞：事件同步，不猜时序
    _wait_until(lambda: lib._movies[catalog.CLICKS[0]].meta_entered.is_set())
    lib.pause_warm()  # 隐藏/切角色：排队中的 clip 必须作废
    # 放行所有已进入 warm_meta 的 clip：循环重查 entered 直到线程退出，
    # 避免「快照后才进入」的 clip 阻塞在无人放行的 meta_release.wait(5.0)。
    while t.is_alive():
        for clip in list(lib._movies.values()):
            if clip.meta_entered.is_set():
                clip.meta_release.set()
        t.join(timeout=0.05)
    assert not t.is_alive()
    assert results.get("done") is True
    # 首帧阶段整段跳过（暂停中，不得再拉起 ffmpeg）
    assert all(c.frame_calls == 0 for c in lib._movies.values())
    # 已进入 meta 的 clip 完成探测；暂停后排队未开始的 clip 被中途作废
    entered = [c for c in lib._movies.values() if c.meta_entered.is_set()]
    skipped = [c for c in lib._movies.values() if not c.meta_entered.is_set()]
    assert entered, "第一批高优先级 clip 必须已进入 warm_meta"
    assert all(c.meta_calls == 1 for c in entered)
    assert all(c.meta_calls == 0 for c in skipped), "暂停后排队中的 clip 不得再拉起 ffmpeg"
    assert len(skipped) >= 2, "高优池必须留有真实排队项（否则 skipped 断言空洞）"

    # 恢复后新代次批次可完整跑完（门控不误伤）
    lib.resume_warm()
    lib._warm_all_meta_background()
    assert lib._movies[catalog.CLICKS[0]].warmed_frame is True
    assert lib._movies[catalog.DRAG].warmed_frame is True


