# -*- coding: utf-8 -*-
"""批5.2a：子系统上移 + 托盘聚合（单进程多窗共享）的机器可验测试。

覆盖 DISPATCH_batch52a 验收 ①：
- agent_link 上移：单 manager 扇出——两窗各收到呈现事件（全体跳舞）；
- 托盘聚合：单托盘 + 每窗子菜单存在，动作路由正确（显示/隐藏、切换角色、退出这只）；
- 灵动岛单击 toggle **全部**窗（按聚合可见态同步 set_pet_visible）。

4.4b：多窗常开化——共享子系统恒建（`experimental_single_process_spawn`
键已删），故不再有「flag 关不实例化」的对照片区。
"""
from __future__ import annotations

import os
import uuid

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

import pet.app as app_mod
import pet.slot_manager as slot_manager_mod
from pet import catalog
from pet.agent_link import AgentLinkManager
from pet.app import AppShell, PetInstance
from pet.config import Config
from pet.multi_window_shared import MultiWindowProxy, SharedProactiveWatcher


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _FakeLib:
    def pause_warm(self):
        pass

    def resume_warm(self):
        pass


class _RecordWin:
    """记录调用的多窗替身：记录呈现事件，供代理扇出断言。"""

    def __init__(self, visible=True):
        self.is_shown = visible
        self.bubbles: list[str] = []
        self.anims: list[str] = []
        self.activities = 0
        self.link_provider = None
        self.cfg = None
        self._bubble_busy_until = 0.0
        # 非空 dict（代理以 `if c:` 判真）
        self.cats = {"idle": "idle", "acts": ["写代码"], "moves": [], "turns": []}
        self._dragging = False
        self._physics_mode = None
        self._click_effect_phase = 0
        self.mouse_through = False

    # ---- 代理/呈现接口 ----
    def set_link_next_provider(self, p):
        self.link_provider = p

    def show_bubble(self, text, duration_ms=4500):
        self.bubbles.append(text)

    def request_link_anim(self, name):
        self.anims.append(name)

    def request_link_idle(self):
        pass

    def mark_activity(self):
        self.activities += 1

    def clear_pending_link_anim(self):
        pass

    def hold_bubble(self, seconds):
        self._bubble_busy_until = seconds

    def on_look_synced(self, user_text, reply):
        pass

    def isVisible(self):
        return self.is_shown

    def hide(self, notify=True):
        self.is_shown = False

    def show(self):
        self.is_shown = True

    def deleteLater(self):
        pass

    # ---- 托盘构建所需 ----
    def icon_pixmap(self, _size=None):
        return QPixmap(2, 2)

    def set_mouse_through(self, on):
        pass

    def hide_speech_bubble(self):
        pass


class _FakeIsland:
    def __init__(self):
        self.pet_visible = None

    def set_pet_visible(self, visible):
        self.pet_visible = bool(visible)

    def hide(self):
        pass

    def show(self):
        pass

    def refresh_from_config(self):
        pass


def _make_shared_shell(tmp_path):
    config = Config(tmp_path)
    config.save()
    # 4.4a：不再抢 slot 文件锁（多进程多宠退役层停用）；身份直接给主槽。
    shell = AppShell(QApplication.instance(), config, enable_chat=True, slot_id=0)
    return shell, config, None


def _make_primary_record_win(shell, config):
    win = _RecordWin()
    win.cfg = config
    shell.instance.win = win
    return win


def _make_second_record_win(shell, tmp_path, monkeypatch):
    """经 spawn_in_process_window 生成第二实例（独立 slot/Config），窗口为 _RecordWin。"""
    def fake_build_window(self, character_id, lib=None, build_tray=True):
        win = _RecordWin()
        win.cfg = self.config
        self.win = win
        return win

    monkeypatch.setattr(app_mod.PetInstance, "_build_window", fake_build_window)
    monkeypatch.setattr(app_mod.PetInstance, "_apply_spawn_offset", lambda self: None)
    second = shell.spawn_in_process_window(1)
    return second


def _stop_sessions(*_insts):
    """4.4a：碰撞 IPC 会话随多进程多宠退役层停用——保留调用点占位（无操作）。"""


# ======================================================================
# PR57 根因修复：共享 AgentLinkManager 的 win 是 MultiWindowProxy，
# 但它缺 show_alert / resolve_alert，导致单进程多窗下所有交互式提醒
# （审批/问题/控制级 Watchdog）全部静默退化为无按钮纯文本气泡。
# 这里给 proxy 补上 alert 扇出面，并用红→绿测试钉住行为。
# ======================================================================


