# -*- coding: utf-8 -*-
"""「待办提醒」模块清单（这里必须便宜：不 import Qt / 运行时代码）。"""
from __future__ import annotations

from ..base import ModuleManifest

MANIFEST = ModuleManifest(
    id="todo",
    name="待办提醒",
    factory="pet.modules.todo.module:create",
    menu_actions="pet.modules.todo.menu:actions",
    config_schema="pet.modules.todo.config:SCHEMA",
    config_keys=("todo_reminder_enabled", "todo_reminder_lead_minutes"),
    description="待办管理面板与到点提醒服务。",
)

__all__ = ["MANIFEST"]
