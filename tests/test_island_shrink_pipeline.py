# -*- coding: utf-8 -*-
"""灵动岛收缩流水线（P1 Slice D2）的契约测试：纯判定 + 采样联动 + 伸长锚点。

规格（施工单 §D2）把收缩定义成一条**可逆的纯计算**流水线：

1. S1 名字省略（96px 静止上限 → 40px）；
2. S2 名字隐藏（整段去掉，含其后 10px 间距）；
3. S3 尾部整段折 ``+N``（列表尾 = 优先级最低，一次折一段直到 fits；被折段
   **撤销采样订阅**）；
4. S4 custom 主信息省略（96px 右省略；时间/余额/峰谷是定宽主信息，永不省略）；
5. 保底：头像 + 主信息 + 状态点永不折，仍超宽就保持溢出截断。

本文件三层验证：

- **纯判定**（``plan_info_row``）：逐级触发、尾部优先、主信息永不折、逆序恢复；
- **几何**：``+N`` chip 的盒宽/居中/无竖线、三分区锚点。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet import island_layout as layout
from pet import island_segments as isl
from pet.island_layout import (
    LEVEL_FOLD_BASE, LEVEL_NAME_ELIDE, LEVEL_NAME_HIDE, LEVEL_NONE,
    _InfoSeg, anchored_x, apply_shrink, elide_to_width, plan_info_row,
    place_info_segments,
)
_PRIMARY = "primary"
#: 测试用的通用段 id（内置段已整体移除，这里只验布局与收缩）。
_CPU = "alpha"
_MEM = "beta"
_ELLIPSIS = isl.ELLIPSIS


class FakeMetrics:
    """字体度量替身：每字符固定 ``step`` px（只验几何，不碰真实字体）。"""

    def __init__(self, step: int = 10):
        self.step = step

    def horizontalAdvance(self, text) -> int:
        return len(str(text)) * self.step

    def height(self) -> int:
        return 17

    def lineSpacing(self) -> int:
        return 20

    def ascent(self) -> int:
        return 13

    def descent(self) -> int:
        return 4

    def leading(self) -> int:
        return 0

    def averageCharWidth(self) -> int:
        return self.step


FM = FakeMetrics(10)
#: 行首固定件（内容左内边距 + 头像 + 间距）与行尾固定件（状态点 + 间距）。
_LEAD = 19.0
_TRAIL = 18.0
#: 长名字（9 字 = 90px，≤96 静止上限；收到 40px 时变成 "小鱼儿…"）。
_LONG_NAME = "小鱼儿她姐姐姐姐姐"


def _primary(text="12:00", box="88:88", *, elide=0):
    return _InfoSeg(kind="primary", seg_id=_PRIMARY, label="", text=text,
                    box_text=box, state=isl.STATE_OK, elide_px=elide)


def _metric(seg_id, label="", text="24%", box="888%", *, state=isl.STATE_OK):
    return _InfoSeg(kind="metric", seg_id=seg_id, label=label, text=text,
                    box_text=box, state=state)


def _metrics():
    """两个指标段，尾部 = 第二个（列表序 = 优先级降序）。"""
    return [_metric(_CPU, "_CPU"), _metric(_MEM, "内存")]


def _plan(segments, available, *, name=_LONG_NAME):
    return plan_info_row(
        segments, lead_w=_LEAD, trail_w=_TRAIL, name_text=name,
        available_w=available, primary_fm=FM, value_fm=FM, label_fm=FM, name_fm=FM)


def _ids(plan):
    return list(plan.visible)


def _row(plan, segments):
    """把计划套到当刻的段列表上（绘制层走的就是这条路）。"""
    return layout.apply_shrink(plan, segments, primary_fm=FM)


# ------------------------------------------------------------ 纯判定：逐级触发
def test_plan_within_budget_touches_nothing():
    plan = _plan([_primary(), *_metrics()], 10_000)
    assert plan.level == LEVEL_NONE
    assert plan.name == _LONG_NAME
    assert plan.folded == ()
    assert _ids(plan) == [_PRIMARY, _CPU, _MEM]
    assert plan.width <= 10_000


def test_plan_elides_the_name_before_dropping_anything():
    """第一刀是名字省略：段一个不动，名字收到 40px。"""
    plan = _plan([_primary(), *_metrics()], 340)
    assert plan.level == LEVEL_NAME_ELIDE
    assert plan.name.endswith(_ELLIPSIS) and plan.name_w <= 40
    assert plan.folded == ()
    assert _ids(plan) == [_PRIMARY, _CPU, _MEM]
    assert plan.width <= 340


def test_plan_hides_the_name_before_folding_segments():
    plan = _plan([_primary(), *_metrics()], 300)
    assert plan.level == LEVEL_NAME_HIDE
    assert plan.name == "" and plan.name_w == 0
    assert plan.folded == ()
    assert _ids(plan) == [_PRIMARY, _CPU, _MEM]


def test_plan_folds_from_the_tail_and_adds_a_chip():
    """第三级：从列表尾逐个折进 +N（尾 = 用户心里的最低优先级）。"""
    segments = [_primary(), *_metrics()]
    plan = _plan(segments, 250)
    assert plan.level == LEVEL_FOLD_BASE + 1
    assert plan.folded == (_MEM,), "先折尾部那一段"
    assert _ids(plan) == [_PRIMARY, _CPU, "chip"]
    chip = _row(plan, segments)[-1]
    assert chip.kind == "chip" and chip.text == "+1"
    assert plan.width <= 250


def test_plan_keeps_folding_until_it_fits():
    segments = [_primary(), *_metrics()]
    plan = _plan(segments, 200)
    assert plan.folded == (_MEM, _CPU), "折叠顺序 = 段 id 序的严格倒序"
    assert plan.level == LEVEL_FOLD_BASE + 2
    assert _ids(plan) == [_PRIMARY, "chip"]
    assert _row(plan, segments)[-1].text == "+2"


def test_plan_never_folds_the_primary():
    """保底：头像 + 主信息 + 状态点永不折（极端窄屏只溢出截断）。"""
    segments = [_primary(), *_metrics()]
    plan = _plan(segments, 100)
    row = _row(plan, segments)
    assert row[0].seg_id == _PRIMARY, "主信息段永远在第一位"
    assert row[0].text == "12:00", "定宽主信息不做省略"
    assert plan.folded == (_MEM, _CPU)
    assert plan.width > 100, "折无可折：宽度如实溢出，由绘制层截断（不静默吃字）"


def test_plan_elides_the_custom_primary_only_at_the_floor():
    """S4：custom 主信息可省（96px）；时间/余额是定宽主信息，永不动。"""
    custom = _primary(text="今天也在摸鱼今天也在摸鱼", elide=96)
    segments = [custom, *_metrics()]
    plan = _plan(segments, 150)
    assert plan.level == LEVEL_FOLD_BASE + 3, "折尽指标段之后才是主信息省略"
    assert plan.elide_primary is True
    head = _row(plan, segments)[0]
    assert head.text.endswith(_ELLIPSIS) and head.text != custom.text
    assert head.box_text == head.text, "省略后盒宽跟着收（不然白占位）"
    assert FM.horizontalAdvance(head.text) <= 96


def test_plan_leaves_a_fixed_width_primary_intact_at_the_floor():
    segments = [_primary(elide=0), *_metrics()]
    plan = _plan(segments, 150)
    assert plan.elide_primary is False, "定宽主信息不参与省略"
    assert _row(plan, segments)[0].text == "12:00"
    assert plan.level == LEVEL_FOLD_BASE + 2, "没有可省的字段：停在折尽那一级"


def test_plan_is_stateless_so_widening_restores_everything():
    """逆序恢复：同一份输入换个预算就全展开——收缩状态纯计算，不落盘。"""
    segments = [_primary(), *_metrics()]
    narrow = _plan(segments, 200)
    assert narrow.folded == (_MEM, _CPU)
    wide = _plan(segments, 10_000)
    assert wide.level == LEVEL_NONE and wide.folded == ()
    assert _ids(wide) == [_PRIMARY, _CPU, _MEM]
    assert wide.name == _LONG_NAME


def test_plan_without_a_budget_never_shrinks():
    """无屏（拿不到可用宽）：按 0 处理——不收缩，宁可靠 clamp 兜底。"""
    plan = _plan([_primary(), *_metrics()], 0)
    assert plan.level == LEVEL_NONE and plan.folded == ()


def test_plan_without_info_segments_only_shrinks_the_name():
    plan = _plan([], 60, name=_LONG_NAME)
    assert plan.folded == () and plan.visible == ()
    assert plan.width > 0


def test_chip_carries_the_alert_flag_when_a_folded_segment_errors():
    """折叠不埋没告警：被折段里有 error → chip 左侧色点（告警级已从 bool 升格为
    ``""|warn|crit``：error 态一律按 crit 算，见 ``island_layout._folded_alert``）。"""
    segments = [_primary(), _metric(_CPU, "_CPU", "--", "888%", state=isl.STATE_ERROR),
                _metric(_MEM, "内存")]
    plan = _plan(segments, 250)
    assert plan.folded == (_MEM,)
    assert plan.chip_alert == "", "折掉的是内存，_CPU 的 error 还在画"

    plan = _plan(segments, 200)
    assert _CPU in plan.folded and _MEM in plan.folded
    assert plan.chip_alert == isl.ALERT_CRIT


# ------------------------------------------------------------ chip 的落位
def test_place_info_segments_lays_out_a_chip_with_its_own_padding():
    chip = _InfoSeg(kind="chip", seg_id="chip", label="", text="+3",
                    box_text="+3", state=isl.STATE_OK)
    (placement,) = place_info_segments([chip], start_x=10.0, primary_fm=FM,
                                       value_fm=FM, label_fm=FM)
    assert placement.box_x == 10.0, "chip 前不画竖线、不占 19px 槽位"
    assert placement.divider_x is None
    assert placement.box_w == max(26, 2 * 10 + 12), "宽 = 文字宽 + 左右各 6px"
    assert placement.text_x == placement.box_x + (placement.box_w - placement.text_w) / 2.0, \
        "chip 是容器：文字居中，不像字段盒那样右对齐"


def test_place_info_segments_gives_a_wide_chip_a_minimum_width():
    chip = _InfoSeg(kind="chip", seg_id="chip", label="", text="+",
                    box_text="+", state=isl.STATE_OK)
    (placement,) = place_info_segments([chip], start_x=0.0, primary_fm=FM,
                                       value_fm=FM, label_fm=FM)
    assert placement.box_w == 26, "最小 26px（K3 §3.3）"


def test_chip_after_a_metric_still_gets_no_divider():
    segments = [_metric(_CPU, "_CPU"),
                _InfoSeg(kind="chip", seg_id="chip", label="", text="+1",
                         box_text="+1", state=isl.STATE_OK)]
    cpu, chip = place_info_segments(segments, start_x=0.0, primary_fm=FM,
                                    value_fm=FM, label_fm=FM)
    assert cpu.divider_x is None, "首段前不画竖线"
    assert chip.divider_x is None, "chip 前不画竖线（它是收尾标记，不是新数据段）"


# ------------------------------------------------------------ 省略实现
def test_elide_to_width_is_a_binary_search_over_prefixes():
    assert elide_to_width("小鱼儿", 96, FM) == "小鱼儿", "装得下就原样返回"
    assert elide_to_width("小鱼儿她姐姐姐姐姐", 40, FM) == "小鱼儿" + _ELLIPSIS
    assert elide_to_width("小鱼儿", 0, FM) == "", "上限非正：宁可不显示也不越界"
    long_text = "很长" * 500
    assert FM.horizontalAdvance(elide_to_width(long_text, 96, FM)) <= 96


# ------------------------------------------------------------ 错输入护栏
def test_apply_shrink_with_fewer_segments_than_the_plan_folds_never_slices_backwards():
    """计划被拖拽冻结时配置可能已经改小：段比折叠数还少也不许吃错段。"""
    plan = _plan([_primary(), *_metrics()], 200)
    assert len(plan.folded) == 2
    row = _row(plan, [_primary()])               # 只剩主信息（配置刚被改小）
    assert row[0].seg_id == _PRIMARY and row[0].text == "12:00", "主信息永不被折"
    assert _row(plan, []) == ()                  # 连主信息都没有：出空行，不炸


def test_plan_with_an_empty_segment_list_is_still_a_valid_row():
    """无段（信息槽关闭）：计划只有名字与固定件，宽度不小于下限。"""
    plan = _plan([], 500, name="")
    assert plan.visible == () and plan.folded == ()
    assert plan.width >= 120, "极小内容下岛仍要是可点可拖的胶囊"


# ------------------------------------------------------------ 伸长锚点（三分区）
def test_anchored_x_pins_the_left_edge_in_the_left_third():
    # 屏 1200 宽、岛宽 200 在 x=100 → 中心 200 < 400（左 1/3）
    assert anchored_x(x=100, width=200, new_width=600,
                      screen_left=0, screen_width=1200) == 100


def test_anchored_x_pins_the_right_edge_in_the_right_third():
    # 中心 1100 ≥ 800（右 1/3）→ 右缘固定，向左长
    assert anchored_x(x=1000, width=200, new_width=600,
                      screen_left=0, screen_width=1200) == 600


def test_anchored_x_pins_the_center_in_the_middle_third():
    # 中心 600（中间 1/3）→ 中心固定，两侧长
    assert anchored_x(x=500, width=200, new_width=600,
                      screen_left=0, screen_width=1200) == 300


def test_anchored_x_without_screen_info_keeps_the_edge():
    assert anchored_x(x=77, width=200, new_width=600,
                      screen_left=0, screen_width=0) == 77
