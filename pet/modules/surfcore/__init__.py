# -*- coding: utf-8 -*-
"""SurfCore 连接模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="surfcore",
    name="SurfCore 连接",
    factory="pet.modules.surfcore.module:create",
    description="发现本机 SurfCore pet-api、长轮询事件，并把 surfcore 客户端提供给其它模块。",
)

__all__ = ["MANIFEST"]
