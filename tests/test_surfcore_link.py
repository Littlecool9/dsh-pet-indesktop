# -*- coding: utf-8 -*-
"""直连模型 ↔ SurfCore 的核心接缝（人格卡 / 额度闸门 / 用量上报 / 主动说话额度）。

约定与仓库一致：Qt 用例 offscreen；真实后台调用用事件/轮询宽预算同步，不靠
固定 sleep 猜时序；假服务只替换 ``service.submit`` 这个宿主边界。
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from pet import surfcore_link
from pet import vision
from pet.chat.models import ProviderConfig
from pet.config import Config
from pet.modules.host import ModuleHostBase
from pet.modules.surfcore.service import SurfCoreService

PERSONA = "SURF TEST PERSONA：温柔、简短。"
BLOCKED_MESSAGE = "SurfCore 说今天的额度用完了。"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_link():
    surfcore_link.reset()
    yield
    surfcore_link.reset()


class _FakeClient:
    def __init__(self) -> None:
        self.persona_result = {
            "ok": True,
            "role": {"id": "demo", "name": "小咪"},
            "persona": PERSONA,
            "hash": "abcdef",
        }
        self.budget_result: dict = {"ok": True, "available": True, "blocked": False}
        self.claim_result: dict = {"ok": True, "granted": True}
        self.usage_calls: list[tuple[str, dict, str | None]] = []
        self.claim_calls: list[str] = []
        self.budget_calls = 0
        self.persona_threads: list[int] = []

    def persona(self):
        self.persona_threads.append(threading.get_ident())
        return dict(self.persona_result)

    def budget(self):
        self.budget_calls += 1
        return dict(self.budget_result)

    def record_usage(self, model, usage, label=None):
        self.usage_calls.append((model, dict(usage), label))
        return {"ok": True, "recorded": True}

    def claim_proactive(self, source="pet"):
        self.claim_calls.append(source)
        return dict(self.claim_result)


class _FakeService:
    """只实现接缝用到的两个面：``online`` 与同步 ``submit``。"""

    def __init__(self, client: _FakeClient, online: bool = True) -> None:
        self.client = client
        self.online = online

    def submit(self, fn_name, *args, on_done=None, **kwargs):
        try:
            result = getattr(self.client, fn_name)(*args, **kwargs)
            error = None
        except Exception as exc:  # 与真实服务一致：失败只作为结果返回
            result = None
            error = exc
        if on_done is not None:
            on_done(result, error)
        return True


def _pump_until(app, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    idle = threading.Event()
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        idle.wait(0.01)
    return predicate()


# ---------------------------------------------------------------- 人格卡


def test_persona_fetched_off_thread_cached_and_used_offline(qapp, tmp_path):
    client = _FakeClient()
    service = SurfCoreService(client, ModuleHostBase())
    service.online = True
    cache_dir = tmp_path / "config"
    try:
        link = surfcore_link.bind_service(service, cache_dir)
        assert _pump_until(qapp, lambda: link.persona_card() == PERSONA)
        # 真实服务的 submit 在单工作线程执行 client.persona
        assert client.persona_threads
        assert all(tid != threading.get_ident() for tid in client.persona_threads)

        cache_file = cache_dir / surfcore_link.PERSONA_FILE_NAME
        assert cache_file.exists()
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cached["persona"] == PERSONA

        # 重启后离线：没有服务也能从磁盘取回同一份人格卡
        surfcore_link.reset()
        offline = surfcore_link.bind_service(None, cache_dir)
        assert offline.persona_card() == PERSONA
        assert offline.persona_or("本地人设") == PERSONA
    finally:
        service.stop()


def test_no_persona_falls_back_to_local_prompt():
    assert surfcore_link.persona_card() is None
    assert surfcore_link.persona_or("本地人设") == "本地人设"


# ---------------------------------------------------------------- 额度


def test_budget_gate_blocked_available_false_and_offline():
    blocked_client = _FakeClient()
    blocked_client.budget_result = {
        "ok": True,
        "available": True,
        "blocked": True,
        "message": BLOCKED_MESSAGE,
    }
    blocked = surfcore_link.bind_service(_FakeService(blocked_client), None)
    assert blocked.budget_gate("桌宠助手") == (False, BLOCKED_MESSAGE)

    unavailable_client = _FakeClient()
    unavailable_client.budget_result = {"ok": True, "available": False}
    unavailable = surfcore_link.bind_service(_FakeService(unavailable_client), None)
    assert unavailable.budget_gate("桌宠助手") == (True, "")

    surfcore_link.reset()
    assert surfcore_link.budget_gate("桌宠助手") == (True, "")


# ---------------------------------------------------------------- 用量


def test_usage_report_sends_only_numbers_model_and_label(tmp_path):
    client = _FakeClient()
    link = surfcore_link.bind_service(_FakeService(client), tmp_path)
    budgets_before = client.budget_calls

    usage = {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
        "text": "聊天正文绝不能外发",
        "nested": {"content": "screen text"},
        "ok": True,
    }
    assert link.report_usage("deepseek-v4-flash", usage, "桌宠助手") is True

    assert client.usage_calls == [(
        "deepseek-v4-flash",
        {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        "桌宠助手",
    )]
    # 记账后强制刷新额度缓存（可以越过 60 秒节流）
    assert client.budget_calls == budgets_before + 1


# ---------------------------------------------------------------- 主动说话额度


def test_claim_proactive_granted_denied_and_offline():
    client = _FakeClient()
    link = surfcore_link.bind_service(_FakeService(client), None)
    results: list[tuple[bool, str]] = []

    client.claim_result = {"ok": True, "granted": True}
    assert link.claim_proactive("vision", lambda g, r: results.append((g, r))) is True
    assert results == [(True, "")]

    client.claim_result = {"ok": True, "granted": False, "reason": "gap"}
    assert link.claim_proactive("vision", lambda g, r: results.append((g, r))) is True
    assert results[-1] == (False, "gap")
    assert client.claim_calls == ["vision", "vision"]

    surfcore_link.reset()
    assert surfcore_link.claim_proactive("vision", lambda g, r: results.append((g, r))) is False
    assert len(results) == 2


# ---------------------------------------------------------------- 主动识屏气泡


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, **extra):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class _ProactiveWindow:
    on_open_chat = True

    def __init__(self) -> None:
        self.mouse_through = False
        self._dragging = False
        self._physics_mode = None
        self._click_effect_phase = 0
        self.bubbles: list[str] = []

    def isVisible(self):
        return True

    def show_bubble(self, text, duration_ms=3000):
        self.bubbles.append(text)


def _proactive_watcher(tmp_path, monkeypatch):
    from pet.proactive import ProactiveScreenWatcher

    # 让 _dispatch_vision_request 的 worker 在本线程同步跑，时序完全确定。
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    cfg = Config(base=tmp_path)
    cfg.set("proactive_screen", {
        "enabled": True,
        "whitelist": ["code.exe"],
        "pre_cue": True,
    })
    win = _ProactiveWindow()
    watcher = ProactiveScreenWatcher(win, cfg)
    watcher.limiter.dry_run = False
    return watcher, win


def _fake_vision(monkeypatch, calls: list) -> None:
    def fake_post(jpeg_bytes, app_str, prompt, p, **kwargs):
        consume = kwargs.get("consume_budget")
        if consume is not None:
            consume()
        calls.append((app_str, prompt, kwargs.get("memory_context", "")))
        return "看到你在写代码呢"

    monkeypatch.setattr(vision, "_post_vision_request", fake_post)


def _frame():
    from PIL import Image

    return Image.new("RGB", (40, 40), (10, 20, 30))


def test_proactive_bubble_only_when_claimed(tmp_path, monkeypatch):
    from pet import proactive as proactive_mod

    client = _FakeClient()
    client.claim_result = {"ok": True, "granted": False, "reason": "gap"}
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    calls: list = []
    _fake_vision(monkeypatch, calls)
    watcher, win = _proactive_watcher(tmp_path, monkeypatch)

    watcher._on_frame_ready(_frame(), "code.exe | t", 1, 0x1234,
                            {"process": "code.exe", "title": "t"})

    assert win.bubbles == [], "拒绝时不得出现先兆或答复气泡"
    assert calls == []
    assert client.claim_calls == ["vision"]
    assert watcher.limiter._load_state()["count"] == 0
    assert watcher._request_in_flight is False


def test_proactive_claim_granted_shows_bubble(tmp_path, monkeypatch):
    client = _FakeClient()
    client.claim_result = {"ok": True, "granted": True}
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    calls: list = []
    _fake_vision(monkeypatch, calls)
    watcher, win = _proactive_watcher(tmp_path, monkeypatch)

    watcher._on_frame_ready(_frame(), "code.exe | t", 1, 0x1234,
                            {"process": "code.exe", "title": "t"})

    assert watcher.limiter._load_state()["count"] == 0, "在线时由 SurfCore 记额度"
    assert "让我看看……" in win.bubbles
    assert "看到你在写代码呢" in win.bubbles
    assert len(calls) == 1
    assert watcher._request_in_flight is False


def test_proactive_offline_uses_local_limiter(tmp_path, monkeypatch):
    surfcore_link.reset()
    calls: list = []
    _fake_vision(monkeypatch, calls)
    watcher, win = _proactive_watcher(tmp_path, monkeypatch)

    watcher._on_frame_ready(_frame(), "code.exe | t", 1, 0x1234,
                            {"process": "code.exe", "title": "t"})

    assert watcher.limiter._load_state()["count"] == 1, "离线时今天的行为不变"
    assert "看到你在写代码呢" in win.bubbles
    assert len(calls) == 1


def test_proactive_budget_blocked_no_bubble_or_claim(tmp_path, monkeypatch):
    client = _FakeClient()
    client.budget_result = {
        "ok": True, "available": True, "blocked": True, "message": BLOCKED_MESSAGE,
    }
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    calls: list = []
    _fake_vision(monkeypatch, calls)
    watcher, win = _proactive_watcher(tmp_path, monkeypatch)

    watcher._on_frame_ready(_frame(), "code.exe | t", 1, 0x1234,
                            {"process": "code.exe", "title": "t"})

    assert win.bubbles == []
    assert calls == []
    assert client.claim_calls == []
    assert watcher._request_in_flight is False


# ---------------------------------------------------------------- 视觉 / 翻译直连


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")


def _capture_urlopen(monkeypatch, payload):
    calls: list[dict] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(json.loads(req.data.decode("utf-8")))
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    from pet.chat import providers as providers_mod

    monkeypatch.setattr(providers_mod, "_make_ssl_context", lambda _verify: object())
    return calls


def test_vision_uses_surfcore_persona_and_reports_usage(tmp_path, monkeypatch):
    client = _FakeClient()
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    body = {
        "choices": [{"message": {"content": "看到啦"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }
    calls = _capture_urlopen(monkeypatch, body)
    p = ProviderConfig.from_dict("test", {"api_key": "sk-test"})

    reply = vision._post_vision_request(b"jpeg", "code.exe | t", "本地人设", p)

    assert reply == "看到啦"
    assert calls[0]["messages"][0]["content"] == PERSONA
    # 上报的是实际发出去的模型名（官方 DS 映射到 deepseek-flash）
    assert client.usage_calls == [(
        "deepseek-flash",
        {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        "桌宠识屏",
    )]


def test_vision_budget_block_prevents_request(tmp_path, monkeypatch):
    client = _FakeClient()
    client.budget_result = {
        "ok": True, "available": True, "blocked": True, "message": BLOCKED_MESSAGE,
    }
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    calls = _capture_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "不应到达"}}],
    })
    p = ProviderConfig.from_dict("test", {"api_key": "sk-test"})

    with pytest.raises(vision.VisionError, match="额度"):
        vision._post_vision_request(b"jpeg", "code.exe | t", "本地人设", p)
    assert calls == []


def test_translate_reports_usage_with_screen_label(tmp_path, monkeypatch):
    from pet.screen_capture.translate import translate_text

    client = _FakeClient()
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    body = {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
    }
    calls = _capture_urlopen(monkeypatch, body)
    provider = ProviderConfig.from_dict("test", {"api_key": "sk-test", "model": "deepseek-v4-flash"})
    cfg = SimpleNamespace(
        chat_settings=lambda: SimpleNamespace(
            active_config=provider, default_system_prompt="本地人设"),
        resolve_api_key=lambda p: p.api_key,
    )

    assert translate_text("你好", cfg) == "hello"
    assert calls
    assert client.usage_calls == [(
        "deepseek-v4-flash",
        {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        "桌宠识屏",
    )]


# ---------------------------------------------------------------- 聊天窗


class _FakeChatService(QObject):
    started = Signal(str)
    delta = Signal(str, str)
    finished = Signal(str, str)
    error = Signal(str, str)
    stopped = Signal(str)
    activity = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.sent: list[list[dict]] = []
        self.last_usage = None

    def send(self, messages, config, request_id=None):
        self.sent.append(messages)
        return request_id or "rid"

    def stop(self):
        pass


class _PetHost:
    def set_chat_status(self, state, text=""):
        pass


def _chat_window(tmp_path, monkeypatch, service):
    from pet.chat import widgets as chat_widgets

    monkeypatch.setattr(chat_widgets, "ChatService", lambda parent=None: service)
    window = chat_widgets.ChatWindow(
        Config(tmp_path), "shenshen", pet_window=_PetHost())
    return window


def _send(window, service):
    window.input.setPlainText("你好")
    window.send_message()
    return service.sent[-1]


def test_chat_window_uses_surfcore_persona_and_reports_usage(tmp_path, monkeypatch):
    client = _FakeClient()
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    service = _FakeChatService()
    window = _chat_window(tmp_path, monkeypatch, service)
    try:
        messages = _send(window, service)
        assert messages[0]["role"] == "system"
        assert PERSONA in messages[0]["content"]

        service.last_usage = {"prompt_tokens": 3, "completion_tokens": 4,
                              "total_tokens": 7}
        service.finished.emit(window._active_request_id, "回复")
        assert client.usage_calls[-1][0] == "deepseek-v4-flash"
        assert client.usage_calls[-1][1] == {
            "prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
        assert client.usage_calls[-1][2] == "桌宠助手"
    finally:
        window.close()
        window.deleteLater()


def test_chat_window_budget_block_shows_message_without_calling_api(
        tmp_path, monkeypatch):
    client = _FakeClient()
    client.budget_result = {
        "ok": True, "available": True, "blocked": True, "message": BLOCKED_MESSAGE,
    }
    surfcore_link.bind_service(_FakeService(client), tmp_path)
    service = _FakeChatService()
    window = _chat_window(tmp_path, monkeypatch, service)
    try:
        window.input.setPlainText("你好")
        window.send_message()

        assert service.sent == [], "额度拦截时不得调用模型 API"
        assert window.status.text() == "额度已用完"
        assert "请求未发送" in window._bubble._raw_text
        assert BLOCKED_MESSAGE in window._bubble._raw_text
    finally:
        window.close()
        window.deleteLater()
