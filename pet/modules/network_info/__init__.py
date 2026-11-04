# -*- coding: utf-8 -*-
"""「网络信息」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="network_info",
    name="网络信息",
    factory="pet.modules.network_info.module:create",
    menu_actions="pet.modules.network_info.menu:actions",
    config_schema="pet.modules.network_info.config:SCHEMA",
    config_keys=("network_info_menu_enabled",),
    description="公网 IP / IP 属地 / 外网连通性弹窗，以及右键菜单入口。",
)

__all__ = ["MANIFEST"]
