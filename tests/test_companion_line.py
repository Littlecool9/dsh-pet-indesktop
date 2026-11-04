# -*- coding: utf-8 -*-
"""陪伴线（快速气泡 / 岛对话 / 主动搭话）走 SurfCore 的端到端回归。

真实 ``SurfCoreService`` + 假客户端 / 假宿主：/chat 在后台线程执行、完成回调
经宿主事件总线回到 GUI 线程；主动事件只有宿主门禁通过才冒泡；离线时发送与
菜单入口一起置灰并写明原因。
"""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.module_host import AppModuleHost, module_service
from pet.modules.host import ModuleHostBase
from pet.modules.surfcore.client import SurfCoreError
from pet.modules.surfcore.companion import OFFLINE_HINT, CompanionBridge
from pet.modules.surfcore.service import SurfCoreService
from pet.quick_chat import SURFCORE_OFFLINE_REASON, QuickChatBubble


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, *, timeout: float = 10.0) -> bool:
    app = _qapp()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


class _FakeOverlay:
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(get=lambda key, default=None: default)
        self.ready = True
        self.shown: list[tuple[str, int]] = []

    def self_talk_ready(self) -> bool:
        return self.ready

    def show_bubble(self, text, duration_ms=3200, **_kwargs) -> bool:
        if not self.ready:
            return False
        self.shown.append((str(text), int(duration_ms)))
        return True


class _FakeShell:
    def __init__(self) -> None:
        self.config = SimpleNamespace(get=lambda key, default=None: default)
        self.app = None
        self._overlay_shell = _FakeOverlay()
        self._module_host = None


