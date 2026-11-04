# -*- coding: utf-8 -*-
"""「DeepSeek 余额」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="balance",
    name="DeepSeek 余额",
    factory="pet.modules.balance.module:create",
    menu_actions="pet.modules.balance.menu:actions",
    config_schema="pet.modules.balance.config:SCHEMA",
    config_keys=(
        "click_show_balance",
        "balance_refresh_minutes",
        "balance_tier_labels_mode",
        "balance_tier_label_peak",
        "balance_tier_label_idle",
        "balance_tier_color_enabled",
    ),
    description="DeepSeek 余额查询、自动刷新、气泡提示与灵动岛余额信息。",
)

__all__ = ["MANIFEST"]
