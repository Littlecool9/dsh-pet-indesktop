# -*- coding: utf-8 -*-
"""音效配置与迁移测试、真实 dt 与长帧物理积分测试。"""
import json
from pathlib import Path

from pet.config import Config


def test_legacy_click_sound_path_migration(tmp_path: Path):
    """旧配置迁移：只包含旧字段 click_sound_path 时迁移到 click_sound_pack。"""
    root = tmp_path / "appdata"
    cfg_dir = root / "dsh-pet-standalone"
    cfg_dir.mkdir(parents=True)
    custom_path = "C:/path/to/custom_sound.mp3"
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, "click_sound_path": custom_path}),
        encoding="utf-8",
    )

    cfg = Config(root)
    pack = cfg.get("click_sound_pack")
    assert pack == {
        "kind": "file",
        "id": "custom",
        "path": custom_path,
    }
    assert cfg.get("click_sound_volume") == 0.70
    assert cfg.get("slingshot_enabled") is True
    assert cfg.get("throw_strength") == "standard"


def test_legacy_click_sound_path_empty_migrates_to_builtin(tmp_path: Path):
    """旧配置 click_sound_path 为空时迁移为 builtin default。"""
    root = tmp_path / "appdata"
    cfg_dir = root / "dsh-pet-standalone"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, "click_sound_path": ""}),
        encoding="utf-8",
    )

    cfg = Config(root)
    pack = cfg.get("click_sound_pack")
    assert pack == {
        "kind": "builtin",
        "id": "default",
        "path": "",
    }


def test_explicit_click_sound_pack_precedence(tmp_path: Path):
    """新配置已有合法 click_sound_pack 时不受 click_sound_path 影响。"""
    root = tmp_path / "appdata"
    cfg_dir = root / "dsh-pet-standalone"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({
            "version": 4,
            "click_sound_path": "C:/old.mp3",
            "click_sound_pack": {"kind": "builtin", "id": "duck", "path": ""},
        }),
        encoding="utf-8",
    )

    cfg = Config(root)
    pack = cfg.get("click_sound_pack")
    assert pack == {
        "kind": "builtin",
        "id": "duck",
        "path": "",
    }


def test_invalid_sound_and_physics_config_normalization(tmp_path: Path):
    """异常或脏配置的归一化处理。"""
    root = tmp_path / "appdata"
    cfg_dir = root / "dsh-pet-standalone"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({
            "version": 4,
            "click_sound_volume": "invalid",
            "click_sound_pack": "bad_type",
            "throw_strength": "super_crazy",
        }),
        encoding="utf-8",
    )

    cfg = Config(root)
    assert cfg.get("click_sound_volume") == 0.70
    assert cfg.get("click_sound_pack") == {"kind": "builtin", "id": "default", "path": ""}
    assert cfg.get("throw_strength") == "standard"
