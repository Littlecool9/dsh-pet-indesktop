# -*- coding: utf-8 -*-
"""SurfCore pet-api 客户端：发现、鉴权重发现、错误码、代理绕开、请求体。"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import FrozenInstanceError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from pet.modules.surfcore.client import (
    API_PREFIX,
    ROUTE_PATHS,
    HostInfo,
    SurfCoreClient,
    SurfCoreError,
    read_host_info,
)

ROOT = Path(__file__).resolve().parents[1]
PET_API_JS = ROOT / "surfcore" / "plugins" / "surfcore" / "lib" / "pet-api.js"


def _write_host(
    path: Path,
    base_url: str,
    *,
    token: str = "token-a",
    api: str = API_PREFIX,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "baseUrl": base_url,
                "token": token,
                "api": api,
                "pluginVersion": "test",
                "updatedAt": "2026-11-04T00:00:00.000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class FakePetApi:
    """本地假 pet-api：回环 + x-pet-token，路由响应可逐条改写。"""

    def __init__(self) -> None:
        self.token = "token-a"
        self.requests: list[dict] = []
        self.routes: dict[tuple[str, str], object] = {
            ("GET", "/health"): (200, {"ok": True, "name": "surfcore-pet", "version": "test"}),
            ("GET", "/status"): (200, {"ok": True, "client": {"online": True}}),
            ("GET", "/persona"): (
                200,
                {
                    "ok": True,
                    "role": {"id": "demo", "name": "小咪"},
                    "persona": "# 小咪\n温柔一点。",
                    "owner": {"name": "主人"},
                    "hash": "abcdef012345",
                },
            ),
            ("GET", "/budget"): (200, {"ok": True, "available": True, "blocked": False}),
            ("POST", "/usage"): (200, {"ok": True, "recorded": True}),
            ("POST", "/self-talk"): (200, {"ok": True, "text": "慢慢来", "role": {"name": "小咪"}}),
            ("POST", "/focus"): (200, {"ok": True, "focus": {"enabled": True}}),
            ("POST", "/proactive/claim"): (200, {"ok": True, "granted": True}),
            ("POST", "/chat"): (200, {"ok": True, "reply": {"text": "嗯"}}),
            ("GET", "/events"): (200, {"ok": True, "bootId": "b", "cursor": 0, "events": []}),
        }
        self._cond = threading.Condition()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                parsed = urlsplit(self.path)
                route = (
                    parsed.path[len(API_PREFIX):]
                    if parsed.path.startswith(API_PREFIX)
                    else parsed.path
                )
                query = parse_qs(parsed.query)
                headers = {key.lower(): value for key, value in self.headers.items()}
                with api._cond:
                    api.requests.append(
                        {
                            "method": self.command,
                            "route": route,
                            "query": query,
                            "headers": headers,
                            "body": body,
                        }
                    )
                    api._cond.notify_all()
                    expected = api.token
                if headers.get("x-pet-token") != expected:
                    self._write(401, {"ok": False, "error": "bad token"})
                    return
                entry = api.routes.get((self.command, route))
                if entry is None:
                    self._write(404, {"ok": False, "error": "unknown"})
                    return
                if callable(entry):
                    status, payload = entry(self.command, body, query)
                else:
                    status, payload = entry
                self._write(status, payload)

            def _write(self, status: int, payload) -> None:
                if isinstance(payload, (bytes, bytearray)):
                    data = bytes(payload)
                else:
                    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def wait_for(self, predicate, timeout: float = 5.0) -> bool:
        """等待 ``predicate(requests)`` 成立；只在条件变量上等，不猜时序。"""
        with self._cond:
            deadline = time.monotonic() + timeout
            while not predicate(self.requests):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def snapshot(self) -> list[dict]:
        with self._cond:
            return list(self.requests)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2.0)


@pytest.fixture
def api():
    server = FakePetApi()
    try:
        yield server
    finally:
        server.close()


def _last_request(api: FakePetApi) -> dict:
    return api.requests[-1]


def test_read_host_info_missing_invalid_and_non_loopback(tmp_path):
    assert read_host_info(tmp_path / "missing.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert read_host_info(bad) is None

    for index, base_url in enumerate(
        (
            "http://192.168.1.5:57981",
            "https://example.com",
            "ftp://127.0.0.1:57981",
            "http://127.0.0.1.evil.test:57981",
        )
    ):
        path = _write_host(tmp_path / f"host-{index}.json", base_url)
        assert read_host_info(path) is None, base_url

    valid = _write_host(tmp_path / "valid.json", "http://127.0.0.1:57981/")
    info = read_host_info(valid)
    assert info == HostInfo(
        base_url="http://127.0.0.1:57981",
        token="token-a",
        api=API_PREFIX,
        plugin_version="test",
        updated_at="2026-11-04T00:00:00.000Z",
    )
    with pytest.raises(FrozenInstanceError):
        info.token = "other"


def test_client_sends_token_header_and_exact_bodies(tmp_path, api):
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)

    assert client.health()["ok"] is True
    request = _last_request(api)
    assert request["headers"]["x-pet-token"] == "token-a"
    assert request["route"] == "/health"

    client.status()
    client.persona()
    client.budget()

    client.record_usage("deepseek-flash", {"outputTokens": 12}, "看图")
    assert _last_request(api)["body"] == {
        "model": "deepseek-flash",
        "usage": {"outputTokens": 12},
        "label": "看图",
    }

    client.self_talk({"recent": "刚写完代码"})
    assert _last_request(api)["body"] == {"context": {"recent": "刚写完代码"}}

    client.set_focus(True, phase="work", ends_at=1700000000000, source="desktop-pet")
    assert _last_request(api)["body"] == {
        "enabled": True,
        "source": "desktop-pet",
        "phase": "work",
        "endsAt": 1700000000000,
    }

    client.claim_proactive("vision")
    assert _last_request(api)["body"] == {"source": "vision"}

    client.chat("在吗", modality="voice")
    assert _last_request(api)["body"] == {"text": "在吗", "modality": "voice"}
    assert _last_request(api)["headers"]["content-type"].startswith("application/json")


def test_401_invalidates_and_next_request_uses_new_host_token(tmp_path, api):
    api.token = "new-token"
    host = _write_host(tmp_path / "host.json", api.base_url, token="old-token")
    client = SurfCoreClient(host_file=host, timeout=2.0)

    with pytest.raises(SurfCoreError) as error:
        client.health()
    assert error.value.code == "unauthorized"
    assert error.value.status == 401
    assert _last_request(api)["headers"]["x-pet-token"] == "old-token"

    _write_host(host, api.base_url, token="new-token")
    assert client.health()["ok"] is True
    assert _last_request(api)["headers"]["x-pet-token"] == "new-token"


def test_documented_statuses_map_to_stable_error_codes(tmp_path, api):
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)

    cases = [
        ("POST", "/self-talk", 409, {"ok": False, "code": "busy", "hint": "还在生成"}, "busy",
         lambda: client.self_talk()),
        ("POST", "/self-talk", 429, {"ok": False, "code": "budget-blocked", "hint": "额度用完"}, "budget-blocked",
         lambda: client.self_talk()),
        ("POST", "/self-talk", 503, {"ok": False, "code": "llm-unavailable", "hint": "模型未就绪"}, "llm-unavailable",
         lambda: client.self_talk()),
        ("POST", "/self-talk", 502, {"ok": False, "code": "model-failed"}, "http-502",
         lambda: client.self_talk()),
        ("GET", "/budget", 503, {"ok": False, "code": "budget-unavailable", "hint": "读不到"}, "http-503",
         lambda: client.budget()),
        ("POST", "/usage", 400, {"ok": False, "code": "invalid-usage", "hint": "usage 不合法"}, "bad-request",
         lambda: client.record_usage("m", {})),
        ("POST", "/chat", 400, {"ok": False, "error": "说点什么吧"}, "bad-request",
         lambda: client.chat("")),
        ("GET", "/health", 500, {"ok": False, "error": "boom"}, "http-500",
         lambda: client.health()),
    ]
    for method, route, status, payload, expected, call in cases:
        api.routes[(method, route)] = (status, payload)
        with pytest.raises(SurfCoreError) as error:
            call()
        assert error.value.code == expected
        assert error.value.status == status
        assert error.value.hint


def test_network_error_and_bad_response_codes(tmp_path):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()

    host = _write_host(tmp_path / "host.json", f"http://127.0.0.1:{closed_port}")
    client = SurfCoreClient(host_file=host, timeout=1.0)
    with pytest.raises(SurfCoreError) as error:
        client.health()
    assert error.value.code == "network"
    assert error.value.status is None


def test_bad_response_json_is_not_silently_accepted(tmp_path, api):
    api.routes[("GET", "/health")] = (200, b"{not-json")
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)
    with pytest.raises(SurfCoreError) as error:
        client.health()
    assert error.value.code == "bad-response"
    assert error.value.status == 200


def test_loopback_requests_bypass_unreachable_system_proxy(tmp_path, api, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)
    assert client.health()["ok"] is True
    assert api.requests[-1]["route"] == "/health"


def test_wait_events_uses_server_cursor_and_wait_query(tmp_path, api):
    seen: list[dict] = []

    def events_response(method, body, query):
        seen.append(query)
        return 200, {"ok": True, "bootId": "b", "cursor": 7, "events": []}

    api.routes[("GET", "/events")] = events_response
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)

    assert client.wait_events(None, 0.05)["cursor"] == 7
    assert "since" not in seen[-1]
    assert seen[-1]["wait"] == ["50"]

    assert client.wait_events(7, 0.05)["cursor"] == 7
    assert seen[-1]["since"] == ["7"]


def test_route_paths_all_exist_in_pet_api_js():
    source = PET_API_JS.read_text(encoding="utf-8")
    missing = [route for route in ROUTE_PATHS if f"'{route}'" not in source]
    assert not missing, f"客户端用了 pet-api.js 未注册的路由：{missing}"


def test_token_and_message_text_never_logged(tmp_path, api, caplog):
    caplog.set_level(logging.DEBUG)
    api.routes[("POST", "/chat")] = (502, {"ok": False, "code": "model-failed", "hint": "稍后再试"})
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)

    with pytest.raises(SurfCoreError):
        client.chat("secret-message-text")

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "token-a" not in logged
    assert "secret-message-text" not in logged
