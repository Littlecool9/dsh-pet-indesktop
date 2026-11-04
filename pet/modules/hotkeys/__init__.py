# -*- coding: utf-8 -*-
"""「全局快捷键」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest
from ...hotkey_actions import ACTIONS

MANIFEST = ModuleManifest(
    id="hotkeys",
    name="全局快捷键",
    factory="pet.modules.hotkeys.module:create",
    config_schema="pet.modules.hotkeys.config:SCHEMA",
    config_keys=tuple(ACTIONS.values()),
    description="把三个既有动作（AI 对话 / 看看屏幕 / 截图提问）绑定到系统级热键。",
)

__all__ = ["MANIFEST"]
