# -*- coding: utf-8 -*-
"""SurfCore pet-api 的本机客户端（无 Qt 依赖）。

发现：DSH 的 SurfCore 插件把 ``~/.dsh/surfcore/pet/host.json`` 写成
``{version, baseUrl, token, api, pluginVersion, updatedAt}``。客户端只在第一次请求时
读它，网络错误或 401 后清掉缓存，下次请求重新读（DSH 端口漂移时靠这个重连）。

安全边界：

- 只接受回环 ``baseUrl``（127.0.0.1 / localhost / ::1）；
- 请求只带 ``x-pet-token``，从不把令牌拼进 URL；
- 客户端不写日志，令牌与消息文本都不会进入日志。
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_PREFIX = "/dsh-surfcore/pet-api"
"""插件注册的 pet-api 前缀；host.json 里的 ``api`` 才是权威值。"""

ROUTE_PATHS: tuple[str, ...] = (
    "/health",
    "/status",
    "/persona",
    "/budget",
    "/usage",
    "/self-talk",
    "/focus",
    "/proactive/claim",
    "/chat",
    "/events",
)
"""客户端用到的所有路由（契约测试会逐条核对 pet-api.js 里确实注册了它们）。"""

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_DEFAULT_HINTS: dict[str, str] = {
    "no-host": "没找到 SurfCore 连接文件；重启 DSH 会自动重写 host.json。",
    "unauthorized": "桌宠令牌无效；DSH 重写 host.json 后会自动重连。",
    "busy": "上一条还在生成，稍后再试。",
    "budget-blocked": "今天的额度用完了，明天再试或调高额度。",
    "llm-unavailable": "模型服务还没就绪，稍后再试。",
    "bad-request": "请求参数不被接受，稍后再试。",
    "network": "暂时连不上 SurfCore，稍后自动重试。",
    "bad-response": "SurfCore 返回了无法识别的数据。",
}


class SurfCoreError(Exception):
    """带稳定错误码的 pet-api 失败。

    ``code`` 是调用方分支用的稳定值：``no-host`` / ``unauthorized`` / ``busy`` /
    ``budget-blocked`` / ``llm-unavailable`` / ``bad-request`` / ``http-<status>`` /
    ``network`` / ``bad-response``。``hint`` 是给用户看的一句中文。
    """

    def __init__(self, code: str, status: int | None = None, hint: str = "") -> None:
        self.code = str(code)
        self.status = status
        self.hint = hint or _DEFAULT_HINTS.get(self.code, "")
        super().__init__(self.hint or self.code)


@dataclass(frozen=True)
class HostInfo:
    """host.json 里客户端真正需要的字段。"""

    base_url: str
    token: str
    api: str
    plugin_version: str = ""
    updated_at: str = ""


def default_host_file() -> Path:
    """DSH / SurfCore 的默认发现文件。"""
    return Path.home() / ".dsh" / "surfcore" / "pet" / "host.json"


def _loopback_base_url(value: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if parts.username is not None or parts.password is not None:
        return False
    host = (parts.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def read_host_info(path: str | Path) -> HostInfo | None:
    """读 host.json；缺失 / 不可读 / 字段不合法 / 非回环地址都返回 ``None``。

    这个函数是发现入口，不能因为文件暂时不存在就抛异常（DSH 没启动是正常状态）。
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    base_url = payload.get("baseUrl")
    token = payload.get("token")
    api = payload.get("api")
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    if not isinstance(token, str) or not token.strip():
        return None
    if not isinstance(api, str) or not api.strip().startswith("/"):
        return None

    base_url = base_url.strip().rstrip("/")
    api_path = api.strip().strip("/")
    if not api_path:
        return None
    api = f"/{api_path}"
    if not _loopback_base_url(base_url):
        return None
    return HostInfo(
        base_url=base_url,
        token=token,
        api=api,
        plugin_version=str(payload.get("pluginVersion") or ""),
        updated_at=str(payload.get("updatedAt") or ""),
    )


def _map_error_code(status: int, server_code: str) -> str:
    if status == 401:
        return "unauthorized"
    if server_code in {"busy", "budget-blocked", "llm-unavailable", "bad-request"}:
        return server_code
    if server_code.startswith("invalid-"):
        return "bad-request"
    if status == 400:
        return "bad-request"
    if status == 409:
        return "busy"
    if status == 429:
        return "budget-blocked"
    return f"http-{status}"


