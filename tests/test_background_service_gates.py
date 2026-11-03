# -*- coding: utf-8 -*-
"""O5 后台常驻门控：DSH 桥接读方 / 进程级共享全屏 watcher。

默认配置下这两项都该真正停下来（现状是**无条件**常驻）：

1. DSH 桥目录的唯一读方 ``DshMonitor``（1.5s 一轮的桥目录轮询 + 3s 一节拍的
   端口探活 + dsh_state 收敛器，全部在它自己的 worker 线程里）的全部输出只喂
   DSH 联动管线——DSH 联动没开时它读的桥接插件根本没装，纯空转。
   门 = ``agent_link.dsh``（``AgentLinkManager.apply_config`` 按它启停监视器）。
2. overlay 拓扑下进程级共享全屏 watcher 的扇出目标是 sprite 世界的壳，而该壳
   **刻意不暴露** ``_watch_required`` / ``_cursor_hidden_passthrough_enabled``
   / ``auto_hide_fullscreen``（overlay 自持 ``FullscreenCursorWatcher``）——
   ``_any_wants()`` 恒 False → 常驻线程每秒空醒。overlay 拓扑不启该线程。

装配口径：真 AppShell + 真 Config + 真共享子系统/跟踪器，真 ``AppShell.start()``；
只有"起桌宠"那一层（建窗口/合成窗、托盘、会话结束探测器、灵动岛、可选服务）
置空——与 ``tests/test_desktop_pet_features.py`` 的 ``owner.start()`` 同款边界。
"""
from __future__ import annotations

import os
import pathlib
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.app as app_mod
import pet.overlay_shell as overlay_shell_mod
from pet import harness_launcher
from pet.app import AppShell
from pet.config import APP_DIR_NAME, Config

app = QApplication.instance() or QApplication([])


class _StubWin:
    """legacy 窗替身：只提供共享全屏 watcher 自省需要的读取面。"""

    def __init__(self, *, watch: bool = True):
        self._watch = watch
        self.auto_hide_fullscreen = False

    def _watch_required(self):
        return self._watch

    def _cursor_hidden_passthrough_enabled(self):
        return False

    def isVisible(self):
        return True


class _StubOverlayShell:
    """overlay 壳替身：真实壳不暴露 ``_watch_required`` 一族（sprite 世界自持）。"""

    def __init__(self, qapp, instance, **kwargs):
        self.qapp = qapp
        self.instance = instance
        self.kwargs = kwargs
        self.started = 0

    def start(self):
        self.started += 1


def _start_shell(tmp_path, monkeypatch, *, dsh=False,
                 win=None, ui_stub=True, prepare=None):
    """真 AppShell.start()（"起桌宠"那一层置空）。

    ``prepare(config)`` 在落盘前改配置。
    """
    config = Config(base=tmp_path)
    if dsh:
        agent_cfg = dict(config.get("agent_link") or {})
        agent_cfg["dsh"] = True
        config.set("agent_link", agent_cfg)
    if prepare is not None:
        prepare(config)
    assert config.save()  # 落盘：外部变更监视的前提
    shell = AppShell(app, config)
    if ui_stub:
        shell.instance._apply_spawn_offset = lambda: None
        shell.instance._refresh_chat_windows = lambda: None
        shell._apply_balance_timer = lambda: None
        shell._sync_dynamic_island = lambda: None
        shell._install_session_watcher = lambda: None
        shell._sync_todo_service = lambda: None
        shell._sync_festival_service = lambda: None
    if win is not None:
        shell.instance.win = win
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda *a, **k: None)
    shell.start()
    return shell


