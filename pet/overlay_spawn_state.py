# -*- coding: utf-8 -*-
"""Compatibility seams for the single fixed profile identity (slot 0)."""
from pathlib import Path

from . import pet_profiles as profiles

MAX_SCAN_SLOTS = profiles.SLOT_MAX
PER_SLOT_SETTING_KEYS = profiles.PER_PET_SETTING_KEYS


def slot_config_path(config_dir, slot_id):
    return profiles.slot_profile_path(config_dir, slot_id)


def scan_slot_configs(config_dir):
    if not config_dir:
        return set()
    return {n for n in range(MAX_SCAN_SLOTS + 1)
            if profiles.slot_profile_exists(Path(config_dir), n)}


def _load_slot_config(config_dir, slot_id):
    return dict(profiles.read_slot_profile(config_dir, slot_id).data)


def _clean_geometry(geometry):
    return profiles._clean_geometry(geometry)[0]


def slot_config_exists(config_dir, slot_id):
    return profiles.slot_profile_exists(config_dir, slot_id)


def read_slot_geometry(config_dir, slot_id):
    return _clean_geometry(_load_slot_config(config_dir, slot_id))


def read_slot_config(config_dir, slot_id):
    profile = profiles.read_slot_profile(config_dir, slot_id)
    return dict(profile.data) if profile.exists else None


def write_slot_setting(config_dir, slot_id, key, value, *, user_customized=None):
    return profiles.write_profile_settings(config_dir, slot_id, {key: value},
                                          user_customized=user_customized).ok


def write_slot_geometry(config_dir, slot_id, geometry):
    return profiles.write_profile_geometry(config_dir, slot_id, geometry).ok
