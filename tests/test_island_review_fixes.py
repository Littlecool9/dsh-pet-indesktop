# -*- coding: utf-8 -*-
"""评审修复批的契约测试（2026-10-07，多轮评审合流）。

来源映射（ops5.5 N1：半年后能反推每个用例是哪轮评审加的）：

- astra 终审 R1：bounce 闸门 / squish 横向 / FontChange 几何 / 卡片 hover / 内容键模板分量
- 6.1sol 交叉票 R2：起拖停淡化 / 部分折叠行标注 / oversize 含单位盒 / 审计用例诚实化
- 6.1sol 终审 R3：hover 真实序列（本节 ②）、closeEvent、滞回清零、折叠故障保持、
  DSH 关闭 offline（用例在 tests/test_agent_link.py::TestDshDisableResetsPresentationState）
- 网络包络振荡的回归在 ``test_island_network_envelope.py``（astra 阻塞 1）

- R1-2 工作上升沿弹跳必须过与 ``notify_event`` 同一道闸门（event_effects + 免打扰；
  2026-10-08 补：免打扰那一半的全屏口径必须读宿主 ``quiet_also_on_fullscreen``，
  不许吃 ``suppression_active`` 的默认参数）
- R1-3 squish 拉伸期（sy>1）横向只鼓不缩，宽岛内容不出外壳
- R1-4 FontChange 后普通胶囊的窗口几何与行计划同步
- R1-5 展开卡片 hover 暂停 15s 自动收起（离开重新倒计时）
- 附：内容缓存键覆盖段模板分量（label/box_text 变化必须重建位图）
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QApplication

import pet.dynamic_island as island_mod
import pet.island_layout as island_layout_mod
from pet import quiet_mode
from pet.dynamic_island import DynamicIsland
from pet.modules.agent_link.dsh_state import DshState

app = QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, width=1400):
        self._rect = QRect(0, 0, width, 768)

    def availableGeometry(self):
        return self._rect


class _StubConfig:
    """最小配置替身：允许把未实现/未声明的 id 塞进 ``island_metrics``。"""

    def __init__(self, **data):
        self._data = {"dynamic_island": {}}
        self._data.update(data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value) -> None:
        self._data[key] = value

    def save(self) -> bool:
        return True

    def character_alias(self, character_id: str) -> str:
        return ""


def _island(monkeypatch, *, metrics=(), **overrides):
    monkeypatch.setattr(island_mod.DynamicIsland, "_current_screen",
                        lambda self: _FakeScreen())
    cfg = _StubConfig(island_metrics=list(metrics))
    data = {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
            "info_mode": "time", "custom_text": "", "show_status": True,
            "style": "dark", "x": 400, "y": 300}
    data.update(overrides)
    cfg.set("dynamic_island", data)
    return DynamicIsland(cfg)


# ---------------------------------------------------------- R1-2 弹跳闸门
def test_work_edge_bounce_respects_event_effects_and_quiet_mode(monkeypatch):
    """DSH 开工弹跳：默认弹；event_effects 关掉不弹；免打扰期间不弹。

    astra 应修 2：修复前 ``set_dsh_state`` 的工作上升沿无条件 ``_bounce()``，
    与 ``notify_event``/``bump`` 的开关语义形成两套（裁决稿 §一-7：禁弹跳，
    读数照常——状态点本身不受闸门影响，所以只拦弹跳不拦状态）。
    """
    island = _island(monkeypatch)
    try:
        bounces = []
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))

        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [3.0], "默认（动效开+非免打扰）工作上升沿应弹一下"

        # event_effects 关掉：换岛重测（配置在岛实例上）
        island.close()
        island = _island(monkeypatch, event_effects=False)
        bounces.clear()
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [], "event_effects=False 时工作上升沿不许弹"
        island.close()

        # 免打扰期间：active()=True 的替身 QuietState
        class _Quiet:
            def suppression_active(self, **_kw):
                return True

        monkeypatch.setattr(quiet_mode, "shared_quiet_state", lambda: _Quiet())
        island = _island(monkeypatch)
        bounces.clear()
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [], "免打扰期间工作上升沿不许弹"
        # 状态本身照常（读数照常是 DND 规则的另一半）
        assert island._dsh_state == DshState.WORKING.value
    finally:
        island.close()


def test_work_edge_bounce_reads_the_fullscreen_quiet_config(monkeypatch):
    """全屏那一半的弹跳闸必须读宿主配置，不许吃 ``suppression_active`` 的默认参数。

    ``quiet_also_on_fullscreen`` 关掉后全屏不算免打扰（quiet_mode 的口径：判据不
    自己读配置，由调用方给），原先这条闸调 ``suppression_active()`` 吃默认 True，
    于是用户在全屏游戏/视频里开工弹跳永远出不来。口径与
    ``window_alerts.quiet_blocked`` 对齐——从岛自己持有的配置取。
    """
    state = quiet_mode.QuietState()
    state.set_fullscreen(True)
    monkeypatch.setattr(quiet_mode, "shared_quiet_state", lambda: state)

    island = _island(monkeypatch)
    try:
        island.config.set("quiet_also_on_fullscreen", False)
        bounces = []
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [3.0], "关掉「全屏时自动免打扰」后，全屏里的开工弹跳必须照弹"
    finally:
        island.close()

    island = _island(monkeypatch)
    try:
        island.config.set("quiet_also_on_fullscreen", True)
        bounces = []
        monkeypatch.setattr(island, "_bounce", lambda impulse=4.0: bounces.append(impulse))
        island.set_dsh_state(DshState.WORKING.value)
        assert bounces == [], "开关开着时全屏仍等效免打扰：不许弹"
    finally:
        island.close()


# ---------------------------------------------------------- R1-3 squish 横向只鼓不缩
def test_squish_stretch_never_narrows_the_shell(monkeypatch):
    """sy>1（拉伸期）外壳横向必须保持静止宽：内容不随形变，sx<1 会把宽岛的
    头像/状态点画到外壳外（astra 应修 3）。"""
    island = _island(monkeypatch, metrics=["cpu", "mem", "network"],
                     custom_text="x" * 60, info_mode="custom")
    try:
        island._update_size()
        app.processEvents()
        rest_rect, _ = island._squished_capsule_rect()
        assert rest_rect.left() == 6.0
        for sy in (0.85, 1.0, 1.06, 1.12):
            island._squish = sy
            rect, _r = island._squished_capsule_rect()
            assert rect.left() <= 6.0 + 0.01, (
                f"squish={sy} 外壳左缘 {rect.left():.2f} 越过静止左缘 6（横向收缩）")
            assert rect.right() >= rest_rect.right() - 0.01, (
                f"squish={sy} 外壳右缘 {rect.right():.2f} 窄于静止右缘 {rest_rect.right():.2f}")
    finally:
        island.close()


# ---------------------------------------------------------- R1-4 FontChange 几何同步
def test_font_change_commits_geometry_in_normal_mode(monkeypatch):
    """FontChange 清缓存后，普通胶囊的窗口宽必须当刻与行计划一致（astra 应修 4：
    修复前要等 30s 心跳或其他事件才同步，期间绘制与几何脱节）。

    测试必须**真的换字体**（6.1sol 建议 5）：不换字体时新旧自然宽相同，
    删掉 ``_update_size()`` 这行断言也能过——那是假绿。
    """
    island = _island(monkeypatch, metrics=["cpu", "mem"])
    try:
        island.show()
        app.processEvents()
        island._update_size()
        app.processEvents()
        width_before = island.width()
        # 岛的字体来自 _FONT_LAYERS 的像素常量（部件字体不影响它）——把 value 层
        # 改大：字体指纹必变、自然宽真变（前提断言）；再发 FontChange 事件
        monkeypatch.setitem(island_mod._FONT_LAYERS, "value",
                            (24, island_mod._FONT_LAYERS["value"][1]))
        island.changeEvent(QEvent(QEvent.Type.FontChange))
        app.processEvents()
        assert island._row_plan().width != width_before, (
            "前提：字号层变化后自然宽必须真的变化（否则本测试没有判别力）")
        assert island.width() == island._row_plan().width, (
            "FontChange 后窗口宽与行计划宽不一致（几何没有同步提交）")
    finally:
        island.close()


# ---------------------------------------------------------- R1-5 卡片 hover 暂停收起
def test_card_hover_pauses_auto_collapse(monkeypatch):
    """展开卡片：hover 暂停 15s 自动收起，离开重新倒计时（裁决稿 §一-10；
    astra 应修 5——修复前用户正读着卡片也会被定时器收掉）。"""
    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        # 真实序列（6.1sol 终审）：先在 normal 态 enter（单击前鼠标已在岛内），
        # 再 expand——这一序列下鼠标不会再产生 enterEvent，15s 表不得启动
        island.enterEvent(None)
        island.expand_card()
        assert island._card_collapse_timer.isActive() is False, (
            "鼠标已在岛内时展开卡片，自动收起不得启动（用户正读着卡片）")
        island.leaveEvent(None)
        assert island._card_collapse_timer.isActive() is True, (
            "离开卡片必须重新倒计时")
        assert island._card_collapse_timer.interval() == island_mod._CARD_AUTO_COLLAPSE_MS
        # 展开后才把鼠标挪进来：同样要暂停（enter/leave 双向守卫）
        island._card_collapse_timer.stop()
        island.enterEvent(None)
        assert island._card_collapse_timer.isActive() is False
        # 隐藏复位（A1 第二票 R3）：hide 后 _cursor_inside 必须是 False——
        # 否则陈旧 True 会让显示后的 expand_card 误判「鼠标在岛内」不起表
        island.hide()
        app.processEvents()
        assert island._cursor_inside is False
        # S2：hide→show 后自动收起倒计时必须接回（光标不在岛内时）
        island.show()
        app.processEvents()
        assert island._mode == "expanded"
        assert island._card_collapse_timer.isActive() is True, (
            "hide→show 后 15s 自动收起没有恢复（卡片会永远开着）")
    finally:
        island.close()


# ---------------------------------------------------------- R2-1 超宽判决含单位盒
def test_oversize_candidates_use_the_full_double_box_width(monkeypatch):
    """120px 判决必须按「值盒+单位盒」完整口径（6.1sol 应修 2：修复前
    oversize_segment_ids 只量 label+max_text，长单位段绕过判决）。"""
    from PySide6.QtGui import QFont, QFontMetrics
    from pet import island_segments as segments

    metrics = QFontMetrics(QFont("", 13))
    try:
        decl = segments.register_segment(
            id="long_unit", label="",
            format_value=lambda v: "1", max_text="8", unit="MMMMMMMMMMMM")
        assert decl.width_px(metrics) > segments.MAX_SEGMENT_WIDTH_PX, (
            "前提：长单位把完整盒宽推过 120px")
        assert "long_unit" in segments.oversize_segment_ids(metrics), (
            "长单位段必须进超宽候选（判决含单位盒）")
    finally:
        segments.clear_segments()
        assert segments.oversize_segment_ids(metrics) == ()


# ---------------------------------------------------------- R2-2 起拖停淡化
def test_starting_a_drag_stops_the_in_flight_fade(monkeypatch):
    """「先淡化、后起拖」：起拖必须停掉进行中的淡化并跳终点帧（6.1sol 应修 3；
    修复前 _dragging 只拦新淡化，残影在拖拽中继续推进）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPixmap

    island = _island(monkeypatch, metrics=["cpu"])
    try:
        island.show()
        app.processEvents()
        island._update_size()
        app.processEvents()
        pm = QPixmap(max(1, island.width()), 44)
        island._start_content_fade(pm)
        assert island._content_fade_timer is not None
        center = island.geometry().center()

        def mouse(kind, global_pos, buttons=Qt.MouseButton.LeftButton):
            local = island.mapFromGlobal(global_pos)
            return QMouseEvent(kind, QPointF(local), QPointF(global_pos),
                               Qt.MouseButton.LeftButton, buttons,
                               Qt.KeyboardModifier.NoModifier)

        island.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, center))
        far = type(center)(center.x() + 200, center.y() + 120)
        island.mouseMoveEvent(mouse(QEvent.Type.MouseMove, far))
        assert island._dragging is True, "前提：位移超过阈值后进入拖拽"
        assert island._content_fade_timer is None, "起拖必须停掉进行中的淡化"
        assert island._content_fade_t == 1.0
        island.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, far,
                                       buttons=Qt.MouseButton.NoButton))
    finally:
        island.close()
