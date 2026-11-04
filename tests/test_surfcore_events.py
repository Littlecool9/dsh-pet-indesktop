# -*- coding: utf-8 -*-
"""SurfCore /events 轮询：顺序、游标、上下线变化、重连、有界停止。"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pet.modules.surfcore.client import API_PREFIX, SurfCoreClient, SurfCoreError
from pet.modules.surfcore.events import EventPoller


def _write_host(path: Path, base_url: str, token: str = "token-a") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "baseUrl": base_url,
                "token": token,
                "api": API_PREFIX,
                "pluginVersion": "test",
                "updatedAt": "2026-11-04T00:00:00.000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class EventServer:
    """只实现 GET /events，按 pet-chat.poll 的 since/wait 语义挂起。"""

    def __init__(self) -> None:
        self.token = "token-a"
        self.cursor = 0
        self.events: list[dict] = []
        self.requests: list[dict] = []
        self._cond = threading.Condition()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                route = (
                    parsed.path[len(API_PREFIX):]
                    if parsed.path.startswith(API_PREFIX)
                    else parsed.path
                )
                headers = {key.lower(): value for key, value in self.headers.items()}
                with api._cond:
                    api.requests.append({"route": route, "query": query})
                    api._cond.notify_all()
                    if route != "/events":
                        status, payload = 404, {"ok": False, "error": "unknown"}
                    elif headers.get("x-pet-token") != api.token:
                        status, payload = 401, {"ok": False, "error": "bad token"}
                    else:
                        status, payload = api._poll(query)
                self._write(status, payload)

            def _write(self, status: int, payload: dict) -> None:
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
        self.server.block_on_close = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def add_event(self, event: dict) -> int:
        with self._cond:
            self.cursor += 1
            event = {"id": self.cursor, "at": 1700000000000, **event}
            self.events.append(event)
            self._cond.notify_all()
            return self.cursor

    def _poll(self, query: dict) -> tuple[int, dict]:
        raw_since = query.get("since")
        since = None if not raw_since or raw_since[0] == "" else int(raw_since[0])
        wait_ms = int((query.get("wait") or ["0"])[0] or 0)
        deadline = time.monotonic() + max(0.0, min(60.0, wait_ms / 1000.0))
        if since is None:
            return 200, {"ok": True, "bootId": "b", "cursor": self.cursor, "events": []}
        if since > self.cursor:
            return 200, {"ok": True, "bootId": "b", "cursor": self.cursor, "events": []}
        while True:
            fresh = [event for event in self.events if event["id"] > since]
            if fresh:
                return 200, {
                    "ok": True,
                    "bootId": "b",
                    "cursor": fresh[-1]["id"],
                    "events": fresh,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 200, {"ok": True, "bootId": "b", "cursor": since, "events": []}
            self._cond.wait(min(remaining, 0.05))

    def wait_for_request(self, predicate, timeout: float = 5.0) -> bool:
        with self._cond:
            deadline = time.monotonic() + timeout
            while not predicate(self.requests):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2.0)


class Recorder:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.events: list[dict] = []
        self.online_changes: list[bool] = []

    def on_event(self, event: dict) -> None:
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def on_online(self, online: bool) -> None:
        with self._cond:
            self.online_changes.append(online)
            self._cond.notify_all()

    def wait_for(self, predicate, timeout: float = 5.0) -> bool:
        with self._cond:
            deadline = time.monotonic() + timeout
            while not predicate():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True


class CountingClient:
    def __init__(self, inner: SurfCoreClient) -> None:
        self.inner = inner
        self._cond = threading.Condition()
        self.calls = 0

    def wait_events(self, since=None, timeout_s: float = 20.0):
        with self._cond:
            self.calls += 1
            self._cond.notify_all()
        return self.inner.wait_events(since, timeout_s)

    def wait_for_calls(self, count: int, timeout: float = 5.0) -> bool:
        with self._cond:
            deadline = time.monotonic() + timeout
            while self.calls < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True


def test_delivers_events_in_order_and_advances_cursor(tmp_path):
    api = EventServer()
    api.cursor = 5
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)
    recorder = Recorder()
    poller = EventPoller(
        client,
        recorder.on_event,
        recorder.on_online,
        backoff=(0.01, 0.02),
        poll_timeout_s=0.1,
    )
    poller.start()
    try:
        assert recorder.wait_for(lambda: recorder.online_changes == [True])
        assert api.wait_for_request(lambda rows: any(row["query"].get("wait") == ["100"] for row in rows))

        api.add_event({"type": "reply", "text": "a"})
        api.add_event({"type": "reply", "text": "b"})
        assert recorder.wait_for(lambda: len(recorder.events) == 2)
        assert [event["id"] for event in recorder.events] == [6, 7]
        assert recorder.wait_for(lambda: recorder.online_changes == [True])

        assert api.wait_for_request(
            lambda rows: any(row["query"].get("since") == ["7"] for row in rows)
        )
        assert poller.cursor == 7
    finally:
        assert poller.stop(2.0)


def test_reconnects_to_new_port_after_server_restart(tmp_path):
    first = EventServer()
    host = _write_host(tmp_path / "host.json", first.base_url)
    client = SurfCoreClient(host_file=host, timeout=1.0)
    recorder = Recorder()
    poller = EventPoller(
        client,
        recorder.on_event,
        recorder.on_online,
        backoff=(0.02, 0.05, 0.1),
        poll_timeout_s=0.1,
    )
    second = None
    poller.start()
    try:
        assert recorder.wait_for(lambda: recorder.online_changes == [True])
        first.close()
        assert recorder.wait_for(lambda: recorder.online_changes == [True, False], timeout=8.0)

        second = EventServer()
        _write_host(tmp_path / "host.json", second.base_url)
        assert recorder.wait_for(
            lambda: recorder.online_changes == [True, False, True], timeout=10.0
        )
        assert poller.online is True
    finally:
        assert poller.stop(2.0)
        if second is not None:
            second.close()
        first.close()


def test_missing_host_is_quietly_offline_and_retry_discovers_it(tmp_path):
    host_path = tmp_path / "host.json"
    client = SurfCoreClient(host_file=host_path, timeout=0.5)
    counting = CountingClient(client)
    recorder = Recorder()
    poller = EventPoller(
        counting,
        recorder.on_event,
        recorder.on_online,
        backoff=(0.02, 0.05),
        poll_timeout_s=0.05,
    )
    api = EventServer()
    poller.start()
    try:
        assert counting.wait_for_calls(1)
        assert recorder.online_changes == []  # 初始就是离线，不算变化

        _write_host(host_path, api.base_url)
        assert recorder.wait_for(lambda: recorder.online_changes == [True])
    finally:
        assert poller.stop(2.0)
        api.close()


def test_stop_interrupts_backoff_wait(tmp_path):
    class NoHostClient:
        def __init__(self) -> None:
            self.called = threading.Event()

        def wait_events(self, since=None, timeout_s: float = 20.0):
            self.called.set()
            raise SurfCoreError("no-host")

    client = NoHostClient()
    poller = EventPoller(client, None, None, backoff=(10, 10), poll_timeout_s=1.0)
    poller.start()
    assert client.called.wait(5.0)
    started = time.monotonic()
    assert poller.stop(1.0) is True
    assert time.monotonic() - started < 1.0


def test_stop_bounds_an_in_flight_long_poll(tmp_path):
    api = EventServer()
    host = _write_host(tmp_path / "host.json", api.base_url)
    client = SurfCoreClient(host_file=host, timeout=2.0)
    poller = EventPoller(client, None, None, backoff=(0.05,), poll_timeout_s=0.5)
    poller.start()
    try:
        assert api.wait_for_request(lambda rows: any(row["route"] == "/events" for row in rows))
        started = time.monotonic()
        assert poller.stop(2.0) is True
        assert time.monotonic() - started < 2.0
        assert not poller.running
    finally:
        poller.stop(2.0)
        api.close()