class _FakeClient:
    """只替换网络边界：记录 /chat 调用线程与参数，可注入失败。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.error: Exception | None = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def chat(self, text, *, modality="text"):
        self.calls.append((str(text), str(modality), threading.get_ident()))
        self.entered.set()
        assert self.release.wait(10.0)
        if self.error is not None:
            raise self.error
        return {"ok": True, "reply": {"id": "a-1", "text": f"回复：{text}", "modality": modality}}


def _make_service(shell: _FakeShell, client: _FakeClient):
    host = AppModuleHost(shell)
    shell._module_host = host
    service = SurfCoreService(client, host)
    bridge = CompanionBridge(host, service)
    service.companion = bridge
    host.provide("surfcore", service)
    service.online = True
    return host, service, bridge


def test_quick_chat_sends_through_service_off_gui_thread_and_shows_reply(tmp_path):
    """GUI 线程不被 /chat 占住；回复经宿主事件总线回到气泡。"""
    _qapp()
    gui_thread = threading.get_ident()
    shell = _FakeShell()
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    bubble = QuickChatBubble(Config(base=tmp_path), companion=bridge)
    try:
        bubble.input.setText("在吗")
        bubble._send()
        assert client.entered.wait(5.0)
        assert client.calls[0][0] == "在吗"
        assert client.calls[0][1] == "text"
        assert client.calls[0][2] != gui_thread, "/chat 必须在后台线程执行"
        assert bubble.request_in_flight() is True
        assert bubble.hint_label.text() == "思考中…"

        assert _pump_until(lambda: bubble.request_in_flight() is False)
        assert bubble._reply_full == "回复：在吗"
        assert "回复：在吗" in bubble.output.text()
    finally:
        bubble.close()
        service.stop()
        _qapp().processEvents()


def test_island_chat_sends_through_the_same_companion(tmp_path):
    """岛对话气泡复用同一陪伴线桥：/chat 回复落回岛上。"""
    _qapp()
    from pet.island_chat import IslandChatBubble

    shell = _FakeShell()
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    bubble = IslandChatBubble(Config(base=tmp_path), companion=bridge)
    try:
        bubble.input.setText("在岛上")
        bubble._send()
        assert _pump_until(lambda: bubble.request_in_flight() is False)
        assert bubble._reply_full == "回复：在岛上"
        assert "回复：在岛上" in bubble.output.text()
    finally:
        bubble.close()
        service.stop()
        _qapp().processEvents()


def test_quick_chat_error_uses_surfcore_hint(tmp_path):
    """额度 / 忙 / 网络错误都把 SurfCoreError.hint 落进气泡。"""
    _qapp()
    shell = _FakeShell()
    client = _FakeClient()
    client.error = SurfCoreError("budget-blocked", 429, "今天的额度用完了，明天再试或调高额度。")
    host, service, bridge = _make_service(shell, client)
    bubble = QuickChatBubble(Config(base=tmp_path), companion=bridge)
    try:
        bubble.input.setText("在吗")
        bubble._send()
        assert _pump_until(lambda: bubble.request_in_flight() is False)
        assert bubble._reply_full == "今天的额度用完了，明天再试或调高额度。"
        assert bubble.hint_label.text() == ""
    finally:
        bubble.close()
        service.stop()
        _qapp().processEvents()


def test_proactive_event_becomes_a_pet_bubble_through_the_host():
    """SurfCore 主动消息 → 宿主可点气泡（点击即快速对话）；非消息事件忽略。"""
    _qapp()
    shell = _FakeShell()
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    try:
        host.emit("surfcore.event", {"id": 1, "type": "focus", "enabled": True})
        host.emit("surfcore.event", {
            "id": 2, "type": "proactive", "text": "主人，该喝水啦",
            "modality": "text", "messageId": "p-1",
        })
        host.emit("surfcore.event", {
            "id": 3, "type": "reply", "text": "外部回复", "messageId": "r-1",
        })
        assert _pump_until(lambda: len(shell._overlay_shell.shown) == 2)
        assert [item[0] for item in shell._overlay_shell.shown] == [
            "主人，该喝水啦", "外部回复"]
    finally:
        service.stop()
        _qapp().processEvents()


def test_proactive_event_respects_host_gates():
    """门禁不过（专注/全屏/隐藏/免打扰）时主动消息不上屏。"""
    _qapp()
    from pet.quiet_mode import reset_shared_quiet_state, shared_quiet_state

    shell = _FakeShell()
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    event = {"id": 7, "type": "proactive", "text": "不该出现", "messageId": "p-7"}
    try:
        shell._overlay_shell.ready = False
        host.emit("surfcore.event", event)
        _qapp().processEvents()
        assert shell._overlay_shell.shown == []

        shell._overlay_shell.ready = True
        shared_quiet_state().start(30)
        host.emit("surfcore.event", dict(event, id=8))
        _qapp().processEvents()
        assert shell._overlay_shell.shown == []

        reset_shared_quiet_state()
        host.emit("surfcore.event", dict(event, id=9))
        assert _pump_until(lambda: len(shell._overlay_shell.shown) == 1)
    finally:
        reset_shared_quiet_state()
        service.stop()
        _qapp().processEvents()


def test_offline_disables_quick_chat_send_and_menu_entry(tmp_path):
    """离线：气泡发送禁用 + 可见原因；菜单通过 disabled_reason 给同一句。"""
    _qapp()
    from pet.modules.surfcore import menu as surfcore_menu

    shell = _FakeShell()
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    service.online = False
    bubble = QuickChatBubble(Config(base=tmp_path), companion=bridge)
    try:
        assert bubble.send_btn.isEnabled() is False
        assert bubble.hint_label.text() == SURFCORE_OFFLINE_REASON
        assert SURFCORE_OFFLINE_REASON == OFFLINE_HINT

        module = SimpleNamespace(online=False)
        pet = SimpleNamespace(
            running_module=lambda module_id: module,
            module_unavailable_reason=lambda module_id: "",
            on_open_quick_chat=lambda: None,
        )
        spec = surfcore_menu.actions()[surfcore_menu.ACTION_ID]
        assert spec.enabled(pet) is False
        assert spec.disabled_reason(pet) == OFFLINE_HINT

        module.online = True
        assert spec.enabled(pet) is True
        service.online = True
        host.emit("surfcore.online", True)
        assert _pump_until(lambda: bubble.send_btn.isEnabled() is True) is True
    finally:
        bubble.close()
        service.stop()
        _qapp().processEvents()


def test_core_reads_the_bridge_only_through_the_service_table():
    """核心经 module_service 拿陪伴线桥；模块缺失 = 离线，不 import 模块。"""
    shell = _FakeShell()
    assert module_service(shell, "surfcore") is None
    client = _FakeClient()
    host, service, bridge = _make_service(shell, client)
    try:
        got = module_service(shell, "surfcore")
        assert got is service
        assert got.companion is bridge
    finally:
        service.stop()
        _qapp().processEvents()


def test_module_host_requires_visible_pet_for_companion_bubbles():
    """桌宠隐藏（self_talk_ready=False）时宿主直接拒绝上屏。"""
    shell = _FakeShell()
    shell._overlay_shell.ready = False
    host = AppModuleHost(shell)
    assert host.companion_bubble_ready() is False
    assert host.show_companion_bubble("不该出现") is False
    shell._overlay_shell.ready = True
    assert host.show_companion_bubble("出现") is True
    assert shell._overlay_shell.shown == [("出现", 6000)]


def test_module_host_does_not_need_a_plain_module_host_base():
    """ModuleHostBase 没有陪伴线呈现面时桥只做发送，不自行造气泡。"""
    host = ModuleHostBase()
    service = SurfCoreService(_FakeClient(), host)
    bridge = CompanionBridge(host, service)
    try:
        host.emit("surfcore.event", {"id": 1, "type": "proactive", "text": "无宿主"})
        _qapp().processEvents()
    finally:
        bridge.stop()
        service.stop()
