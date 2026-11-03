# -*- coding: utf-8 -*-
"""设置页「网络信息入口 / 灵动岛第三方指标」的行、依赖、保存契约。

内置指标（网络/CPU/内存/GPU）与游戏帧率已删除；这里只验保留下来的两块：

- 右键菜单「网络信息」入口显隐（``network_info_menu_enabled``）；
- 第三方组件指标行（``island_metrics``，行来自可信目录的声明清单）。

断言走真实 ``ModernSettingsDialog``（设置窗口这个公开 seam），不碰私有调用顺序。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.modern_settings_dialog as settings_mod
from pet import island_extension_host as host
from pet.config import Config
from tests.test_island_extension_host import MANIFEST, _write_component

app = QApplication.instance() or QApplication([])

EXT = "cpu_temp"
WIDE_EXT = "cpu_power"
WIDE_MANIFEST = dict(MANIFEST, id=WIDE_EXT, label="功耗", max_text="8" * 24,
                     unit="W", unit_full="瓦特", source="测试电源")


def _dialog(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    cfg = Config(base=tmp_path)
    for key, value in settings.items():
        cfg.set(key, value)
    # #271：空身份会话按 slot0 分流，全局键的读源是路由视图另建的主配置（初值只取盘）
    if settings:
        assert cfg.save() is True
    return settings_mod.ModernSettingsDialog(cfg, include_ai=True), cfg


def _row(dialog, key):
    row = dialog.findChild(settings_mod.SettingRow, f"settingRow_{key}")
    assert row is not None, f"缺少设置行 {key}"
    return row


def _isolated_extension_root(tmp_path, monkeypatch):
    root = tmp_path / "island-extensions"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(host.ENV_DIRS, str(root))
    host.reset_cache()
    return root


# ---------------------------------------------------------------- 网络信息入口
def test_network_info_menu_row_exists_with_documented_copy(tmp_path, monkeypatch):
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        menu = _row(dialog, "network_info_menu")
        assert "1 KB" in menu.hint_label.text() and "不轮询" in menu.hint_label.text()
        assert dialog.network_info_menu_check.isChecked() is True
    finally:
        dialog.close()


def test_network_info_menu_toggle_round_trips(tmp_path, monkeypatch):
    dialog, cfg = _dialog(tmp_path, monkeypatch)
    try:
        dialog.network_info_menu_check.setChecked(False)
        assert dialog._write_config() is True
    finally:
        dialog.close()
    cfg.reload()
    assert cfg.get("network_info_menu_enabled") is False
    assert Config(base=tmp_path).get("network_info_menu_enabled") is False


# ---------------------------------------------------------------- 第三方组件行
def test_component_rows_exist_and_default_off(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        row = _row(dialog, f"island_{EXT}")
        assert "灵动岛指标" in row.label.text()
        toggle = getattr(dialog, f"island_{EXT}_check")
        assert toggle.isChecked() is False
        assert "settingRow_network_info_menu" in {
            item.objectName() for item in dialog._search_rows}
    finally:
        dialog.close()
        host.reset_cache()


def test_component_toggle_reflects_the_configured_list(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    dialog, _cfg = _dialog(tmp_path, monkeypatch, island_metrics=[EXT])
    try:
        assert getattr(dialog, f"island_{EXT}_check").isChecked() is True
    finally:
        dialog.close()
        host.reset_cache()


def test_component_rows_follow_the_island_and_info_toggles(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    dialog, _cfg = _dialog(tmp_path, monkeypatch)
    try:
        dialog.island_enabled_check.setChecked(True)
        dialog.island_info_check.setChecked(True)
        assert not _row(dialog, f"island_{EXT}").isHidden()
        dialog.island_info_check.setChecked(False)
        assert _row(dialog, f"island_{EXT}").isHidden()
    finally:
        dialog.close()
        host.reset_cache()


def test_save_writes_canonical_component_order(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    _write_component(root, "wide", manifest=WIDE_MANIFEST)
    dialog, cfg = _dialog(tmp_path, monkeypatch)
    try:
        getattr(dialog, f"island_{WIDE_EXT}_check").setChecked(True)
        getattr(dialog, f"island_{EXT}_check").setChecked(True)
        assert dialog._write_config() is True
    finally:
        dialog.close()
    cfg.reload()
    assert cfg.get("island_metrics") == [EXT, WIDE_EXT], "勾选先后不影响写回顺序"
    host.reset_cache()


def test_save_keeps_the_order_already_in_the_config(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    _write_component(root, "wide", manifest=WIDE_MANIFEST)
    dialog, cfg = _dialog(tmp_path, monkeypatch,
                          island_metrics=[WIDE_EXT, EXT])
    try:
        assert dialog._write_config() is True
    finally:
        dialog.close()
    cfg.reload()
    assert cfg.get("island_metrics") == [WIDE_EXT, EXT], "保存不得压回典范序"
    host.reset_cache()


def test_save_with_every_toggle_off_writes_an_empty_list(tmp_path, monkeypatch):
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    dialog, cfg = _dialog(tmp_path, monkeypatch, island_metrics=[EXT])
    try:
        getattr(dialog, f"island_{EXT}_check").setChecked(False)
        assert dialog._write_config() is True
    finally:
        dialog.close()
    cfg.reload()
    assert cfg.get("island_metrics") == []
    host.reset_cache()


def test_save_survives_a_component_that_appears_after_the_form_was_built(
        tmp_path, monkeypatch):
    """窗口开着时清单多了组件：保存不许抛，也不许删掉表单没覆盖的偏好。"""
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root)
    dialog, cfg = _dialog(tmp_path, monkeypatch, island_metrics=[EXT])
    try:
        assert "probe_late" not in dialog._island_metric_controls
        _write_component(root, "late",
                         manifest=dict(MANIFEST, id="probe_late", label="新组件"))
        cfg.set("island_metrics", [EXT, "probe_late"])
        assert dialog._write_config() is True
        assert cfg.get("island_metrics") == [EXT, "probe_late"], \
            "表单没覆盖的 id 保留磁盘偏好"
    finally:
        dialog.close()
        host.reset_cache()


def test_save_keeps_a_declared_component_whose_provider_is_missing(
        tmp_path, monkeypatch):
    """组件暂缺（清单在、provider 文件不在）：行仍在表单里 → 勾选态就是偏好。"""
    root = _isolated_extension_root(tmp_path, monkeypatch)
    _write_component(root, provider=None)
    dialog, cfg = _dialog(tmp_path, monkeypatch, island_metrics=[EXT])
    try:
        assert getattr(dialog, f"island_{EXT}_check").isChecked() is True
        assert dialog._write_config() is True
        assert cfg.get("island_metrics") == [EXT]
    finally:
        dialog.close()
        host.reset_cache()
