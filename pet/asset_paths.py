# -*- coding: utf-8 -*-
"""Bundled-asset path helpers shared by kept features.

The playful menu entry used to own these helpers; the entry is gone but the
self-talk image directory still resolves relative paths against the bundled
``assets`` tree, so the small path layer lives here instead.
"""
from __future__ import annotations

from pathlib import Path


def bundled_assets_root() -> Path:
    """应用内置资产根目录（源码树或 PyInstaller _internal）。"""
    return Path(__file__).resolve().parents[1] / "assets"


def default_self_talk_image_dir() -> Path:
    """内置自言自语配图目录（默认池）。"""
    return bundled_assets_root() / "big_blue_fat_fish"


def resolve_asset_path(path: str | Path | None, fallback: Path) -> Path:
    """把配置里的相对/绝对路径解析成当前安装下的真实路径；读不到回退默认。"""
    fallback = Path(fallback).expanduser()
    if path is None or not str(path).strip():
        return fallback
    candidate = Path(str(path or "")).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.exists() else fallback
    bundled = bundled_assets_root() / candidate
    return bundled if bundled.exists() else fallback
