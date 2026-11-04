# -*- coding: utf-8 -*-
"""桌宠直连模型与 SurfCore 之间的核心接缝（无 Qt 依赖）。

本模块只做四件事，全部通过宿主提供的 ``surfcore`` 服务完成，绝不 import
``pet.modules.surfcore``：

- **人格卡**：在线时经 ``service.submit('persona')`` 在后台线程读取，缓存到应用
  配置目录；离线/读取失败时沿用磁盘缓存。``persona_card()`` 总是立即返回（可能
  是 ``None``），绝不阻塞 GUI。
- **额度闸门**：后台缓存 ``budget``（最多 60 秒一次，记账后立即刷新）。
  ``budget_gate(label)`` 只读缓存：``blocked=True`` 返回 SurfCore 给的提示；
  离线、服务缺失或 ``available=False`` 一律放行（保持今天的直连行为）。
- **用量上报**：``report_usage(model, usage, label)`` 只把模型名、数字型 token
  用量和标签交给 SurfCore；截图/聊天文本绝不会出现在这里。
- **主动说话额度**：``claim_proactive(source, on_done)`` 在后台领取，完成回调在
  GUI/宿主线程执行；离线时返回 ``False``，由调用方沿用本地限流器。

安装入口由 ``AppShell._start_modules`` 在模块启动后调用 :func:`bind`；测试可
直接 :func:`bind_service` 注入假服务。所有网络调用都走 ``service.submit`` 的
单工作线程，本模块自身不创建线程、也不碰 Qt。
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

log = logging.getLogger(__name__)

PERSONA_TTL_SECONDS = 600.0
BUDGET_TTL_SECONDS = 60.0
PERSONA_FILE_NAME = "surfcore_persona.json"
DEFAULT_BUDGET_MESSAGE = "今天的额度用完了，明天再试或调高额度。"


def _persona_text(result: Any) -> str | None:
    """从 ``GET /persona`` 的响应里取人格文本；形状不对返回 ``None``。"""
    if not isinstance(result, Mapping) or result.get("ok") is False:
        return None
    text = result.get("persona")
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None


def _clean_usage(usage: Any) -> dict[str, int | float] | None:
    """只保留数字型 token 字段。

    这是隐私边界：``/usage`` 只需要用量数字，绝不允许把消息文本、图片
    base64、窗口标题等夹带字段带过去（服务端也按数字校验）。
    """
    if not isinstance(usage, Mapping):
        return None
    cleaned: dict[str, int | float] = {}
    for key, value in usage.items():
        if not isinstance(key, str) or not key:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if value < 0:
            continue
        cleaned[key] = int(value) if float(value).is_integer() else float(value)
    return cleaned or None


def _load_cached_persona(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    text = payload.get("persona")
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None


def _write_cached_persona(path: Path | None, result: Mapping[str, Any],
                          text: str) -> None:
    """原子写入人格缓存；失败只记错误类型，不影响本次会话。"""
    if path is None:
        return
    payload = {
        "persona": text,
        "hash": result.get("hash") if isinstance(result.get("hash"), str) else "",
        "role": result.get("role") if isinstance(result.get("role"), Mapping) else {},
        "saved_at": time.time(),
    }
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        log.debug("SurfCore 人格卡缓存写入失败：%s", type(error).__name__)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


class SurfCoreLink:
    """一个 ``surfcore`` 服务的直连接缝；线程安全、所有网络都异步。"""

    def __init__(self, service: Any = None, cache_dir: str | Path | None = None,
                 *, now: Callable[[], float] = time.monotonic) -> None:
        self._service = service
        self._cache_path = (
            Path(cache_dir) / PERSONA_FILE_NAME if cache_dir is not None else None
        )
        self._now = now
        self._lock = threading.Lock()
        self._persona = _load_cached_persona(self._cache_path)
        self._persona_at = 0.0
        self._persona_busy = False
        self._budget: dict[str, Any] | None = None
        self._budget_at = 0.0
        self._budget_busy = False

    # ---- 生命周期 -----------------------------------------------------------
    @property
    def service(self) -> Any:
        return self._service

    @property
    def cache_path(self) -> Path | None:
        return self._cache_path

    def online(self) -> bool:
        service = self._service
        return bool(service is not None and getattr(service, "online", False))

    def warm(self) -> None:
        """启动/重连后的首次拉取（离线时什么都不做，磁盘缓存已经就位）。"""
        if not self.online():
            return
        self.refresh_persona()
        self.refresh_budget()

    # ---- 后台调用 -----------------------------------------------------------
    def _submit(self, fn_name: str, *args: Any,
                on_done: Callable[[Any, Exception | None], None] | None = None,
                **kwargs: Any) -> bool:
        service = self._service
        if service is None or not getattr(service, "online", False):
            return False
        submit = getattr(service, "submit", None)
        if not callable(submit):
            return False
        try:
            return bool(submit(fn_name, *args, on_done=on_done, **kwargs))
        except Exception as error:  # 服务停止等边界：按"没发出去"处理
            log.debug("SurfCore 调用 %s 失败：%s", fn_name, type(error).__name__)
            return False

    # ---- 人格卡 -------------------------------------------------------------
    def _refresh_persona_if_due(self) -> None:
        if not self.online():
            return
        with self._lock:
            due = (not self._persona_busy) and (
                self._persona_at <= 0.0
                or self._now() - self._persona_at >= PERSONA_TTL_SECONDS
            )
        if due:
            self.refresh_persona()

    def refresh_persona(self, *, force: bool = False) -> bool:
        """在后台读取 ``/persona``；最多每 10 分钟一次（``force`` 忽略节流）。"""
        if not self.online():
            return False
        with self._lock:
            if self._persona_busy:
                return False
            now = self._now()
            if not force and self._persona_at > 0.0 \
                    and now - self._persona_at < PERSONA_TTL_SECONDS:
                return False
            self._persona_busy = True
            self._persona_at = now

        def done(result: Any, error: Exception | None) -> None:
            with self._lock:
                self._persona_busy = False
            if error is not None:
                log.debug("SurfCore 人格卡读取失败：%s",
                          getattr(error, "code", type(error).__name__))
                return
            text = _persona_text(result)
            if text is None:
                log.debug("SurfCore 人格卡响应缺少 persona")
                return
            with self._lock:
                self._persona = text
            _write_cached_persona(self._cache_path, result, text)

        if not self._submit("persona", on_done=done):
            with self._lock:
                self._persona_busy = False
                self._persona_at = 0.0
            return False
        return True

    def persona_card(self) -> str | None:
        self._refresh_persona_if_due()
        with self._lock:
            return self._persona

    def persona_or(self, local: str | None) -> str | None:
        return self.persona_card() or local

    # ---- 额度闸门 -----------------------------------------------------------
    def _refresh_budget_if_due(self) -> None:
        if not self.online():
            return
        with self._lock:
            due = (not self._budget_busy) and (
                self._budget_at <= 0.0
                or self._now() - self._budget_at >= BUDGET_TTL_SECONDS
            )
        if due:
            self.refresh_budget()

    def refresh_budget(self, *, force: bool = False) -> bool:
        """后台刷新 ``/budget``；默认最多 60 秒一次（记账后强制刷新）。"""
        if not self.online():
            return False
        with self._lock:
            if self._budget_busy:
                return False
            now = self._now()
            if not force and self._budget_at > 0.0 \
                    and now - self._budget_at < BUDGET_TTL_SECONDS:
                return False
            self._budget_busy = True
            self._budget_at = now

        def done(result: Any, error: Exception | None) -> None:
            with self._lock:
                self._budget_busy = False
            if error is not None:
                log.debug("SurfCore 额度读取失败：%s",
                          getattr(error, "code", type(error).__name__))
                return
            if not isinstance(result, Mapping):
                return
            if result.get("available") is False:
                with self._lock:
                    self._budget = None
                return
            with self._lock:
                self._budget = dict(result)

        if not self._submit("budget", on_done=done):
            with self._lock:
                self._budget_busy = False
                self._budget_at = 0.0
            return False
        return True

    def budget_gate(self, label: str = "") -> tuple[bool, str]:
        """``(allowed, message)``：只看缓存，绝不阻塞调用方。"""
        self._refresh_budget_if_due()
        with self._lock:
            budget = dict(self._budget) if self._budget is not None else None
        if budget is None or budget.get("available") is False:
            return True, ""
        if not bool(budget.get("blocked")):
            return True, ""
        message = str(budget.get("message") or "").strip() or DEFAULT_BUDGET_MESSAGE
        if label:
            log.info("SurfCore 额度已阻止直连调用（%s）：%s", label, message)
        return False, message

    # ---- 用量上报 -----------------------------------------------------------
    def report_usage(self, model: str, usage: Any, label: str) -> bool:
        cleaned = _clean_usage(usage)
        if cleaned is None:
            return False
        model_text = str(model or "").strip()[:100]
        label_text = str(label or "").strip()[:40]

        def done(result: Any, error: Exception | None) -> None:
            if error is not None:
                log.debug("SurfCore 用量上报失败：%s",
                          getattr(error, "code", type(error).__name__))
                return
            # 记账后额度缓存可能已经变了：立即刷新（允许越过 60 秒节流）。
            self.refresh_budget(force=True)

        return self._submit(
            "record_usage", model_text, cleaned, label=label_text, on_done=done,
        )

    # ---- 主动说话额度 -------------------------------------------------------
    def claim_proactive(self, source: str,
                        on_done: Callable[[bool, str], None]) -> bool:
        """领取一次主动说话额度；在线且已排队返回 ``True``。

        ``on_done(granted, reason)`` 在宿主线程执行：只有明确
        ``granted=True`` 才放行，请求失败/形状不对都按拒绝处理（在线时绝不
        悄悄退回本地限流器）。
        """
        if not self.online():
            return False

        def done(result: Any, error: Exception | None) -> None:
            granted = False
            reason = ""
            if error is not None:
                reason = f"error:{getattr(error, 'code', type(error).__name__)}"
            elif not isinstance(result, Mapping):
                reason = "bad-response"
            elif result.get("ok") is False:
                reason = str(result.get("reason") or result.get("code") or "denied")
            elif result.get("granted") is True:
                granted = True
            else:
                reason = str(result.get("reason") or "denied")
            try:
                on_done(granted, reason)
            except Exception:
                log.warning("SurfCore 主动说话额度回调异常", exc_info=True)

        return self._submit("claim_proactive", str(source), on_done=done)


# ---- 模块级接缝（应用/测试只碰这几个函数）-----------------------------------

_LINK: SurfCoreLink | None = None
_LABEL_LOCAL = threading.local()


@contextmanager
def usage_label(label: str) -> Iterator[None]:
    """给当前线程的用量上报打一个标签（例如 ``桌宠主动识屏``）。

    视觉请求在后台线程里执行，调用点用上下文而不是给 ``vision`` 的公开签名
    加参数——已有测试替身按旧签名打桩，不该被迫跟着改。
    """
    previous = getattr(_LABEL_LOCAL, "value", None)
    _LABEL_LOCAL.value = str(label or "")
    try:
        yield
    finally:
        if previous is None:
            try:
                del _LABEL_LOCAL.value
            except AttributeError:
                pass
        else:
            _LABEL_LOCAL.value = previous


def current_usage_label(default: str = "桌宠识屏") -> str:
    return getattr(_LABEL_LOCAL, "value", None) or default


def current() -> SurfCoreLink | None:
    return _LINK


def bind_service(service: Any, cache_dir: str | Path | None = None) -> SurfCoreLink:
    """注入服务并立即预热（离线时只加载磁盘人格缓存）。"""
    global _LINK
    link = SurfCoreLink(service, cache_dir)
    _LINK = link
    link.warm()
    return link


def bind(shell: Any, cache_dir: str | Path | None = None) -> SurfCoreLink:
    """从应用壳的模块宿主取 ``surfcore`` 服务（缺失也安装，保留磁盘缓存）。"""
    from .module_host import module_service

    return bind_service(module_service(shell, "surfcore", None), cache_dir)


def reset() -> None:
    global _LINK
    _LINK = None


def persona_card() -> str | None:
    link = _LINK
    return link.persona_card() if link is not None else None


def persona_or(local: str | None) -> str | None:
    return persona_card() or local


def budget_gate(label: str = "") -> tuple[bool, str]:
    link = _LINK
    return link.budget_gate(label) if link is not None else (True, "")


def report_usage(model: str, usage: Any, label: str) -> bool:
    link = _LINK
    return link.report_usage(model, usage, label) if link is not None else False


def claim_proactive(source: str, on_done: Callable[[bool, str], None]) -> bool:
    link = _LINK
    return link.claim_proactive(source, on_done) if link is not None else False


__all__ = [
    "BUDGET_TTL_SECONDS",
    "DEFAULT_BUDGET_MESSAGE",
    "PERSONA_FILE_NAME",
    "PERSONA_TTL_SECONDS",
    "SurfCoreLink",
    "bind",
    "bind_service",
    "budget_gate",
    "claim_proactive",
    "current",
    "current_usage_label",
    "persona_card",
    "persona_or",
    "report_usage",
    "reset",
    "usage_label",
]
