# -*- coding: utf-8 -*-
"""QuickChatBubble：气泡外形 + 陪伴线 SurfCore 发送/离线/错误回归。"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.quick_chat import SURFCORE_OFFLINE_REASON, _surface_radius
from pet.speech_bubble import BUBBLE_STYLE_PRESETS


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class FakeCompanion:
    """陪伴线桥替身：只记录 /chat 提交，由用例显式完成。"""

    def __init__(self, online: bool = True) -> None:
        self.online = online
        self.listeners: list = []
        self.sent: list[tuple[str, object]] = []
        self._done = None

    def add_listener(self, callback) -> None:
        self.listeners.append(callback)

    def remove_listener(self, callback) -> None:
        if callback in self.listeners:
            self.listeners.remove(callback)

    def send(self, text, on_done=None) -> bool:
        if not self.online:
            return False
        self.sent.append((text, on_done))
        self._done = on_done
        return True

    def complete(self, text: str) -> None:
        self._done({"ok": True, "reply": {"id": "m-1", "text": text, "modality": "text"}}, None)

    def fail(self, hint: str) -> None:
        from pet.modules.surfcore.client import SurfCoreError

        self._done(None, SurfCoreError("network", hint=hint))

    def set_online(self, online: bool) -> None:
        self.online = bool(online)
        for callback in list(self.listeners):
            callback(self.online)


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


def test_breath_bubble_preset_gets_rounded_fallback_radius():
    """breath_bubble 是 speech_bubble 专属有机形（preset 里 radius=0）：
    quick_chat 不支持该形状，直接按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置两套观感。必须给大圆角近似回退。"""
    preset = BUBBLE_STYLE_PRESETS["breath_bubble"]
    assert preset.get("shape") == "breath_bubble"
    assert _surface_radius(preset) > 0


def test_regular_preset_uses_own_radius():
    """普通预设用自己的 radius（回退不得影响既有外观）。"""
    preset = BUBBLE_STYLE_PRESETS["classic_top"]
    assert _surface_radius(preset) == float(preset.get("radius", 14))


# ---------------------------------------------------------------- SurfCore 陪伴线
def test_send_posts_chat_through_companion_and_shows_reply(tmp_path):
    """发送只经过陪伴线桥（后台 /chat）；等待态与回复落在同一个气泡。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    companion = FakeCompanion()
    bubble.set_companion(companion)
    try:
        bubble.input.setText("今天也要加油")
        bubble._send()

        assert companion.sent and companion.sent[0][0] == "今天也要加油"
        assert bubble.hint_label.text() == "思考中…"
        assert bubble.request_in_flight() is True

        companion.complete("嗯，我在呢")
        assert _pump_until(lambda: not bubble.request_in_flight())
        assert bubble.hint_label.text() == ""
        assert bubble._reply_full == "嗯，我在呢"
        assert "嗯，我在呢" in bubble.output.text()
        assert bubble.send_btn.isEnabled()
    finally:
        bubble.close()
        _qapp().processEvents()


def test_chat_error_shows_surfcore_hint_in_bubble(tmp_path):
    """/chat 失败（busy / 额度 / 网络…）显示 SurfCoreError.hint，不露原始异常。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path), companion=FakeCompanion())
    try:
        bubble.input.setText("在吗")
        bubble._send()
        bubble.companion.fail("今天的额度用完了，明天再试或调高额度。")
        assert _pump_until(lambda: not bubble.request_in_flight())
        assert "额度用完了" in bubble._reply_full
        assert "Traceback" not in bubble._reply_full
        assert bubble.hint_label.text() == ""
    finally:
        bubble.close()
        _qapp().processEvents()


def test_offline_disables_send_with_visible_reason(tmp_path):
    """离线：发送动作禁用 + 气泡内写明原因；发送不提交任何请求。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    companion = FakeCompanion(online=False)
    bubble = QuickChatBubble(Config(base=tmp_path), companion=companion)
    try:
        assert bubble.send_btn.isEnabled() is False
        assert bubble.input.isEnabled() is False
        assert bubble.hint_label.text() == SURFCORE_OFFLINE_REASON
        assert SURFCORE_OFFLINE_REASON == "SurfCore 未连接：启动 DSH 后会自动连上"

        bubble.input.setText("在吗")
        bubble._send()
        assert companion.sent == []
    finally:
        bubble.close()
        _qapp().processEvents()


def test_online_change_reenables_send_and_clears_reason(tmp_path):
    """SurfCore 上线后发送入口恢复、离线原因撤掉（经桥的上下线订阅）。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    companion = FakeCompanion(online=False)
    bubble = QuickChatBubble(Config(base=tmp_path), companion=companion)
    try:
        assert bubble.send_btn.isEnabled() is False
        companion.set_online(True)
        assert bubble.send_btn.isEnabled() is True
        assert bubble.input.isEnabled() is True
        assert bubble.hint_label.text() == ""
        companion.set_online(False)
        assert bubble.send_btn.isEnabled() is False
        assert bubble.hint_label.text() == SURFCORE_OFFLINE_REASON
    finally:
        bubble.close()
        _qapp().processEvents()


def test_companion_closed_removes_online_listener(tmp_path):
    """关气泡必须退订：模块侧不再持有已销毁的气泡回调。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    companion = FakeCompanion()
    bubble = QuickChatBubble(Config(base=tmp_path), companion=companion)
    assert companion.listeners
    bubble.close()
    assert companion.listeners == []


def test_companion_line_has_no_direct_api_transport():
    """陪伴线不得保留直连 API 的旧链路（ChatService / SessionStore / Prompt）。"""
    import inspect

    import pet.quick_chat as quick_chat_mod

    source = inspect.getsource(quick_chat_mod)
    for banned in ("ChatService", "SessionStore", "PromptBuilder", "chat.service"):
        assert banned not in source, f"陪伴线仍引用直连聊天链路：{banned}"


def test_reply_renders_markdown(tmp_path):
    """快捷气泡的助手回复按 Markdown 渲染（对齐现代聊天窗 #249 的口径）——
    用户反馈 v4.3.0 快捷气泡里 markdown 原文直出（**、## 符号裸露）。"""
    _qapp()
    from pet.quick_chat import QuickChatBubble

    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        bubble._set_reply_text("重点**加粗**收尾")
        bubble._render_reply()
        assert 'font-weight:700' in bubble.output.text() and "加粗" in bubble.output.text(), \
            f"markdown 未渲染: {bubble.output.text()[:80]}"  # Qt 写 span font-weight 而非 <strong>
    finally:
        bubble.close()
        _qapp().processEvents()
