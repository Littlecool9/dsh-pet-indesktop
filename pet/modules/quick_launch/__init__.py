# -*- coding: utf-8 -*-
"""「快捷启动」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="quick_launch",
    name="快捷启动",
    factory="pet.modules.quick_launch.module:create",
    menu_actions="pet.modules.quick_launch.menu:actions",
    config_schema="pet.modules.quick_launch.config:SCHEMA",
    config_keys=("quick_launch_apps",),
    description="右键菜单「快捷启动」子菜单；应用列表在设置页维护。",
)

__all__ = ["MANIFEST"]
