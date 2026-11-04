# -*- coding: utf-8 -*-
"""「自言自语」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。

键名与默认值沿用旧核心配置，路由不变：这些键是**每宠**偏好，不是模块全局键，
所以 ``global_keys`` 保持空——设置页保存时仍按原路径落 ``config-slot-N.json``。
"""
from __future__ import annotations

from ...config import (
    DEFAULT_SELF_TALK_BUBBLE_STYLE,
    DEFAULT_SELF_TALK_DURATION_SECONDS,
    DEFAULT_SELF_TALK_IMAGE_CHANCE,
    DEFAULT_SELF_TALK_MAX_INTERVAL,
    DEFAULT_SELF_TALK_MIN_INTERVAL,
    DEFAULT_SELF_TALK_TEXTS,
    SELF_TALK_BUBBLE_STYLES,
)
from ..base import ModuleConfigSchema

DEFAULTS = {
    "self_talk_enabled": False,
    "self_talk_min_interval": DEFAULT_SELF_TALK_MIN_INTERVAL,
    "self_talk_max_interval": DEFAULT_SELF_TALK_MAX_INTERVAL,
    "self_talk_duration_seconds": DEFAULT_SELF_TALK_DURATION_SECONDS,
    "self_talk_image_scale": 100,
    "self_talk_image_chance": DEFAULT_SELF_TALK_IMAGE_CHANCE,
    "self_talk_texts": list(DEFAULT_SELF_TALK_TEXTS),
    "self_talk_image_dir": "assets/big_blue_fat_fish",
    "self_talk_bubble_style": DEFAULT_SELF_TALK_BUBBLE_STYLE,
}


def _float_or_default(value, default: float, low: float, high: float) -> float:
    """与 ``pet.config._float_or_default`` 同规：坏值/NaN/超大数都回退默认再夹取。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float(default)
    if number != number:  # NaN
        number = float(default)
    return max(low, min(high, number))


def _clean_texts(value) -> list[str]:
    """文本池清洗：兼容旧口径（去空、去重、单条 ≤120 字，空表回默认）。"""
    if not isinstance(value, list):
        return list(DEFAULT_SELF_TALK_TEXTS)
    texts: list[str] = []
    for item in value:
        if not isinstance(item, str):
            item = str(item)
        text = item.strip()[:120]
        if text and text not in texts:
            texts.append(text)
    return texts or list(DEFAULT_SELF_TALK_TEXTS)


def normalize(data: dict) -> None:
    """就地清洗自言自语配置（手改配置里的脏值；异常由调用方隔离）。"""
    if not isinstance(data, dict):
        return
    data["self_talk_min_interval"] = _float_or_default(
        data.get("self_talk_min_interval"), DEFAULT_SELF_TALK_MIN_INTERVAL, 5.0, 3600.0)
    data["self_talk_max_interval"] = _float_or_default(
        data.get("self_talk_max_interval"), DEFAULT_SELF_TALK_MAX_INTERVAL, 5.0, 3600.0)
    minimum = float(data["self_talk_min_interval"])
    maximum = float(data["self_talk_max_interval"])
    data["self_talk_min_interval"] = min(minimum, maximum)
    data["self_talk_max_interval"] = max(minimum, maximum)
    data["self_talk_duration_seconds"] = _float_or_default(
        data.get("self_talk_duration_seconds"), DEFAULT_SELF_TALK_DURATION_SECONDS, 1.0, 300.0)
    data["self_talk_image_dir"] = str(data.get("self_talk_image_dir") or "").strip()[:500]
    data["self_talk_image_scale"] = int(_float_or_default(
        data.get("self_talk_image_scale"), 100.0, 50.0, 300.0))
    data["self_talk_image_chance"] = int(_float_or_default(
        data.get("self_talk_image_chance"), float(DEFAULT_SELF_TALK_IMAGE_CHANCE), 0.0, 100.0))
    data["self_talk_enabled"] = bool(data.get("self_talk_enabled", False))
    data["self_talk_texts"] = _clean_texts(data.get("self_talk_texts"))
    style = str(data.get("self_talk_bubble_style") or "")
    data["self_talk_bubble_style"] = (
        style if style in SELF_TALK_BUBBLE_STYLES else DEFAULT_SELF_TALK_BUBBLE_STYLE)


SCHEMA = ModuleConfigSchema(defaults=DEFAULTS, normalize=normalize)

__all__ = ["DEFAULTS", "SCHEMA", "normalize"]