class _AlertRecordWin:
    """记录 show_alert / show_bubble / resolve_alert 的多窗替身，供 proxy 扇出断言。"""

    def __init__(self, visible=True):
        self.is_shown = bool(visible)
        self.alerts: list[dict] = []
        self.bubbles: list[dict] = []
        self.resolved: list[str] = []
        self.cleared = 0
        self.hidden = 0
        self._bubble_suppressed = False
        self._sticky_bubble_active = False
        self.cfg = None
        self._bubble_busy_until = 0.0
        self._dragging = False
        self._physics_mode = None
        self._click_effect_phase = 0
        self.mouse_through = False
        self.cats = {"idle": "idle", "acts": ["写代码"], "moves": [], "turns": []}

    # ---- 代理/呈现接口 ----
    def isVisible(self):
        return self.is_shown

    def show_bubble(self, text, duration_ms=4500, sticky=False, buttons=None):
        self.bubbles.append({"text": str(text), "sticky": bool(sticky), "buttons": buttons})

    def show_alert(self, text, *, subtitle="", duration_ms=0, buttons=None, sticky=True,
                   alert_id="", priority=3, alert_type="watchdog", metadata=None):
        self.alerts.append({
            "text": str(text), "subtitle": str(subtitle), "buttons": buttons,
            "sticky": bool(sticky), "duration_ms": int(duration_ms),
            "alert_id": str(alert_id), "priority": int(priority),
            "alert_type": str(alert_type), "metadata": dict(metadata or {}),
        })

    def resolve_alert(self, alert_id):
        self.resolved.append(str(alert_id))

    def clear_alerts(self):
        self.cleared += 1

    def hide_bubble(self):
        self.hidden += 1

    def request_link_anim(self, anim):
        pass

    def request_link_idle(self):
        pass

    def set_link_next_provider(self, p):
        pass

    def mark_activity(self):
        pass

    def clear_pending_link_anim(self):
        pass

    def hold_bubble(self, seconds):
        self._bubble_busy_until = seconds

    def on_look_synced(self, user_text, reply):
        pass

    def hide(self, notify=True):
        self.is_shown = False

    def show(self):
        self.is_shown = True

    def deleteLater(self):
        pass


class _ProxyShell:
    """只读 window 替身集合，满足 MultiWindowProxy 的 shell.instances/config 访问面。"""

    def __init__(self, config, windows):
        self.config = config
        self.instances = [type("_Inst", (), {"win": w})() for w in windows]
        self._shared = None


def _make_proxy_manager(tmp_path, windows):
    """构造共享 manager，win 为只读 MultiWindowProxy 集合（生产 320 行同构）。"""
    config = Config(base=tmp_path)
    proxy = MultiWindowProxy(_ProxyShell(config, windows))
    mgr = AgentLinkManager(proxy, config)
    mgr._clock = lambda: 1000.0
    return proxy, mgr


def _control_buttons(alert):
    return [name for name, _ in (alert["buttons"] or [])]


def test_proxy_interaction_approval_fans_out_without_buttons(tmp_path, app):
    """审批提醒经 show_alert 扇出到首个可见窗（不多窗重复）；减法后为纯提示，
    不出「同意/拒绝」按钮。"""
    w1, w2 = _AlertRecordWin(visible=True), _AlertRecordWin(visible=True)
    _, mgr = _make_proxy_manager(tmp_path, [w1, w2])
    try:
        mgr._pending_interactions["itest"] = {
            "kind": "approval", "text": "DSH 有审批等你决定，请到 DSH 界面处理～",
            "rpc_id": "rpc-1", "alert_id": "interaction:itest",
            "session_id": "s1", "agent_key": "dsh",
        }
        mgr._show_interaction_bubble("itest")
        assert w1.alerts, "审批应经 show_alert 展示"
        assert _control_buttons(w1.alerts[-1]) == [], "减法后审批气泡不得出按钮（纯提示）"
        assert not w2.alerts, "审批只在首个可见窗展示"
        # resolved 精确关闭：首个可见窗收起
        mgr._resolve_interaction("itest")
        assert w1.resolved == ["interaction:itest"]
    finally:
        mgr.shutdown()