def _error_from_http(status: int, raw: bytes) -> SurfCoreError:
    payload: Any = None
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        payload = None
    server_code = ""
    server_hint = ""
    if isinstance(payload, dict):
        value = payload.get("code")
        if isinstance(value, str):
            server_code = value.strip()
        hint = payload.get("hint")
        if isinstance(hint, str):
            server_hint = hint.strip()
        # /chat /proactive 这类路由失败时只返回 {ok:false,error:"..."}（没有
        # code/hint）；错误文本就是给用户看的那一句，直接拿来当 hint，免得
        # 把"今天的额度用完了"降级成通用的"请求参数不被接受"。
        error_text = payload.get("error")
        if not server_hint and isinstance(error_text, str):
            server_hint = error_text.strip()
    code = _map_error_code(status, server_code)
    hint = server_hint or _DEFAULT_HINTS.get(code) or f"SurfCore 返回了 HTTP {status}。"
    return SurfCoreError(code, status, hint)


class SurfCoreClient:
    """pet-api 客户端；每次请求都走回环，显式绕开 Windows 系统代理。"""

    def __init__(self, host_file: str | Path | None = None, timeout: float = 10.0) -> None:
        self._host_file = Path(host_file) if host_file is not None else None
        self._timeout = float(timeout)
        # 显式空 ProxyHandler：Windows 系统代理 / VPN 改不了回环请求的走向。
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._host: HostInfo | None = None
        self._host_lock = threading.Lock()

    @property
    def host_file(self) -> Path:
        return self._host_file if self._host_file is not None else default_host_file()

    def _current_host(self) -> HostInfo:
        with self._host_lock:
            if self._host is None:
                info = read_host_info(self.host_file)
                if info is None:
                    raise SurfCoreError("no-host")
                self._host = info
            return self._host

    def _invalidate_host(self) -> None:
        with self._host_lock:
            self._host = None

    def _request(
        self,
        method: str,
        route: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        host = self._current_host()
        path = route if route.startswith("/") else f"/{route}"
        url = f"{host.base_url}{host.api}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        headers = {"Accept": "application/json", "x-pet-token": host.token}
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        effective_timeout = self._timeout if timeout is None else timeout
        try:
            with self._opener.open(request, timeout=effective_timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200) or 200)
        except urllib.error.HTTPError as error:
            try:
                raw = error.read() or b""
            except OSError:
                raw = b""
            finally:
                error.close()
            # 401 常见于 DSH 重启换了令牌；清缓存让下一次请求重新读 host.json。
            self._invalidate_host()
            raise _error_from_http(int(error.code), raw) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            # 端口漂移 / 插件重启：下一次请求重新发现 host.json。
            self._invalidate_host()
            raise SurfCoreError("network") from None

        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            raise SurfCoreError("bad-response", status) from None
        if not isinstance(payload, dict):
            raise SurfCoreError("bad-response", status)
        return payload

    # ---- 只读 ---------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def persona(self) -> dict[str, Any]:
        return self._request("GET", "/persona")

    def budget(self) -> dict[str, Any]:
        return self._request("GET", "/budget")

    # ---- 写操作 -------------------------------------------------------------
    def record_usage(
        self, model: str, usage: dict[str, Any], label: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "usage": usage}
        if label is not None:
            body["label"] = label
        return self._request("POST", "/usage", body=body)

    def self_talk(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", "/self-talk", body={"context": context or {}})

    def set_focus(
        self,
        enabled: bool,
        *,
        phase: str | None = None,
        ends_at: Any = None,
        source: str = "desktop-pet",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"enabled": bool(enabled), "source": source}
        if phase is not None:
            body["phase"] = phase
        if ends_at is not None:
            body["endsAt"] = ends_at
        return self._request("POST", "/focus", body=body)

    def claim_proactive(self, source: str = "pet") -> dict[str, Any]:
        return self._request("POST", "/proactive/claim", body={"source": source})

    def chat(self, text: str, *, modality: str = "text") -> dict[str, Any]:
        return self._request("POST", "/chat", body={"text": text, "modality": modality})

    # ---- 长轮询 -------------------------------------------------------------
    def wait_events(self, since: int | None = None, timeout_s: float = 20.0) -> dict[str, Any]:
        """GET /events；``since=None`` 时只取当前水位（插件重启后不重放旧事件）。"""
        wait_ms = int(max(0.0, min(60.0, float(timeout_s))) * 1000)
        query = {"wait": str(wait_ms)}
        if since is not None:
            query["since"] = str(int(since))
        # 服务端会按 wait 挂住连接；socket 超时必须比它长，否则正常长轮询会先被本地判超时。
        request_timeout = max(self._timeout, float(timeout_s) + 5.0)
        return self._request("GET", "/events", query=query, timeout=request_timeout)


__all__ = [
    "API_PREFIX",
    "HostInfo",
    "ROUTE_PATHS",
    "SurfCoreClient",
    "SurfCoreError",
    "default_host_file",
    "read_host_info",
]
