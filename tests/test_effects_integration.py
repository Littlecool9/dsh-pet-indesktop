# -*- coding: utf-8 -*-
"""黄金回旋/边缘探头在设置页中的集成测试。

右键菜单入口已迁到 sprite_menu_facade（tests/test_sprite_menu_parity.py）；
纯 PetWindow 效果闸门（WindowFeatureGateMixin）已随 pet/window.py 删除，
其行为由 tests/test_sprite_behavior.py 的探头会话用例锁定。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow


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
    assert dialog.golden_spin_click_check is not None
    assert dialog.golden_spin_direct_check is not None
    assert dialog.edge_probe_check is not None
    direct_row = dialog.findChild(SettingRow, "settingRow_golden_spin_direct")
    assert direct_row is not None
    # 子开关只在“点击触发黄金回旋”开启后显示。
    assert dialog.golden_spin_click_check.isChecked() is False
    assert direct_row.isHidden() is True
    dialog.golden_spin_click_check.setChecked(True)
    assert direct_row.isHidden() is False
    dialog.golden_spin_direct_check.setChecked(True)
    dialog.edge_probe_check.setChecked(True)
    assert dialog._write_config() is True
    cfg.reload()  # #271：写盘走路由视图另建的主配置，传入对象需重读才可见
    assert cfg.get("golden_spin_on_click") is True
    assert cfg.get("golden_spin_direct") is True
    assert cfg.get("edge_probe_enabled") is True
    dialog.reject()
    app.processEvents()
