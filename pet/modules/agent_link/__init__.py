# -*- coding: utf-8 -*-
"""「Agent 联动」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="agent_link",
    name="Agent 联动",
    factory="pet.modules.agent_link.module:create",
    menu_actions="pet.modules.agent_link.menu:actions",
    config_schema="pet.modules.agent_link.config:SCHEMA",
    config_keys=("agent_link",),
    description="感知 DSH / Claude Code / Cursor / OpenCode 状态并驱动桌宠动作、气泡与音效。",
    extra={"uninstall_cleanup": "pet.modules.agent_link.uninstall:run_cleanup"},
)

__all__ = ["MANIFEST"]
