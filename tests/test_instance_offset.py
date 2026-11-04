# -*- coding: utf-8 -*-
"""角色名别名测试。"""
from __future__ import annotations

from pet.config import Config


def test_character_alias_roundtrip(tmp_path):
    """角色别名：设置 → 读取 → 空名恢复默认，且持久化到配置文件。"""
    cfg = Config(base=tmp_path)
    assert cfg.character_alias("shenshen") == ""

    cfg.set_character_alias("shenshen", "大肥鱼")
    assert cfg.character_alias("shenshen") == "大肥鱼"

    # 重新加载同一配置文件，别名仍在
    cfg2 = Config(base=tmp_path)
    assert cfg2.character_alias("shenshen") == "大肥鱼"

    # 空名 = 恢复默认
    cfg2.set_character_alias("shenshen", "")
    assert cfg2.character_alias("shenshen") == ""

    # 超长截断到 24 字符
    cfg2.set_character_alias("shenshen", "x" * 40)
    assert len(cfg2.character_alias("shenshen")) == 24


def test_character_display_name_prefers_alias(tmp_path):
    """显示名统一解析：用户别名优先，未设置时回退目录显示名（识屏身份提示同源）。"""
    from pet import catalog

    cfg = Config(base=tmp_path)
    assert cfg.character_display_name("shenshen") == catalog.character_display_name("shenshen")

    cfg.set_character_alias("shenshen", "小鲸鱼")
    assert cfg.character_display_name("shenshen") == "小鲸鱼"

    # 空名恢复默认后，回退目录显示名
    cfg.set_character_alias("shenshen", "")
    assert cfg.character_display_name("shenshen") == catalog.character_display_name("shenshen")
