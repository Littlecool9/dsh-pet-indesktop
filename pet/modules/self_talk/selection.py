# -*- coding: utf-8 -*-
"""自言自语台词选择（纯逻辑，无 Qt、无宿主依赖）。

从 ``pet.window_alerts`` 迁入：文本池清洗、出图概率与「先掷骰子再选池」的抽样。
模块只依赖这些纯函数，测试可直接驱动。
"""
from __future__ import annotations

import random

from ...config import DEFAULT_SELF_TALK_IMAGE_CHANCE, DEFAULT_SELF_TALK_TEXTS

DEFAULT_IMAGE_CHANCE = DEFAULT_SELF_TALK_IMAGE_CHANCE


def read_self_talk_texts(value) -> list[str]:
    """配置里的候选文本；缺失/类型不对/全空时回默认池。"""
    if not isinstance(value, list):
        return list(DEFAULT_SELF_TALK_TEXTS)
    texts: list[str] = []
    for item in value:
        text = str(item).strip()[:120]
        if text and text not in texts:
            texts.append(text)
    return texts or list(DEFAULT_SELF_TALK_TEXTS)


def self_talk_image_chance(cfg) -> int:
    """自言自语出图概率（百分比 0~100）；读不到配置按默认值走。"""
    getter = getattr(cfg, "get", None)
    if not callable(getter):
        return DEFAULT_IMAGE_CHANCE
    try:
        value = float(getter("self_talk_image_chance", DEFAULT_IMAGE_CHANCE))
    except Exception:
        return DEFAULT_IMAGE_CHANCE
    return int(max(0.0, min(100.0, value)))


def pick_self_talk_choice(texts, images, image_chance):
    """按出图概率抽一条自言自语，返回 ``(kind, value)``；两边都空返回 None。

    先决定"这次出图还是出文本"，再在对应池里等权选一条，用户设的百分比就是
    真实概率（0 = 只出文本，100 = 只出图）。只有一边有内容时不掷骰子。
    """
    clean_texts = [text for text in (texts or []) if str(text).strip()]
    image_list = list(images or [])
    if not clean_texts and not image_list:
        return None
    if not image_list:
        return ("text", random.choice(clean_texts))
    if not clean_texts:
        return ("image", random.choice(image_list))
    chance = max(0.0, min(100.0, float(image_chance)))
    if random.random() * 100.0 < chance:
        return ("image", random.choice(image_list))
    return ("text", random.choice(clean_texts))


__all__ = [
    "DEFAULT_IMAGE_CHANCE",
    "pick_self_talk_choice",
    "read_self_talk_texts",
    "self_talk_image_chance",
]
