# -*- coding: utf-8 -*-
"""「DeepSeek 余额」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ..base import ModuleConfigSchema

REFRESH_KEY = "balance_refresh_minutes"
LABELS_MODE_KEY = "balance_tier_labels_mode"
LABEL_PEAK_KEY = "balance_tier_label_peak"
LABEL_IDLE_KEY = "balance_tier_label_idle"
COLOR_KEY = "balance_tier_color_enabled"
CLICK_KEY = "click_show_balance"

# click_show_balance 是每宠键（跟着角色/档案走）；其余是全局键。
GLOBAL_KEYS = (REFRESH_KEY, LABELS_MODE_KEY, LABEL_PEAK_KEY, LABEL_IDLE_KEY, COLOR_KEY)

SCHEMA = ModuleConfigSchema(
    defaults={
        CLICK_KEY: False,  # 点击显示 DeepSeek 余额
        REFRESH_KEY: 0,  # 自动刷新间隔（分钟，0=关闭）
        LABELS_MODE_KEY: "default",  # 峰谷提示文案：default / liangwen / custom
        LABEL_PEAK_KEY: "",  # 自定义“高峰”文本（custom 模式）
        LABEL_IDLE_KEY: "",  # 自定义“空闲”文本（custom 模式）
        COLOR_KEY: True,  # 峰谷提示颜色：高峰红/低谷绿
    },
    global_keys=GLOBAL_KEYS,
)

__all__ = [
    "CLICK_KEY", "COLOR_KEY", "GLOBAL_KEYS", "LABEL_IDLE_KEY", "LABEL_PEAK_KEY",
    "LABELS_MODE_KEY", "REFRESH_KEY", "SCHEMA",
]