def _pump(seconds: float) -> None:
    """有界泵事件循环（不赌时序：只用来让已排队的信号/定时器跑完）。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _save_external(config) -> None:
    """外部保存（有界重试）。

    Windows 上 ``os.replace`` 偶发被瞬时占用拒绝（``Config.save`` 内部只 warning
    一次级失败；同族测试 ``test_config_watcher_reloads_and_applies_external_change``
    同样见过），失败时文件未替换 → 重试是同一件事的第二次尝试，不是时间赌注。
    """
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if config.save():
            return
        time.sleep(0.05)
    raise AssertionError("外部保存重试 10s 仍失败（Config.save 返回 False）")


# ---------------------------------------------------------------- DSH 桥接读方门
def _dsh_monitor(shell):
    return shell._shared.agent_link.monitors["dsh"]


def test_default_config_keeps_dsh_monitor_stopped(tmp_path, monkeypatch):
    """默认配置（agent_link 四 agent 全关）：读方不启，零端口探测。"""
    connects: list[int] = []
    monkeypatch.setattr(harness_launcher, "is_running",
                        lambda port: connects.append(port) or False)
    shell = _start_shell(tmp_path, monkeypatch)
    monitor = _dsh_monitor(shell)
    assert monitor._running is False, "默认配置下 DSH 读方不得启动"
    assert connects == [], "读方未启动就不得发起 loopback 端口探测"
    _pump(0.2)
    assert connects == [], "监视器未启动，后续也不得自启探测"


def test_dsh_link_enabled_starts_monitor(tmp_path, monkeypatch):
    """DSH 联动开启：读方照常跑（功能不变），worker 线程存活。"""
    monkeypatch.setattr(harness_launcher, "is_running", lambda port: False)
    shell = _start_shell(tmp_path, monkeypatch, dsh=True)
    monitor = _dsh_monitor(shell)
    assert monitor._running is True
    assert monitor._worker is not None and monitor._worker.is_alive()


def test_malformed_agent_link_config_keeps_monitor_stopped(tmp_path, monkeypatch):
    """脏配置（agent_link 不是 dict）：门判假、不抛，读方保持不跑。"""
    shell = _start_shell(tmp_path, monkeypatch)
    shell.config.data["agent_link"] = "broken"
    assert shell._dsh_tracker_wanted() is False
    shell._shared.agent_link.apply_config()
    assert _dsh_monitor(shell)._running is False


def test_gated_monitor_still_drives_offline_dismiss(tmp_path, monkeypatch):
    """门开时行为与现在一致：收敛器 offline 仍收口常驻审批/问题气泡。"""
    monkeypatch.setattr(harness_launcher, "is_running", lambda port: False)
    shell = _start_shell(tmp_path, monkeypatch, dsh=True)
    manager = shell._shared.agent_link
    dismissed: list[bool] = []
    monkeypatch.setattr(manager, "dismiss_all_interactions",
                        lambda: dismissed.append(True))
    mon = _dsh_monitor(shell)
    mon.dsh_state_changed.emit("thinking", "offline", "", mon._emit_gen)
    app.processEvents()
    assert dismissed, "DSH 离线必须照常收口常驻气泡"


def test_disabling_dsh_link_stops_monitor_on_apply_config(tmp_path, monkeypatch):
    """关掉 DSH 联动 → apply_config（设置保存链的终点）同步停读方。"""
    monkeypatch.setattr(harness_launcher, "is_running", lambda port: False)
    shell = _start_shell(tmp_path, monkeypatch, dsh=True)
    monitor = _dsh_monitor(shell)
    assert monitor._running is True

    agent_cfg = dict(shell.config.get("agent_link") or {})
    agent_cfg["dsh"] = False
    shell.config.set("agent_link", agent_cfg)
    shell._shared.agent_link.apply_config()

    assert monitor._running is False, "关掉 DSH 联动后读方必须停"
    assert monitor._worker is None or not monitor._worker.is_alive()


def test_enabling_dsh_link_starts_monitor_on_apply_config(tmp_path, monkeypatch):
    """反向：运行期打开 DSH 联动 → apply_config 立即拉起读方。"""
    monkeypatch.setattr(harness_launcher, "is_running", lambda port: False)
    shell = _start_shell(tmp_path, monkeypatch)
    monitor = _dsh_monitor(shell)
    assert monitor._running is False

    agent_cfg = dict(shell.config.get("agent_link") or {})
    agent_cfg["dsh"] = True
    shell.config.set("agent_link", agent_cfg)
    shell._shared.agent_link.apply_config()

    assert monitor._running is True
    assert monitor._worker is not None and monitor._worker.is_alive()


# ---------------------------------------------------------------- 共享全屏 watcher
def test_overlay_topology_skips_shared_fullscreen_watcher(tmp_path, monkeypatch):
    """overlay 拓扑：进程级共享全屏 watcher 不启线程（壳自持探测）。"""
    monkeypatch.setattr(overlay_shell_mod, "OverlayShell", _StubOverlayShell)
    shell = _start_shell(tmp_path, monkeypatch)
    assert shell._overlay_shell is not None, "用例前置：overlay 壳已接管"
    fs = shell._shared.fs
    assert fs._thread is None, "overlay 拓扑下共享全屏 watcher 不得起线程"


def test_overlay_topology_would_restore_spawned_pets(tmp_path, monkeypatch):
    """对照组：同一份活跃宠清单在 overlay 拓扑下确实由壳接管（对照非空转）。"""
    from pet import overlay_spawn_state

    active_dir = tmp_path / APP_DIR_NAME
    active_dir.mkdir(parents=True, exist_ok=True)
    assert overlay_spawn_state.save_active_slots(active_dir, [1, 2])

    monkeypatch.setattr(overlay_shell_mod, "OverlayShell", _StubOverlayShell)
    shell = _start_shell(tmp_path, monkeypatch)
    assert shell._overlay_shell is not None
    assert shell._overlay_shell.started == 1
    assert len(shell._instances) == 1  # 子肥鱼由壳负责（sprite），不走 AppShell._instances


def test_one_settings_save_applies_external_change_exactly_once(tmp_path, monkeypatch):
    """一次外部设置保存 → 恰好一次 _apply_external_config_change。"""
    shell = _start_shell(tmp_path, monkeypatch, win=_StubWin())
    applies: list[int] = []
    shell._apply_external_config_change = lambda: applies.append(1)
    external = Config(base=tmp_path)
    external.set("pnpm_bin", "C:/tools/pnpm.cmd")
    _save_external(external)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not applies:
        app.processEvents()
        time.sleep(0.02)
    _pump(0.8)  # 去抖窗口（300ms）之后的余量：不得出现第二次
    assert len(applies) == 1, f"一次保存触发了 {len(applies)} 次应用链"
    assert shell.config.get("pnpm_bin") == "C:/tools/pnpm.cmd"


def test_late_duplicate_notification_does_not_reapply_same_content(tmp_path, monkeypatch):
    """首轮应用后迟到的**同内容** fileChanged 重发 → 不得第二次应用。

    CI 实测（mac 轮，一轮 6735 项的套件里）：一次保存触发 2 次
    ``_apply_external_config_change``。成因是文件侧的 arm 点没有签名门——
    目录侧（``_on_config_dir_changed``）按 (mtime_ns, size) 签名判变，文件侧
    只 ``_arm_config_reload()``；mac 上同一次 ``os.replace`` 的重复通知会迟到
    于 300ms 去抖窗口之后，于是重启窗口、再应用一次（盘上内容并未再变）。

    这里不赌 OS 事件时序：首轮应用完成后，直接用真实 watcher 的
    ``fileChanged`` 把同一条通知重发一次——这就是"迟到重发"的确定性形态。
    同一条用例钉住三件事：重发不二次应用、新内容照常应用、原子 replace 后
    监听恢复（换 inode 后路径仍在监视表内）。
    """
    shell = _start_shell(tmp_path, monkeypatch, win=_StubWin())
    applies: list[int] = []
    shell._apply_external_config_change = lambda: applies.append(1)
    watcher = shell._config_watcher
    external = Config(base=tmp_path)
    external.set("pnpm_bin", "C:/tools/pnpm.cmd")
    _save_external(external)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not applies:
        app.processEvents()
        time.sleep(0.02)
    _pump(0.8)
    assert applies == [1], f"首轮应用链必须是恰好一次，实为 {applies}"
    assert str(shell.config.path) in watcher.files(), \
        "原子 replace 换 inode 后必须把配置路径监听起来（否则后续变更全丢）"

    watcher.fileChanged.emit(str(shell.config.path))  # 迟到的重复通知（内容未变）
    _pump(0.8)
    assert applies == [1], f"同内容重发不得二次应用，实为 {applies}"

    external.set("pnpm_bin", "C:/tools/pnpm2.cmd")
    _save_external(external)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and len(applies) < 2:
        app.processEvents()
        time.sleep(0.02)
    _pump(0.8)
    assert applies == [1, 1], f"新的真实改动必须照常应用且只应用一次，实为 {applies}"
    assert shell.config.get("pnpm_bin") == "C:/tools/pnpm2.cmd"


def test_write_during_apply_window_is_not_lost(tmp_path, monkeypatch):
    """应用链执行期间外部落下第二份配置 → 必须照常应用（漏 = 缺陷）。

    签名记成"应用之后"的盘上状态时，这次落盘会被算成已应用，它随后的通知全被去重
    门吞掉（内容只落盘、运行期看不到）。这里 apply 期间真落盘第二份，再按真实通知
    形态 emit 一次 fileChanged。
    """
    shell = _start_shell(tmp_path, monkeypatch, win=_StubWin())
    applies: list[int] = []
    watcher = shell._config_watcher
    second = Config(base=tmp_path)

    def apply_with_concurrent_write():
        applies.append(1)
        if len(applies) == 1:  # 应用链执行期间（去抖回调内）外部写下第二份配置
            second.set("pnpm_bin", "C:/tools/during-apply.cmd")
            _save_external(second)

    shell._apply_external_config_change = apply_with_concurrent_write
    external = Config(base=tmp_path)
    external.set("pnpm_bin", "C:/tools/pnpm.cmd")
    _save_external(external)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not applies:
        app.processEvents()
        time.sleep(0.02)
    _pump(0.8)
    watcher.fileChanged.emit(str(shell.config.path))
    deadline = time.monotonic() + 10.0
    while (time.monotonic() < deadline
           and shell.config.get("pnpm_bin") != "C:/tools/during-apply.cmd"):
        app.processEvents()
        time.sleep(0.02)
    _pump(0.6)
    assert shell.config.get("pnpm_bin") == "C:/tools/during-apply.cmd", \
        "应用期间落盘的第二次保存被去重门吞掉了（只落盘、未进运行期）"
    assert applies == [1, 1], f"第二份配置应恰好再应用一次，实为 {applies}"


def test_same_mtime_size_new_inode_is_not_suppressed(tmp_path, monkeypatch):
    """同 (mtime_ns, size)、只换 inode → 不得误屏蔽（用局部 stat 替身，跨平台）。

    真机 inode 能否区分取决于文件系统（NTFS/APFS/ext4 可以，部分网络/FUSE 挂载
    返回 0），所以这里不依赖宿主能力：在同一台机器上用局部 stat 替身造出"同时间
    戳、同字节数、inode 换了一个"的形态。能力边界如实记在 ``_config_signature``
    的 docstring 里——替身证明的是门与指纹的判定，不是某个文件系统的 inode 语义。
    真实原子 replace 的行为由本文件另两条用例（迟到的同内容重发、应用期间落盘）
    照常覆盖。
    """
    shell = _start_shell(tmp_path, monkeypatch, win=_StubWin())
    applies: list[int] = []
    shell._apply_external_config_change = lambda: applies.append(1)
    path = shell.config.path
    external = Config(base=tmp_path)
    external.set("pnpm_bin", "C:/tools/pnpm.cmd")
    _save_external(external)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not applies:
        app.processEvents()
        time.sleep(0.02)
    _pump(0.8)
    assert applies == [1], f"首轮应用链必须是恰好一次，实为 {applies}"

    base = path.stat()
    real_stat = pathlib.Path.stat

    class _Stat:
        """只提供 ``_config_signature`` 读的三个字段：mtime/size 不变、inode 换号。"""

        def __init__(self, ino):
            self.st_ino = ino
            self.st_mtime_ns = base.st_mtime_ns
            self.st_size = base.st_size
            self.st_mode = base.st_mode

    def fake_stat(self, *, follow_symlinks=True):
        if self == path:
            return _Stat(int(base.st_ino) + 1)
        return real_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(pathlib.Path, "stat", fake_stat)
    shell._config_watcher.fileChanged.emit(str(path))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and len(applies) < 2:
        app.processEvents()
        time.sleep(0.02)
    assert applies == [1, 1], f"同 mtime/size 的新 inode 被误屏蔽了，实为 {applies}"
