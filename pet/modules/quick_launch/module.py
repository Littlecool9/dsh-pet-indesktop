# -*- coding: utf-8 -*-
"""「快捷启动」模块运行时：菜单本身无进程级状态，启动/停止都是 no-op。"""
from __future__ import annotations

from ..base import ModuleHost, ModuleManifest

MODULE_ID = "quick_launch"


class QuickLaunchModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None

    def start(self, host: ModuleHost) -> None:
        self._host = host

    def apply_config(self, config) -> None:
        return None

    def stop(self) -> None:
        self._host = None


def create(manifest: ModuleManifest) -> QuickLaunchModule:
    return QuickLaunchModule(manifest)


__all__ = ["QuickLaunchModule", "create"]
