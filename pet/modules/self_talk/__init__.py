# -*- coding: utf-8 -*-
"""「自言自语」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

SELF_TALK_CONFIG_KEYS: tuple[str, ...] = (
    "self_talk_enabled",
    "self_talk_min_interval",
    "self_talk_max_interval",
    "self_talk_texts",
    "self_talk_duration_seconds",
    "self_talk_image_dir",
    "self_talk_image_scale",
    "self_talk_image_chance",
    "self_talk_bubble_style",
)

MANIFEST = ModuleManifest(
    id="self_talk",
    name="自言自语",
    factory="pet.modules.self_talk.module:create",
    optional=("surfcore",),
    config_schema="pet.modules.self_talk.config:SCHEMA",
    config_keys=SELF_TALK_CONFIG_KEYS,
    description="桌宠每隔一段时间冒一条短句或配图；在线时每小时最多一条 SurfCore 生成台词。",
)

__all__ = ["MANIFEST", "SELF_TALK_CONFIG_KEYS"]
