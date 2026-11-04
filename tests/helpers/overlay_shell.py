# -*- coding: utf-8 -*-
"""Shared offscreen OverlayShell scaffolding for per-slot / menu tests.

Extracted from the retired collision-toggle test module: these helpers build a
real on-disk Config + real PetSprite shell. They are support code, not a test
module, so they live outside ``test_*`` collection.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import tests.test_sprite_menu_facade as fac

app = QApplication.instance() or QApplication([])


class _SlotInstance:
    """Minimal shell host that only provides the per-pet library factory."""

    def __init__(self, config):
        self.config = config

    def _create_library(self, _character_id):
        return fac.RichLibrary()


def _make_slot_shell(tmp_path, **config_values):
    """Real on-disk Config shell + real PetSprite (per-slot reads are real files)."""
    from pet.config import Config
    from pet.overlay_shell import OverlayShell
    from pet.pet_sprite import PetSprite
    from tests.test_overlay_window_capabilities import FakeScreen

    cfg = Config(base=tmp_path)
    for key, value in config_values.items():
        cfg.set(key, value)
    cfg.save()
    shell = OverlayShell(
        app, _SlotInstance(cfg),
        screen=FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040)),
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    lib = fac.RichLibrary()
    shell.lib = lib
    shell.sprite.library = lib
    return shell, cfg


def _write_slot(parent, slot, **values):
    """Write settings the way the settings process does (real Config + disk)."""
    from pet.config import Config
    from pet.settings_slot_config import route_settings_config

    cfg = route_settings_config(Config(base=parent, instance_id=f"slot-{slot}"))
    for key, value in values.items():
        cfg.set(key, value)
    assert cfg.save()


def _notify_slot_saved(shell):
    """Drive the shell's existing config-directory change entry point."""
    shell._on_settings_command_dir_changed(str(shell._config.dir))


def _save_main(parent, shell, **values):
    """Simulate an external write to the main config: save -> reload -> apply."""
    from pet.config import Config
    from pet.settings_slot_config import route_settings_config

    other = route_settings_config(Config(base=parent, instance_id="slot-0"))
    for key, value in values.items():
        other.set(key, value)
    assert other.save()
    shell._config.reload()
    shell.refresh_settings()


def _teardown(shell):
    timer = getattr(shell, "_self_talk_timer", None)
    if timer is not None:
        timer.stop()
    shell._teardown_settings_command_watch()
    overlay = getattr(shell, "overlay", None)
    if overlay is not None:
        overlay.close()
    # Drain deferred sound callbacks delivered with QTimer.singleShot(0, ...).
    QApplication.processEvents()
    QApplication.processEvents()


def _make_persistent_shell(base, values=None):
    """Real on-disk Config shell + real PetSprite (slot0 only).

    Returns ``(shell, made_libraries)``; ``_create_main_library`` is replaced by a
    factory that records each library it builds.
    """
    from pet.config import Config
    from pet.overlay_shell import OverlayShell
    from pet.pet_sprite import PetSprite
    from tests.test_overlay_window_capabilities import FakeScreen

    config = Config(str(base))
    for key, value in (values or {}).items():
        config.set(key, value)
    config.save()
    instance = _SlotInstance(config)
    screen = FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    shell = OverlayShell(
        app, instance, screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    main_lib = fac.RichLibrary()
    if shell.sprite is not None:
        shell.lib = main_lib
        shell.sprite.library = main_lib
    made: list = []

    def make_lib():
        lib = fac.RichLibrary()
        made.append(lib)
        return lib

    shell._create_main_library = make_lib
    return shell, made


def _place_center(sprite, cx, cy):
    """Place a sprite so its rect centre is at ``(cx, cy)`` (subject to clamping)."""
    from PySide6.QtCore import QPointF

    rect = sprite.rect()
    sprite.set_pos(QPointF(cx - rect.width() / 2.0, cy - rect.height() / 2.0))
    return sprite.rect()


def _ratio_of(rect, bounds):
    """Body-centre ratio relative to a bounds rect (same geometry as the product)."""
    return ((rect.x() + rect.width() / 2.0 - bounds.x()) / bounds.width(),
            (rect.y() + rect.height() / 2.0 - bounds.y()) / bounds.height())


def _teardown(shell, clip=None):
    """Stop a shell, close overlays and delete its runtime marker."""
    shell.stop()
    for overlay in list(shell.driver.overlays):
        overlay.close()
    if clip is not None:
        clip.close()
    shell._delete_runtime_marker()
