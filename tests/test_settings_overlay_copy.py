# -*- coding: utf-8 -*-
"""设置页文案 × overlay（默认拓扑）实际行为的聚焦回归（批 B8）。

三个缺口（证据：.scratch/windows-parity-20260926-a/audit-20260927-swarm/raw.txt）：

- T3 窗口级键（置顶/鼠标穿透/不透明度/锁定位置/SHIFT 拖拽/光标隐藏穿透/全屏
  自动隐藏）在 overlay 一窗多宠下物理上只能整窗生效 → 每个 slot 设置页补一句
  「对所有桌宠生效」。**#271 起主宠页也在此列**：无 ``--instance`` 的空身份设置
  会话按 slot0 分流，主宠页就是 slot0 页（= 生产 ``--instance slot-0`` 路径），
  与子宠页同口径标注。

纪律：offscreen；同步直调，不 sleep；不 mock 产品对象。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

#: overlay 单合成窗下只能整窗生效的窗口级键（T3）。
WINDOW_SCOPE_IDS = (
    "on_top",
    "mouse_through",
    "pet_opacity",
    "lock_position",
    "shift_drag",
    "cursor_hidden_passthrough",
    "auto_hide_fullscreen",
)

SCOPE_NOTE = "（对所有桌宠生效）"


def _dialog(tmp_path, monkeypatch, *, instance_id: str = "",
            standalone: bool = False):
    """按身份构建设置页。

    平台固定 win32：T3 的 ``cursor_hidden_passthrough`` / ``auto_hide_fullscreen``
    只在 Windows 建控件。
    """
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.sys, "platform", "win32")
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(base=tmp_path, instance_id=instance_id) if instance_id else Config(base=tmp_path)
    return settings_mod.ModernSettingsDialog(config, include_ai=False, standalone=standalone)


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def _hint(dialog, setting_id: str) -> str:
    import pet.modern_settings_dialog as settings_mod

    row = dialog.findChild(settings_mod.SettingRow, f"settingRow_{setting_id}")
    assert row is not None, f"设置页必须有 {setting_id} 行"
    return row.hint_label.text()


def _row(dialog, setting_id: str):
    import pet.modern_settings_dialog as settings_mod

    row = dialog.findChild(settings_mod.SettingRow, f"settingRow_{setting_id}")
    assert row is not None, f"设置页必须有 {setting_id} 行"
    return row


def _scope_note(dialog, setting_id: str) -> str:
    """行内**独立标注**里的那句话（作用域声明不再粘在灰说明末尾）。"""
    row = _row(dialog, setting_id)
    return row.scope_note.text() if not row.scope_note.isHidden() else ""


# --------------------------------------------------------------------------
# T3 窗口级键的生效范围
# --------------------------------------------------------------------------
@pytest.mark.parametrize("setting_id", WINDOW_SCOPE_IDS)
def test_child_page_marks_window_scope_keys_as_global(tmp_path, monkeypatch, setting_id):
    """overlay + 子宠页：窗口级键补「对所有桌宠生效」，可访问说明同步。"""
    row = None
    dialog = _dialog(tmp_path, monkeypatch, instance_id="slot-1")
    try:
        hint = _hint(dialog, setting_id)
        row = _row(dialog, setting_id)
        note = _scope_note(dialog, setting_id)
        description = row.control.accessibleDescription()
    finally:
        _close(dialog)
    assert note == SCOPE_NOTE, "标注里要有这一句（挂在标签那一行，不粘在说明末尾）"
    assert SCOPE_NOTE not in hint, "灰说明末尾不该还带着它"
    # 可访问说明是"说明 + 标注"全文：读屏仍播得到作用域（构造期 hint 已含它时不能丢）。
    assert description == hint + SCOPE_NOTE


@pytest.mark.parametrize("setting_id", WINDOW_SCOPE_IDS)
def test_main_page_shows_scope_note(tmp_path, monkeypatch, setting_id):
    """overlay + 主宠页：与子宠页同口径补「（对所有桌宠生效）」。

    #271 契约变更：无 ``--instance`` 的空身份设置会话按 slot0 分流——**主宠页就是
    slot0 页**，与生产 ``--instance slot-0`` 路径（D13）逐位同构。窗口级键在单合成
    窗里同样只能整窗生效，故主宠页不该再"静默地少一句说明"。旧契约（"空身份 = 全局
    视角页，不加注记"）已作废，这里与 ``test_child_page_marks_window_scope_keys_as_global``
    断言同一条注记；注记本体的措辞由产品常量 ``ALL_PETS_SCOPE_NOTE`` 提供。
    """
    from pet.settings_pet_controls import ALL_PETS_SCOPE_NOTE

    dialog = _dialog(tmp_path, monkeypatch)
    try:
        note = _scope_note(dialog, setting_id)
    finally:
        _close(dialog)
    assert note == ALL_PETS_SCOPE_NOTE


def test_standalone_settings_process_marks_scope_note(tmp_path, monkeypatch):
    """真实交付路径：独立设置进程（--settings --instance slot-1）同样带说明。"""
    dialog = _dialog(tmp_path, monkeypatch, instance_id="slot-1", standalone=True)
    try:
        notes = {key: _scope_note(dialog, key) for key in WINDOW_SCOPE_IDS}
    finally:
        _close(dialog)
    for key, note in notes.items():
        assert note == SCOPE_NOTE, key


@pytest.mark.parametrize("setting_id", WINDOW_SCOPE_IDS)
def test_window_scope_note_survives_readers(tmp_path, monkeypatch, setting_id):
    """窗口级注入不许漏：七行都在、都可见、搜索也还找得回这一行。

    这条盯的是"拆成独立标注"最容易踩的坑——原注入（``_apply_window_scope_rows``）
    是运行期按 objectName 补的，改成标注之后就多了一个"标注没挂上"的失败面。
    """
    row = None
    dialog = _dialog(tmp_path, monkeypatch, instance_id="slot-1")
    try:
        row = _row(dialog, setting_id)
        assert row.scope_note.isHidden() is False, f"{setting_id} 的标注没有呈现"
        dialog.search_edit.setText("")
        app.processEvents()
        dialog.search_edit.setText(SCOPE_NOTE)
        app.processEvents()
        hits = [item.objectName() for item in dialog._search_matches]
    finally:
        _close(dialog)
    assert f"settingRow_{setting_id}" in hits, (
        f"搜「{SCOPE_NOTE}」应当仍能命中 {setting_id}（实得 {hits}）")
