# -*- coding: utf-8 -*-
"""全局快捷键的**动作表**（Qt-free，设置页与模块运行时共用）。

主进程的注册运行时代码在 ``pet/modules/hotkeys``；设置进程（``--settings``）
只读这里，**不 import 模块运行时**。动作 id 与右键菜单同名：热键只是这些动作的
另一种触发方式，行为仍落在宿主既有的入口上。

``ACTIONS`` 的值就是配置键名（与设置行 ``key`` 同名，这样「已修改」标记与单项
重置能自动比对）。
"""

from __future__ import annotations

import os

#: 动作 → 配置键。键名稳定，不许改名。
ACTIONS: dict[str, str] = {
    "open_chat": "hotkey_open_chat",
    "look_screen": "hotkey_look_screen",
    "screen_capture": "hotkey_screen_capture",
}

#: 动作的中文名（日志/提示用）
ACTION_LABELS: dict[str, str] = {
    "open_chat": "AI 对话",
    "look_screen": "看看屏幕",
    "screen_capture": "截图提问",
}


def is_supported() -> bool:
    """当前平台能否注册系统级热键（只有 Windows 有这条路）。"""
    return os.name == "nt"


__all__ = ["ACTIONS", "ACTION_LABELS", "is_supported"]
