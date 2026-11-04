# -*- coding: utf-8 -*-
"""「全局快捷键」模块运行时：系统级热键注册 + 按动作 id 分发。

动作表在 Qt-free 的核心模块 ``pet.hotkey_actions``（设置页也读同一份）；这里只
负责注册与分发。分发目标沿用宿主既有的入口，不复制行为：

- ``open_chat`` → ``shell.instance.open_chat``，否则 ``overlay.open_quick_chat``
- ``look_screen`` → ``overlay.look_at_screen``，否则 ``instance.win.look_at_screen``
- ``screen_capture`` → ``overlay.on_screen_capture``，否则 ``instance.win.on_screen_capture``

动作的目标不可用（目标模块没登记 / 没启动，或对应的宿主入口不存在）时，该热键
**不注册**并记录原因——绝不能留下「绑上了却永远不触发」的假绑定。
"""
from __future__ import annotations

import logging
from typing import Callable

from ... import hotkey_actions
from ..base import ModuleHost, ModuleManifest
from .hotkeys import GlobalHotkeyService

logger = logging.getLogger(__name__)

#: 动作 → 目标模块 id。``None`` = 目标就是宿主既有入口（不是模块）。
#: 现阶段三个动作都落在宿主入口上；表留在这里，后续把 Chat 等迁成模块时只需
#: 填 id，可用性判定会走 ``running_module``。
ACTION_TARGET_MODULES: dict[str, str | None] = {
    action: None for action in hotkey_actions.ACTIONS
}


class HotkeysModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._service: GlobalHotkeyService | None = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        try:
            service = GlobalHotkeyService(getattr(host, "app", None))
            self._service = service
            service.install()
        except Exception:
            # 装不上时保留诊断入口（右键菜单仍可用），绝不阻断启动。
            logger.exception("安装全局快捷键失败（右键菜单仍可用）")

    def apply_config(self, config) -> None:
        service = self._service
        if service is None or not getattr(service, "installed", False):
            return
        bindings: dict[str, str] = {}
        callbacks: dict[str, Callable[[], None]] = {}
        for action, key in hotkey_actions.ACTIONS.items():
            text = str(config.get(key) or "").strip()
            if not text:
                continue
            callback, reason = self._resolve(action)
            if callback is None:
                logger.warning(
                    "全局快捷键：%s（%s）的目标不可用，不注册：%s",
                    hotkey_actions.ACTION_LABELS.get(action, action),
                    action,
                    reason or "目标不可用",
                )
                continue
            bindings[action] = text
            callbacks[action] = callback
        try:
            failures = service.apply(bindings, callbacks)
        except Exception:
            logger.exception("注册全局快捷键失败（右键菜单仍可用）")
            return
        for action, text, reason in failures:
            logger.warning("全局快捷键未生效：%s（%s）%s", action, text, reason)

    def stop(self) -> None:
        service = self._service
        self._service = None
        self._host = None
        if service is None:
            return
        try:
            service.uninstall()
        except Exception:
            logger.debug("注销全局快捷键失败", exc_info=True)

    # ---- 分发目标 -----------------------------------------------------------
    def _resolve(self, action: str) -> tuple[Callable[[], None] | None, str]:
        """返回 ``(回调, 不可用原因)``；不可用时回调为 None。"""
        target_module = ACTION_TARGET_MODULES.get(action)
        if target_module:
            reason = self._module_unavailable(target_module)
            if reason:
                return None, reason
        shell = self._shell()
        if shell is None:
            return None, "宿主未就绪"
        if action == "open_chat":
            return self._resolve_open_chat(shell)
        if action == "look_screen":
            return self._resolve_look_screen(shell)
        if action == "screen_capture":
            return self._resolve_screen_capture(shell)
        return None, "未知动作"

    def _module_unavailable(self, module_id: str) -> str:
        getter = getattr(self._host, "running_module", None)
        if not callable(getter):
            getter = getattr(self._shell(), "running_module", None)
        if not callable(getter):
            return f"目标模块 {module_id} 未运行"
        try:
            if getter(module_id) is not None:
                return ""
        except Exception:
            logger.debug("查询模块 %s 运行状态失败", module_id, exc_info=True)
        reason_getter = getattr(self._host, "module_unavailable_reason", None)
        if not callable(reason_getter):
            reason_getter = getattr(self._shell(), "module_unavailable_reason", None)
        reason = ""
        if callable(reason_getter):
            try:
                reason = str(reason_getter(module_id) or "")
            except Exception:
                logger.debug("查询模块 %s 不可用原因失败", module_id, exc_info=True)
        return reason or f"目标模块 {module_id} 未运行"

    def _shell(self):
        return getattr(self._host, "shell", None)

    @staticmethod
    def _resolve_open_chat(shell):
        opener = getattr(getattr(shell, "instance", None), "open_chat", None)
        if callable(opener):
            return opener, ""
        overlay = getattr(shell, "_overlay_shell", None)
        quick = getattr(overlay, "open_quick_chat", None)
        if callable(quick):
            return quick, ""
        return None, "AI 对话入口不可用"

    @staticmethod
    def _resolve_look_screen(shell):
        overlay = getattr(shell, "_overlay_shell", None)
        look = getattr(overlay, "look_at_screen", None)
        if callable(look):
            return look, ""
        legacy = getattr(getattr(shell, "instance", None), "win", None)
        legacy_look = getattr(legacy, "look_at_screen", None)
        if callable(legacy_look):
            return legacy_look, ""
        return None, "看看屏幕入口不可用"

    @staticmethod
    def _resolve_screen_capture(shell):
        overlay = getattr(shell, "_overlay_shell", None)
        capture = getattr(overlay, "on_screen_capture", None)
        if callable(capture):
            return capture, ""
        legacy = getattr(getattr(shell, "instance", None), "win", None)
        legacy_capture = getattr(legacy, "on_screen_capture", None)
        if callable(legacy_capture):
            return legacy_capture, ""
        return None, "截图提问入口不可用"


def create(manifest: ModuleManifest) -> HotkeysModule:
    return HotkeysModule(manifest)


__all__ = ["ACTION_TARGET_MODULES", "HotkeysModule", "create"]