def test_proxy_bubble_suppressed_aggregates_any(tmp_path, app):
    """新行为：任一见窗打开设置(suppressed)则共享 manager 读到的抑制态为 True。"""
    w1, w2 = _AlertRecordWin(visible=True), _AlertRecordWin(visible=True)
    proxy, mgr = _make_proxy_manager(tmp_path, [w1, w2])
    try:
        assert proxy._bubble_suppressed is False
        w1._bubble_suppressed = True
        assert proxy._bubble_suppressed is True, "任一窗抑制则全局抑制"
        w1._bubble_suppressed = False
        w2._bubble_suppressed = True
        assert proxy._bubble_suppressed is True
        w2._bubble_suppressed = False
        assert proxy._bubble_suppressed is False
    finally:
        mgr.shutdown()


# ============================================================================
# 哨兵语义：_physics_mode 的哨兵是 None（非 False）
#
# 单窗 PetWindow._physics_mode 的取值域是 None / 'drag' / 'throw'，消费方
# （proactive G1 守卫）按 `is not None` 读哨兵。代理早期实现返回 `any(...)`
# 的 bool，把「无人处于物理模式」表达成 False——`False is not None` 恒真，
# 于是共享模式下 interacting 恒为 True、每次 tick 都在 G1 被静默拦截，
# 「主动识屏从不触发」且用户侧开关无效（拿到的是同一个共享实例）。
# 红→绿：修复前 proxy._physics_mode is False。
# ============================================================================


def test_proxy_physics_mode_is_none_when_nobody_in_physics(tmp_path, app):
    """红→绿：所有窗都不在物理模式时，代理必须返回哨兵 None（不是 False）。

    这是 G1 守卫的契约：False 与 None 在布尔上等价，但在 `is not None` 上
    天差地别。返回 False 等于对守卫谎报「有人正在拖拽/抛掷」。
    """
    w1, w2 = _RecordWin(visible=True), _RecordWin(visible=True)
    proxy = MultiWindowProxy(_ProxyShell(Config(base=tmp_path), [w1, w2]))
    value = proxy._physics_mode
    assert value is not False, "不得用 False 冒充「无物理模式」——G1 读的是 is not None"
    assert value is None, "无窗处于物理模式时哨兵必须是 None"


def test_proxy_physics_mode_reports_active_mode(tmp_path, app):
    """任一窗进入物理模式时，代理按哨兵语义报出该模式（任一窗生效）。"""
    w1, w2 = _RecordWin(visible=True), _RecordWin(visible=True)
    proxy = MultiWindowProxy(_ProxyShell(Config(base=tmp_path), [w1, w2]))
    assert proxy._physics_mode is None
    w2._physics_mode = "throw"
    assert proxy._physics_mode == "throw", "任一生效即视为全局处于物理模式（G1 拦话）"
    w2._physics_mode = None
    w1._physics_mode = "drag"
    assert proxy._physics_mode == "drag"
    w1._physics_mode = None
    assert proxy._physics_mode is None


def test_shared_watcher_tick_survives_idle_windows(tmp_path, app, monkeypatch):
    """红→绿：端到端——共享 watcher 在无人交互时，tick 必须越过 G1 守卫。

    修复前 proxy._physics_mode 恒为 False → `is not None` 恒真 → G1 恒定拦截，
    `_on_tick` 在守卫处 return，连前台窗口探测都不发生（用户的实测现象：
    零日志、零状态文件）。这里用「前台窗口查询被调用」作为越过守卫的证据。
    """
    w1, w2 = _RecordWin(visible=True), _RecordWin(visible=True)
    config = Config(base=tmp_path)
    config.set("proactive_screen", {"enabled": True, "whitelist": ["*"]})
    proxy = MultiWindowProxy(_ProxyShell(config, [w1, w2]))
    watcher = SharedProactiveWatcher(proxy, config)
    try:
        from pet import vision

        probed: list[int] = []
        # 返回 None：守卫之后的第一步（前台窗口信息），且不会触发截图/网络，
        # 该分支只清状态、不产生副作用。
        monkeypatch.setattr(
            vision, "foreground_window_info",
            lambda: (probed.append(1), None)[1])

        watcher._on_tick()
        assert probed, (
            "无人交互时 G1 守卫不得拦截——否则共享模式（experimental_"
            "single_process_spawn=true）下主动识屏永不触发")
    finally:
        watcher.stop_all()
