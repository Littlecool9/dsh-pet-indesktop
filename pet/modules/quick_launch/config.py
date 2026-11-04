# -*- coding: utf-8 -*-
"""「快捷启动」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。"""
from __future__ import annotations

from ..base import ModuleConfigSchema

KEY = "quick_launch_apps"

DEFAULT_QUICK_LAUNCH_APPS = [
    {"name": "默认浏览器", "path": "", "kind": "default_browser"},
]


def _clean_quick_launch_apps(value):
    """与 ``Config._clean_quick_launch_apps`` 同口径：最多 20 条，路径/名称必填。"""
    if not isinstance(value, list):
        return [dict(item) for item in DEFAULT_QUICK_LAUNCH_APPS]
    cleaned = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "application")
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or "").strip()[:60]
        if kind == "default_browser":
            cleaned.append({"name": name or "默认浏览器", "path": "", "kind": "default_browser"})
        elif path and name:
            cleaned.append({"name": name, "path": path, "kind": "application"})
    return cleaned


def _normalize(data: dict) -> None:
    data[KEY] = _clean_quick_launch_apps(data.get(KEY))


SCHEMA = ModuleConfigSchema(
    defaults={KEY: [dict(item) for item in DEFAULT_QUICK_LAUNCH_APPS]},
    normalize=_normalize,
    global_keys=(KEY,),
)

__all__ = ["DEFAULT_QUICK_LAUNCH_APPS", "KEY", "SCHEMA"]
