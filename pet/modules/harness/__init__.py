# -*- coding: utf-8 -*-
"""「DeepSeek Harness」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="harness",
    name="DeepSeek Harness",
    factory="pet.modules.harness.module:create",
    menu_actions="pet.modules.harness.menu:actions",
    config_schema="pet.modules.harness.config:SCHEMA",
    config_keys=("harness_autostart", "harness_launch_target"),
    description="一键启动 / 重启 / 停止 dsh web，以及桌面端界面；随桌宠自启。",
)

__all__ = ["MANIFEST"]
