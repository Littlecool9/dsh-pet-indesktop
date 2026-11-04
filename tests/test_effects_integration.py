# -*- coding: utf-8 -*-
"""边缘探头在设置页中的集成测试。

右键菜单入口已迁到 sprite_menu_facade（tests/test_sprite_menu_parity.py）；
纯 PetWindow 效果闸门（WindowFeatureGateMixin）已随 pet/window.py 删除，
其行为由 tests/test_sprite_behavior.py 的探头会话用例锁定。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_settings_dialog_has_effect_toggles_and_writes_config(tmp_path, monkeypatch):
    app = _qapp()
    # 该用例只验证设置写回，不验证音频预热；在 Windows headless CI 上触发
    # QSoundEffect 异步加载的 processEvents 可能产生 access violation。
    monkeypatch.setattr(
        "pet.modern_settings_dialog.warm_click_sound_effects",
        lambda *args, **kwargs: None,
    )
    cfg = Config(tmp_path)
    dialog = ModernSettingsDialog(cfg, include_ai=False)
    assert dialog.edge_probe_check is not None
    dialog.edge_probe_check.setChecked(True)
    assert dialog._write_config() is True
    cfg.reload()  # #271：写盘走路由视图另建的主配置，传入对象需重读才可见
    assert cfg.get("edge_probe_enabled") is True
    dialog.reject()
    app.processEvents()
