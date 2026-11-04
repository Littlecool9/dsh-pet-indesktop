# -*- coding: utf-8 -*-
"""「DeepSeek 余额」模块运行时：自动刷新定时器、手动/静默查询与灵动岛回填。

``apply_config`` 就是原来 ``AppShell._apply_balance_timer`` 的语义；查询结果仍
走同一条 ``_show_balance_payload`` 呈现路径（气泡副标题 + 余额档位动画）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import weakref

import shiboken6
from PySide6.QtCore import QObject, QTimer, Signal

from ...persona_phrases import PhrasePicker
from ..base import ModuleHost, ModuleManifest
from . import balance as balance_mod

logger = logging.getLogger(__name__)

MODULE_ID = "balance"

_persona_pickers = weakref.WeakKeyDictionary()


def _presentation_available(host) -> bool:
    """这个宿主现在还能不能承载一次**呈现**（迟到的服务结果用）。"""
    check = getattr(host, "presentation_available", None)
    if not callable(check):
        return True
    try:
        return bool(check())
    except RuntimeError:
        return False


def _persona_picker(win):
    try:
        picker = _persona_pickers.get(win)
    except (TypeError, RuntimeError):
        picker = None
    if picker is None:
        picker = PhrasePicker()
        try:
            _persona_pickers[win] = picker
        except (TypeError, RuntimeError):
            pass
    return picker


def _persona_text(win, key: str, fallback: str, **values) -> str:
    """Render a configured persona phrase for application-level messages."""
    cfg = getattr(win, "cfg", None)
    if cfg is None:
        return fallback.format(**values)
    mode = str(cfg.get("dialogue_mode", "legacy") or "legacy")
    picker = _persona_picker(win)
    if mode == "custom":
        text = picker.custom(cfg.get("dialogue_phrases", {}), key, fallback, **values)
        return fallback.format(**values) if text is fallback else text
    text = picker.get(mode, key, fallback, **values)
    return fallback.format(**values) if text is fallback else text


def _show_balance_payload(win, payload) -> None:
    """展示余额气泡（含峰谷副标题）并按余额档位触发余额动画。"""
    if win is None or not shiboken6.isValid(win):
        return
    if isinstance(payload, dict):
        text = str(payload.get("text") or "余额信息为空")
        info = payload.get("info") or {}
    else:
        text = str(payload)
        info = {}
    cfg = getattr(win, "cfg", None)
    if cfg is not None:
        text = _persona_text(win, "balance.result", "余额情况：{text}", text=text)
    mode = str(cfg.get("balance_tier_labels_mode", "default") or "default") if cfg is not None else "default"
    custom_peak = str(cfg.get("balance_tier_label_peak", "") or "") if cfg is not None else ""
    custom_idle = str(cfg.get("balance_tier_label_idle", "") or "") if cfg is not None else ""
    peak_label, idle_label = balance_mod.resolve_tier_labels(mode, custom_peak, custom_idle)
    color_enabled = bool(cfg.get("balance_tier_color_enabled", True)) if cfg is not None else True
    if color_enabled:
        subtitle = balance_mod.deepseek_pricing_hint_html(
            peak_label=peak_label, idle_label=idle_label,
        )
    else:
        subtitle = balance_mod.deepseek_pricing_hint(
            peak_label=peak_label, idle_label=idle_label,
        )
    win.show_bubble(text, duration_ms=6000, subtitle=subtitle)
    p = balance_mod.balance_percent(info.get("total"))
    if p is not None:
        idx = balance_mod.balance_event_index(p)
        name = balance_mod.BALANCE_EVENT_NAMES[idx]
        if name and hasattr(win, "request_link_anim"):
            win.request_link_anim(name)


class _BackgroundResult(QObject):
    done = Signal(bool, object)


class _BalanceBridge(_BackgroundResult):
    def __init__(self, win, owner):
        super().__init__()
        self.win = win
        self.owner = owner
        self.done.connect(self._show)

    def _show(self, ok: bool, payload) -> None:
        if self.win is None or not shiboken6.isValid(self.win):
            return
        if not _presentation_available(self.win):
            logging.info("余额结果到达时发起桌宠已不在，取消本次呈现（缓存仍更新）")
            if ok and self.owner is not None:
                self.owner.update_island_balance(payload)
            return
        if not ok:
            self.win.show_bubble(str(payload), duration_ms=6000)
            return
        _show_balance_payload(self.win, payload)
        if self.owner is not None:
            self.owner.update_island_balance(payload)


class _QuietBalanceBridge(_BackgroundResult):
    """灵动岛卡片展开时的静默余额查询：只更新岛卡片，不冒泡、不播余额动画。"""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.done.connect(self._apply)

    def _apply(self, ok: bool, payload) -> None:
        owner = self.owner
        island = owner.island if owner is not None else None
        if island is None or not shiboken6.isValid(island):
            return
        if ok:
            owner.update_island_balance(payload, animate=False)
        else:
            island.set_balance_info(owner.island_tier_hint(), "余额查询失败")


class BalanceModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._timer = QTimer()
        self._timer.timeout.connect(self.show_balance)
        self._balance_busy = False
        self._quiet_balance_busy = False
        self._quiet_balance_last: float | None = None
        self._balance_cache = None
        self._balance_bridge = None
        self._balance_cache_path = None
        self._island = None

    # ---- PetModule ---------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        config = self.config
        if config is not None:
            self._balance_cache_path = config.dir / 'balance_cache.json'
        self._attach_island()

    def apply_config(self, config) -> None:
        self._timer.stop()
        minutes = max(0, int(config.get("balance_refresh_minutes", 0) or 0))
        if minutes:
            self._timer.start(minutes * 60000)
        self._attach_island()

    def stop(self) -> None:
        self._timer.stop()
        self._balance_busy = False
        self._quiet_balance_busy = False
        self._island = None
        self._host = None

    # ---- 宿主面 ------------------------------------------------------------
    @property
    def _shell(self):
        return getattr(self._host, "shell", None)

    @property
    def config(self):
        host = self._host
        cfg = getattr(host, "config", None)
        if cfg is not None:
            return cfg
        return getattr(self._shell, "config", None)

    @property
    def island(self):
        return getattr(self._shell, "island", None)

    def _attach_island(self) -> None:
        island = self.island
        if island is None or island is self._island:
            return
        self._island = island
        try:
            island.card_expanded.connect(self.refresh_island)
        except Exception:
            logger.debug("余额模块挂接灵动岛失败", exc_info=True)

    def island_tier_hint(self) -> str:
        """灵动岛余额峰谷提示文案（与 update_island_balance / 静默查询共用）。"""
        config = self.config
        peak_label, idle_label = balance_mod.resolve_tier_labels(
            str(config.get("balance_tier_labels_mode", "default") or "default"),
            str(config.get("balance_tier_label_peak", "") or ""),
            str(config.get("balance_tier_label_idle", "") or ""),
        )
        return balance_mod.deepseek_pricing_hint(
            peak_label=peak_label, idle_label=idle_label,
        )

    def update_island_balance(self, payload, *, animate: bool = True) -> None:
        """把余额文本/峰谷提示同步给灵动岛（若有）。"""
        island = self.island
        if island is None:
            return
        text = "余额 --"
        if isinstance(payload, dict):
            text = str(payload.get("text") or "余额 --")
        island.set_balance_info(self.island_tier_hint(), text)
        if animate:
            island.notify_event("balance")

    def refresh_island(self, *, force: bool = False) -> None:
        """灵动岛卡片展开时的静默余额刷新：不冒泡、不播动画，只更新岛卡片。"""
        island = self.island
        if island is None or self._quiet_balance_busy:
            return
        shell = self._shell
        if not bool(getattr(shell, "enable_chat", True)):
            island.set_balance_info(self.island_tier_hint(), "此版本无余额查询")
            return
        config = self.config
        now = time.monotonic()
        settings = config.chat_settings()
        provider = settings.active_config
        provider.api_key = config.resolve_api_key(provider)
        if not provider.api_key:
            island.set_balance_info(
                self.island_tier_hint(), "未配置 API Key（设置 → 聊天）")
            return
        key_digest = hashlib.sha256(str(provider.api_key or '').encode()).hexdigest()[:12]
        provider_key = '|'.join([
            str(getattr(provider, 'id', '') or ''),
            str(provider.base_url or ''),
            key_digest,
        ])
        if self._balance_cache is not None and now - self._balance_cache[0] < 30.0 \
                and self._balance_cache[2] == provider_key:
            self.update_island_balance(self._balance_cache[1], animate=False)
            return
        file_payload = self._read_balance_file_cache(provider_key)
        if file_payload is not None:
            self._balance_cache = (now, file_payload, provider_key)
            self.update_island_balance(file_payload, animate=False)
            return
        last = self._quiet_balance_last
        if not force and last is not None and now - last < 60.0:
            island.set_balance_info(self.island_tier_hint(), "刚刚查询过，稍后自动更新")
            return
        self._quiet_balance_last = now
        island.set_balance_info(self.island_tier_hint(), "查询中…")
        bridge = _QuietBalanceBridge(owner=self)
        self._balance_bridge = bridge
        self._quiet_balance_busy = True
        try:
            threading.Thread(
                target=self._balance_worker,
                args=(bridge, provider.base_url, provider.api_key, provider.verify_ssl, provider_key),
                kwargs={"quiet": True},
                daemon=True, name='pet-balance-quiet',
            ).start()
        except Exception as exc:  # noqa: BLE001 - 启动失败也必须释放忙状态
            self._quiet_balance_busy = False
            QTimer.singleShot(0, lambda message=str(exc): bridge.done.emit(False, message))

    # ---- 余额 --------------------------------------------------------------
    def show_balance(self, parent=None) -> None:
        win = parent
        if win is None or not callable(getattr(win, "show_bubble", None)):
            win = getattr(self._shell, "win", None)
        if win is None or self._balance_busy or not win.isVisible():
            return
        now = time.monotonic()
        config = self.config
        settings = config.chat_settings()
        provider = settings.active_config
        provider.api_key = config.resolve_api_key(provider)
        key_digest = hashlib.sha256(str(provider.api_key or '').encode()).hexdigest()[:12]
        provider_key = '|'.join([
            str(getattr(provider, 'id', '') or ''),
            str(provider.base_url or ''),
            key_digest,
        ])
        if self._balance_cache is not None and now - self._balance_cache[0] < 30.0 \
                and self._balance_cache[2] == provider_key:
            self.update_island_balance(self._balance_cache[1])
            _show_balance_payload(win, self._balance_cache[1])
            return
        file_payload = self._read_balance_file_cache(provider_key)
        if file_payload is not None:
            self._balance_cache = (now, file_payload, provider_key)
            self.update_island_balance(file_payload)
            _show_balance_payload(win, file_payload)
            return
        self._balance_busy = True
        QTimer.singleShot(0, lambda: win.show_bubble('让我看看余额…', duration_ms=6000))
        bridge = _BalanceBridge(win, owner=self)
        self._balance_bridge = bridge
        try:
            threading.Thread(
                target=self._balance_worker,
                args=(bridge, provider.base_url, provider.api_key, provider.verify_ssl, provider_key),
                daemon=True, name='pet-balance',
            ).start()
        except Exception as exc:  # noqa: BLE001 - 启动失败也必须释放忙状态
            self._balance_busy = False
            error_message = f'余额查询失败：{exc}'
            QTimer.singleShot(0, lambda message=error_message: bridge.done.emit(False, message))

    def _balance_worker(self, bridge, base_url: str, api_key: str, verify_ssl: bool,
                        provider_key: str = '', *, quiet: bool = False) -> None:
        try:
            info = balance_mod.fetch_balance(base_url, api_key, verify_ssl=verify_ssl)
            text = balance_mod.format_balance(info)
            payload = {"text": text, "info": info}
            self._balance_cache = (time.monotonic(), payload, provider_key)
            self._write_balance_file_cache(payload, provider_key)
            bridge.done.emit(True, payload)
        except Exception as exc:  # noqa: BLE001 - 任何失败走气泡提示
            bridge.done.emit(False, f'余额查询失败：{exc}')
        finally:
            if quiet:
                self._quiet_balance_busy = False
            else:
                self._balance_busy = False

    def _read_balance_file_cache(self, provider_key: str = '') -> dict | None:
        """读取跨实例共享的余额缓存（30s 内有效，且必须是同一 provider 的缓存）。"""
        path = self._balance_cache_path
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                return None
            if str(data.get('provider', '') or '') != provider_key:
                return None
            if time.time() - float(data.get('ts', 0) or 0) >= 30.0:
                return None
            text = str(data.get('text', '') or '')
            if not text:
                return None
            info = data.get('info')
            return {
                'text': text,
                'info': info if isinstance(info, dict) else {},
            }
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _write_balance_file_cache(self, payload: dict, provider_key: str = '') -> None:
        """写入跨实例共享的余额缓存（原子替换，绑定 provider）。"""
        path = self._balance_cache_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f'.{os.getpid()}.tmp')
            tmp.write_text(
                json.dumps({
                    'ts': time.time(),
                    'text': str(payload.get('text') or ''),
                    'info': payload.get('info') or {},
                    'provider': provider_key,
                }, ensure_ascii=False),
                encoding='utf-8',
            )
            tmp.replace(path)
        except OSError:
            pass


def create(manifest: ModuleManifest) -> BalanceModule:
    return BalanceModule(manifest)


__all__ = ["BalanceModule", "create"]
