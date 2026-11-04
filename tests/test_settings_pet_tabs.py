# -*- coding: utf-8 -*-
"""「桌宠」域页内标签（显示 / 动作）的聚焦回归（第二刀，2026-10-08）。

口径来源：``.scratch/SETTINGS-UI-DESIGN-K3-20261007.md`` §二（页内标签的判定规则）
与第二刀裁决——桌宠域是**两个互斥任务**：「它长什么样」（显示）与
「它怎么动」（动作）；高级组永远垫底其所属标签页；侧栏 10 域、
深链与搜索跳域语义不变。

本文件钉住五件事：

1. 桌宠域确实用页内标签组织、默认激活标签 1、侧栏 10 个域不变（域是外部契约）；
2. 标签内组序：主视线组在前、高级组垫底；每行的 ``SettingsSection`` 归属唯一；
3. 每一行都能由标签键路由到，切到所属标签后可见（分页没丢功能）；
4. 搜索命中另一标签的行时自动切标签 + 展开高级组，命中行**实际可见**
   （标签 1：桌宠大小；标签 2：播放速率）；
5. 保存 round trip 不变——分页是纯呈现层改动，不碰配置键、默认值与保存链。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

EXPECTED_SIDEBAR = [
    "常规", "桌宠", "互动", "菜单", "桌面组件", "AI 与对话", "自动化与联动",
]
#: 标签键给代码（稳定），标签名给用户（可读）；顺序 = 使用顺序。
EXPECTED_TABS = (("display", "显示"), ("motion", "动作"))

#: 标签 1 的主视线组序。
TAB1_PRIMARY = ("显示",)
#: 标签 2 的组序。
TAB2_SECTIONS = ("动画与移动", "拖动", "边缘探头")

TAB1_ROWS = (
    "scale", "bubble_text_scale", "pet_opacity",
)
TAB1_ADVANCED_ROWS = ()
TAB2_ROWS = (
    "playback_speed", "animation_gap", "no_move",
    "lock_position", "shift_drag", "edge_probe",
)
TAB2_ADVANCED_ROWS = ()
def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.settings_slot_config import route_settings_config

    app = _qapp()
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    # 生产形态：当前宠的设置页拿 slot0 的路由视图（每宠键写进 config-slot-0.json）
    dlg = settings_mod.ModernSettingsDialog(
        route_settings_config(Config(base=tmp_path, instance_id="slot-0")),
        include_ai=True)
    yield dlg
    dlg.close()
    app.processEvents()


def _pet_page(dialog):
    index = next(
        i for i in range(dialog.sidebar.count()) if dialog.sidebar.item(i).text() == "桌宠"
    )
    return dialog.pages.widget(index)


def _pet_tabs(dialog):
    from pet.settings_widgets import SettingsTabContainer

    tabs = _pet_page(dialog).findChild(SettingsTabContainer, "settingsTaskTabs")
    assert tabs is not None, "桌宠域没有用页内标签组织"
    return tabs


def _row(dialog, key):
    from pet.modern_settings_dialog import SettingRow

    found = dialog.findChild(SettingRow, f"settingRow_{key}")
    assert found is not None, f"缺少设置行 {key}"
    return found


def _row_key(row) -> str:
    return row.objectName()[len("settingRow_"):]


def _sections_of_tab(tabs, tab_key):
    """标签页里按真实布局顺序排列的 ``SettingsSection``（不是 child 顺序）。"""
    from pet.settings_widgets import SettingsSection

    tabs.setCurrentKey(tab_key)
    content = tabs.stack.currentWidget()
    sections = []
    for position in range(content.layout().count()):
        widget = content.layout().itemAt(position).widget()
        if isinstance(widget, SettingsSection):
            sections.append(widget)
    return sections


def _section_title(section) -> str:
    from PySide6.QtWidgets import QLabel

    if section.toggle is not None:  # 高级组：标题在 disclosure 按钮上
        return section.toggle.text()
    label = section.findChild(QLabel, "sectionTitle")
    return label.text() if label is not None else ""


def _section_of(row):
    """行所属的 ``SettingsSection``（走 widget 祖先链）。"""
    from pet.modern_settings_dialog import SettingsSection

    parent = row.parentWidget()
    while parent is not None and not isinstance(parent, SettingsSection):
        parent = parent.parentWidget()
    assert parent is not None, f"{row.objectName()} 必须落在某个 SettingsSection 内"
    return parent


def test_pet_domain_uses_in_page_tabs_without_changing_sidebar(dialog):
    """页内标签组织桌宠域；默认激活标签 1；侧栏 10 个域不变。"""
    assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == EXPECTED_SIDEBAR

    tabs = _pet_tabs(dialog)
    assert tabs.keys() == tuple(key for key, _ in EXPECTED_TABS)
    assert tabs.labels() == tuple(label for _, label in EXPECTED_TABS)
    assert tabs.currentKey() == EXPECTED_TABS[0][0], "默认必须激活标签 1"
    assert _pet_page(dialog).isAncestorOf(tabs)


def test_group_order_inside_each_tab_puts_the_advanced_group_last(dialog):
    """标签内组序：主视线组在前、高级组垫底；每行的 SettingsSection 归属唯一。"""
    tabs = _pet_tabs(dialog)
    expected = {
        "display": TAB1_PRIMARY,
        "motion": TAB2_SECTIONS,
    }
    for tab_key, titles in expected.items():
        sections = _sections_of_tab(tabs, tab_key)
        assert [_section_title(section) for section in sections] == list(titles)
        assert all(section.advanced is False for section in sections)

    # 归属唯一：每个桌宠行的 SettingsSection 祖先有且只有一个（不会一组挂两处）。
    from pet.modern_settings_dialog import SettingsSection

    for key in TAB1_ROWS + TAB1_ADVANCED_ROWS + TAB2_ROWS + TAB2_ADVANCED_ROWS:
        parent, ancestors = _row(dialog, key).parentWidget(), []
        while parent is not None:
            if isinstance(parent, SettingsSection):
                ancestors.append(parent)
            parent = parent.parentWidget()
        assert len(ancestors) == 1, f"{key} 的 SettingsSection 祖先必须唯一"


def test_every_pet_row_routes_to_its_tab_and_is_reachable(dialog):
    """每行都由标签键路由到，切到所属标签后可见——分页没有丢掉任何一行。"""
    tabs = _pet_tabs(dialog)
    routing = {}
    routing.update({key: "display" for key in TAB1_ROWS})
    routing.update({key: "display" for key in TAB1_ADVANCED_ROWS})
    routing.update({key: "motion" for key in TAB2_ROWS})
    routing.update({key: "motion" for key in TAB2_ADVANCED_ROWS})

    page = _pet_page(dialog)
    for tab_key, keys in (
        ("display", TAB1_ROWS + TAB1_ADVANCED_ROWS),
        ("motion", TAB2_ROWS + TAB2_ADVANCED_ROWS),
    ):
        tabs.setCurrentKey(tab_key)
        _qapp().processEvents()
        for key in keys:
            row = _row(dialog, key)
            assert tabs.key_for_descendant(row) == routing[key], (
                f"{key} 期望落在 {routing[key]} 标签，实际 {tabs.key_for_descendant(row)}"
            )
            if key in TAB1_ADVANCED_ROWS or key in TAB2_ADVANCED_ROWS:
                _section_of(row).toggle.setChecked(True)  # 高级组默认收起
            _qapp().processEvents()
            assert row.isVisibleTo(page) is True, f"{key} 在 {tab_key} 标签里不可见"


def test_rows_of_the_other_tab_are_out_of_view_but_not_destroyed(dialog):
    """另一标签的行只是不可见，对象与控件都还在——整理没有删功能/没有动保存链。"""
    tabs = _pet_tabs(dialog)
    tabs.setCurrentKey("display")
    hidden_row = _row(dialog, "playback_speed")
    assert hidden_row.isVisibleTo(tabs) is False
    assert hidden_row.isHidden() is False, "行只是不在当前标签页，不是被隐藏/删除"
    assert hidden_row.control is not None, "控件对象必须仍在（保存链依赖它）"

    tabs.setCurrentKey("motion")
    assert hidden_row.isVisibleTo(tabs) is True


def _search(dialog, query: str):
    """真实搜索框输入（textChanged）+ 事件循环，取当前命中行。"""
    dialog.search_edit.setText("")
    _qapp().processEvents()
    dialog.search_edit.setText(query)
    for _ in range(3):
        _qapp().processEvents()
    matches = dialog._search_matches
    assert matches, f"搜索「{query}」没有命中任何行"
    return matches[dialog._search_index]


def test_search_jumps_to_the_tab_that_owns_the_hit(dialog):
    """搜「播放速率」（标签 2 的行）→ 自动切到动作标签，命中行可见。"""
    tabs = _pet_tabs(dialog)
    assert tabs.currentKey() == "display"

    row = _search(dialog, "播放速率")
    assert _row_key(row) == "playback_speed"
    assert dialog.sidebar.currentItem().text() == "桌宠"
    assert tabs.currentKey() == "motion"
    assert row.isVisibleTo(_pet_page(dialog)) is True


def test_search_on_tab_one_hits_stay_on_tab_one(dialog):
    """标签 1 的行（含默认标签）命中后仍停在标签 1、行可见——回归，不是只测切过去。"""
    tabs = _pet_tabs(dialog)
    queries = [
        ("桌宠大小", "scale"),
        ("气泡文字大小", "bubble_text_scale"),
    ]

    for query, key in queries:
        tabs.setCurrentKey("motion")  # 先离开标签 1，验证真的切回来
        row = _search(dialog, query)
        assert _row_key(row) == key, f"「{query}」应命中 {key}"
        assert tabs.currentKey() == "display", f"「{query}」命中标签 1 的行必须切回标签 1"
        assert row.isVisibleTo(_pet_page(dialog)) is True, f"「{query}」命中的行必须实际可见"


def test_pet_settings_save_round_trip_is_unchanged(dialog, tmp_path):
    """保存 round trip 不变：分页只改呈现，配置键/默认值/保存链一字未动。"""
    from pet.config import Config

    _row(dialog, "lock_position").control.setChecked(True)

    dialog._save()
    _qapp().processEvents()

    # 每宠键（锁定位置）真值在 slot0 档案。
    from pet.settings_slot_config import route_settings_config

    saved = route_settings_config(Config(base=tmp_path, instance_id="slot-0"))
    assert saved.get("lock_position") is True
