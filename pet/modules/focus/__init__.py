# -*- coding: utf-8 -*-
"""「专注模式」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="focus",
    name="专注模式",
    factory="pet.modules.focus.module:create",
    menu_actions="pet.modules.focus.menu:actions",
    config_schema="pet.modules.focus.config:SCHEMA",
    config_keys=("focus_mode",),
    description="番茄钟专注/休息循环、专注陪伴与灵动岛卡片。",
)

__all__ = ["MANIFEST"]
