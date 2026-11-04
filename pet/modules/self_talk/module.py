# -*- coding: utf-8 -*-
"""「自言自语」模块运行时：周期调度、台词选择与每小时一次 SurfCore 生成。

迁移边界：

- 调度与选择在本模块（``handle_timeout`` / ``schedule`` / ``selection``）；
- 呈现仍走宿主既有气泡路径（``host.show_self_talk``）：可见性、设置页抑制、
  专注模式、提醒让路、配图预热缓存等门禁都在应用侧，观感不变；
- 需要 SurfCore 时只经宿主的服务表（``host.get("surfcore")``），绝不 import
  ``pet.modules.surfcore``，也绝不在 GUI 线程直接调客户端：``service.submit``
  把 HTTP 放到工作线程，``on_done`` 经宿主事件总线回到 GUI 线程。

每小时最多一条生成台词：以**最近一次成功**的生成时刻为基准（常量 3600 秒）。
失败（busy / budget-blocked / llm-unavailable / 网络 / 离线 / 服务缺失 / 排队失败）
一律回退本地预设台词；关闭自言自语就不会向 SurfCore 发任何请求。
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from PySide6.QtCore import QTimer

from ...asset_paths import resolve_self_talk_image_dir
from ...config import (
    DEFAULT_SELF_TALK_DURATION_SECONDS,
    DEFAULT_SELF_TALK_MAX_INTERVAL,
    DEFAULT_SELF_TALK_MIN_INTERVAL,
)
from ...speech_bubble_text import list_self_talk_images
from ..base import ModuleHost, ModuleManifest
from .selection import (
    pick_self_talk_choice,
    read_self_talk_texts,
    self_talk_image_chance,
)

logger = logging.getLogger(__name__)

MODULE_ID = "self_talk"

#: 生成台词的世界间隔（秒）；从**上一次成功**生成起算。
SURFCORE_INTERVAL_SECONDS = 3600.0

#: SurfCore 只需要一个非个人的空闲原因；不要把宠物设置或用户内容塞进上下文。
SURFCORE_CONTEXT = {"reason": "idle"}


@dataclass(frozen=True)
class SelfTalkSettings:
    """一次配置快照（全部按旧核心口径清洗/钳位）。"""

    enabled: bool
    texts: tuple[str, ...]
    images: tuple[Path, ...]
    duration_s: float
    image_scale: float
    image_chance: int
    min_interval: float
    max_interval: float


def _config_get(cfg: Any, key: str, default: Any) -> Any:
    getter = getattr(cfg, "get", None)
    if not callable(getter):
        return default
    try:
        return getter(key, default)
    except Exception:
        return default


def _clamped_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float(default)
    if number != number:  # NaN
        number = float(default)
    return max(low, min(high, number))


def load_settings(cfg: Any) -> SelfTalkSettings:
    """从（每宠）配置读出调度/选择所需字段。"""
    enabled = bool(_config_get(cfg, "self_talk_enabled", False))
    texts = tuple(read_self_talk_texts(_config_get(cfg, "self_talk_texts", None)))
    image_dir = str(_config_get(cfg, "self_talk_image_dir", "") or "")
    images = tuple(list_self_talk_images(resolve_self_talk_image_dir(image_dir)))
    duration_s = _clamped_float(
        _config_get(cfg, "self_talk_duration_seconds",
                    DEFAULT_SELF_TALK_DURATION_SECONDS),
        DEFAULT_SELF_TALK_DURATION_SECONDS, 1.0, 300.0)
    image_scale = _clamped_float(
        _config_get(cfg, "self_talk_image_scale", 100.0), 100.0, 50.0, 300.0) / 100.0
    image_chance = self_talk_image_chance(cfg)
    minimum = max(5.0, _clamped_float(
        _config_get(cfg, "self_talk_min_interval", DEFAULT_SELF_TALK_MIN_INTERVAL),
        DEFAULT_SELF_TALK_MIN_INTERVAL, 0.0, 86400.0))
    maximum = max(minimum, _clamped_float(
        _config_get(cfg, "self_talk_max_interval", DEFAULT_SELF_TALK_MAX_INTERVAL),
        DEFAULT_SELF_TALK_MAX_INTERVAL, 0.0, 86400.0))
    return SelfTalkSettings(
        enabled=enabled,
        texts=texts,
        images=images,
        duration_s=duration_s,
        image_scale=image_scale,
        image_chance=image_chance,
        min_interval=minimum,
        max_interval=maximum,
    )


class SelfTalkModule:
    """单实例运行时：一个单发定时器，冒泡后按显示时长重排下一次。"""

    def __init__(
        self,
        manifest: ModuleManifest | None = None,
        *,
        clock: Callable[[], float] | None = None,
        timer: QTimer | None = None,
    ) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._config: Any = None
        self._settings: SelfTalkSettings | None = None
        self._clock = clock or (lambda: time.monotonic())
        self._timer = timer or QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.handle_timeout)
        self._visible = True
        self._started = False
        self._request_in_flight = False
        self._last_surfcore_at: float | None = None
        self._last_text: str | None = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        self._started = True
        if self._settings is None:
            self._reload()
        self._reschedule()

    def apply_config(self, config: Any) -> None:
        self._config = config
        self._reload()
        self._reschedule()

    def stop(self) -> None:
        self._timer.stop()
        self._started = False
        self._host = None
        self._config = None
        self._settings = None
        self._visible = True
        self._request_in_flight = False

    # ---- 应用侧能力 ---------------------------------------------------------
    def set_visible(self, visible: bool) -> None:
        """桌宠隐藏时停表；恢复显示时重新排一次（与旧壳显隐对称语义一致）。"""
        self._visible = bool(visible)
        if not self._started:
            return
        if self._visible:
            self._reschedule()
        else:
            self._timer.stop()

    # ---- 调度 ---------------------------------------------------------------
    @property
    def timer(self) -> QTimer:
        return self._timer

    @property
    def settings(self) -> SelfTalkSettings | None:
        return self._settings

    @property
    def last_text(self) -> str | None:
        return self._last_text

    @property
    def last_surfcore_at(self) -> float | None:
        return self._last_surfcore_at

    @property
    def request_in_flight(self) -> bool:
        return self._request_in_flight

    def _pet_config(self) -> Any:
        host = self._host
        getter = getattr(host, "pet_config", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                logger.debug("读取自言自语每宠配置失败", exc_info=True)
        return getattr(host, "config", None) or self._config

    def _reload(self) -> None:
        settings = load_settings(self._pet_config())
        self._settings = settings
        host = self._host
        prepare = getattr(host, "prepare_self_talk", None)
        if callable(prepare):
            try:
                prepare(
                    images=[str(path) for path in settings.images],
                    image_scale=settings.image_scale,
                )
            except Exception:
                logger.debug("自言自语配图预热准备失败", exc_info=True)

    def _reschedule(self) -> None:
        if not self._started or not self._visible:
            self._timer.stop()
            return
        self.schedule()

    def schedule(self, *, after_display: bool = False) -> None:
        """排下一次自言自语；开关关闭/没有内容时停表。"""
        self._timer.stop()
        settings = self._settings
        if settings is None or not settings.enabled or not (settings.texts or settings.images):
            return
        delay = random.uniform(settings.min_interval, settings.max_interval)
        if after_display:
            delay += settings.duration_s
        self._timer.start(max(1000, int(round(delay * 1000))))

    def handle_timeout(self) -> None:
        """到点：先看门禁，再决定走 SurfCore 还是本地预设。"""
        settings = self._settings
        if (settings is None or not settings.enabled
                or (not settings.texts and not settings.images)):
            self.schedule()
            return
        if not self._host_ready():
            self.schedule()
            return

        service = self._surfcore_service()
        if service is not None and bool(getattr(service, "online", False)) and self._surfcore_due():
            if self._submit_surfcore(service):
                return
            # 排队失败（服务已停/执行器关闭）：回退本地台词。
        displayed = self._show_local()
        self.schedule(after_display=displayed)

    def _on_timeout(self) -> None:
        """``QTimer``/旧 host 形调用面的别名。"""
        self.handle_timeout()

    # ---- SurfCore -----------------------------------------------------------
    def _surfcore_service(self) -> Any:
        host = self._host
        getter = getattr(host, "get", None)
        if not callable(getter):
            return None
        try:
            return getter("surfcore", None)
        except Exception:
            logger.debug("读取 surfcore 服务失败", exc_info=True)
            return None

    def _surfcore_due(self) -> bool:
        last = self._last_surfcore_at
        return last is None or (self._clock() - last) >= SURFCORE_INTERVAL_SECONDS

    def _submit_surfcore(self, service: Any) -> bool:
        submit = getattr(service, "submit", None)
        if not callable(submit):
            return False
        self._request_in_flight = True
        try:
            accepted = bool(submit(
                "self_talk", dict(SURFCORE_CONTEXT), on_done=self._on_surfcore_done))
        except Exception:
            logger.debug("自言自语 SurfCore 请求提交失败", exc_info=True)
            accepted = False
        if not accepted:
            self._request_in_flight = False
        return accepted

    def _on_surfcore_done(self, result: Any, error: Exception | None) -> None:
        """宿主线程回调：成功用生成台词，任何失败都回退本地预设。"""
        self._request_in_flight = False
        settings = self._settings
        if not self._started or settings is None or not settings.enabled:
            return

        displayed = False
        text = _result_text(result if error is None else None)
        if text is not None:
            # “最后一次成功”按 API 成功计；显示门禁失败也不在同一小时重复生成。
            self._last_surfcore_at = self._clock()
            displayed = self._show_text(text)
        if not displayed:
            displayed = self._show_local()
        self.schedule(after_display=displayed)

    # ---- 呈现 ---------------------------------------------------------------
    def _host_ready(self) -> bool:
        host = self._host
        checker = getattr(host, "self_talk_ready", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            logger.debug("自言自语门禁查询失败", exc_info=True)
            return False

    def _show_local(self) -> bool:
        settings = self._settings
        if settings is None:
            return False
        picked = pick_self_talk_choice(
            settings.texts, settings.images, settings.image_chance)
        if picked is None:
            return False
        kind, value = picked
        if kind == "image":
            self._last_text = None
            if self._show_image(str(value)):
                return True
            if not settings.texts:
                return False
            self._last_text = settings.texts[0]
            return self._show_text(settings.texts[0])
        self._last_text = str(value)
        return self._show_text(str(value))

    def _show_text(self, text: str) -> bool:
        settings = self._settings
        duration_ms = int(round((settings.duration_s if settings else 3.2) * 1000))
        return self._present(text=text, duration_ms=duration_ms)

    def _show_image(self, image: str) -> bool:
        settings = self._settings
        duration_ms = int(round((settings.duration_s if settings else 3.2) * 1000))
        return self._present(
            image=image,
            duration_ms=duration_ms,
            image_scale=(settings.image_scale if settings else 1.0),
        )

    def _present(
        self,
        *,
        text: str | None = None,
        image: str | None = None,
        duration_ms: int = 3200,
        image_scale: float | None = None,
    ) -> bool:
        host = self._host
        if host is None:
            return False
        presenter = getattr(host, "show_self_talk", None)
        if callable(presenter):
            try:
                return bool(presenter(
                    text=text,
                    image=image,
                    duration_ms=duration_ms,
                    image_scale=image_scale,
                ))
            except TypeError:
                # 兼容更小的宿主面：只给约定里的三个位置参数。
                try:
                    return bool(presenter(text, image, duration_ms))
                except Exception:
                    logger.debug("自言自语呈现失败", exc_info=True)
                    return False
            except Exception:
                logger.debug("自言自语呈现失败", exc_info=True)
                return False
        if text is None:
            return False
        fallback = getattr(host, "show_bubble", None)
        if not callable(fallback):
            return False
        try:
            return bool(fallback(str(text), duration_ms))
        except Exception:
            logger.debug("自言自语回退气泡失败", exc_info=True)
            return False


def _result_text(result: Any) -> str | None:
    """从 ``POST /self-talk`` 的成功响应里取台词（pet-chat 返回 ``{ok, text, role}``）。"""
    if not isinstance(result, Mapping):
        return None
    if result.get("ok") is False:
        return None
    text = result.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None


def create(manifest: ModuleManifest) -> SelfTalkModule:
    return SelfTalkModule(manifest)


__all__ = [
    "MODULE_ID",
    "SURFCORE_CONTEXT",
    "SURFCORE_INTERVAL_SECONDS",
    "SelfTalkModule",
    "SelfTalkSettings",
    "create",
    "load_settings",
]
