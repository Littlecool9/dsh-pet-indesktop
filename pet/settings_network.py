# -*- coding: utf-8 -*-
"""设置页「灵动岛第三方指标 / 网络信息」的控件创建 / 行装配 / 保存。

modern_settings_dialog.py 行数预算零余量，所以本功能的控件与行全部在本模块构建，
对话框只做三处接线：import、岛页挂「桌面组件」小节、保存委托。

归属（SETTINGS-CHANGE-GATES 的"归属唯一"）：

- ``island_metrics``（岛上的第三方指标段有序列表）只属于「桌面组件 · 桌面胶囊
  （灵动岛）」——岛的信息槽显示什么，只在岛这一处决策。行来自可信目录里的组件
  声明清单（标准库 JSON），主进程与设置进程读同一份静态 metadata。
- ``network_info_menu_enabled`` 只属于「菜单」——它决定右键菜单里「网络信息」那一项
  显不显示，与岛上的指标段无关。
"""
from __future__ import annotations

from . import island_extension_host
from .config import _clean_island_metrics
from .settings_widgets import SettingRow, ToggleSwitch


def _metric_attr(metric_id: str) -> str:
    """指标开关在对话框上的属性名。"""
    return f"island_{metric_id}_check"


def _extension_rows() -> tuple[tuple[str, str, str, str], ...]:
    """第三方组件行（``(段 id, 行键, 行 label, 行 hint)``）。

    行与岛外观行同层级、同风格（同一个 ``SettingRow`` 装配、同一个"灵动岛指标 ·"
    前缀、同一套显隐依赖），label 与 hint 取自组件自己的声明。顺序 = 声明清单的
    扫描序（用户目录在前、目录名排序），与"谁先注册"无关——两个进程因此得到同一份
    行序，保存后的列表序也不会随进程内的注册顺序漂移。
    """
    rows: list[tuple[str, str, str, str]] = []
    for declaration in island_extension_host.declarations():
        segment_id = declaration.segment_id
        label = declaration.label or segment_id
        provider_note = (
            f"组件暂缺：找不到 {declaration.provider}，这份偏好会保留，"
            "但当前不采样、也不在岛上显示（装回来后自动恢复）。"
            if not declaration.provider_present else
            f"数据来自本机组件 {declaration.provider}（{declaration.source or '来源由组件声明'}）。")
        rows.append((
            segment_id,
            f"island_{segment_id}",
            f"灵动岛指标 · {label}",
            f"第三方组件「{label}」提供的指标段。{provider_note}"
            "单位、最坏读数样本与告警阈值都由组件自己声明，本应用只负责岛上排版、"
            "卡片详情与告警判定；关掉即不采样。",
        ))
    return tuple(rows)


def metric_rows() -> tuple[tuple[str, str, str, str], ...]:
    """全部指标行 = 声明清单里的组件行（**顺序就是写回序**）。"""
    return _extension_rows()


def metric_order() -> tuple[str, ...]:
    """写回 ``island_metrics`` 的典范序（组件按声明序）。"""
    return tuple(row[0] for row in metric_rows())


def _checked_metrics(dialog) -> list:
    """当前配置里的指标列表（走 config 的同一份归一化：脏值/未知 id 的口径只有一处）。"""
    return _clean_island_metrics(dialog.config.get("island_metrics"))


def create_network_controls(dialog) -> None:
    """在对话框上创建本功能的控件（幂等；行由下面的 build_* 装配）。

    建控件的同时记下**本次表单的指标 id 快照**（``_island_metric_controls``）：
    可信目录里的组件可能在窗口打开之后被装上 / 卸掉，而控件只在这一次建。保存必须
    按**这份快照**收集值——按保存当刻的清单收集会去取一个从没建过的控件
    （``getattr`` 抛 AttributeError，整条保存链在写入之前断掉），或者把"表单里根本
    没有的 id"当成"用户没勾"而静默删掉用户的偏好。
    """
    if getattr(dialog, "island_network_check", None) is None:
        selected = _checked_metrics(dialog)
        controlled = metric_order()
        for metric_id in controlled:
            toggle = ToggleSwitch(dialog)
            toggle.setChecked(metric_id in selected)
            setattr(dialog, _metric_attr(metric_id), toggle)
        dialog._island_metric_controls = tuple(controlled)

    if getattr(dialog, "network_info_menu_check", None) is None:
        dialog.network_info_menu_check = ToggleSwitch(dialog)
        dialog.network_info_menu_check.setChecked(
            bool(dialog.config.get("network_info_menu_enabled", True)))


def _form_metric_ids(dialog) -> tuple[str, ...]:
    """本次表单**实际可编辑的**指标 id = 表单快照 ∩ 真的有控件。

    - 快照（``_island_metric_controls``）由 :func:`create_network_controls` 建控件时
      记下，所以它不随窗口打开之后的清单变动而变；
    - 再按"真的有控件"过一遍：快照里有、控件却没了（不该发生，但**保偏好**永远比
      猜"用户没勾"安全），以及调用方自己拼控件、没有快照的兜底路径，都收敛到同一条
      规则——"这一行这次真的可编辑"。

    没有快照时按当刻清单回落，**不按"清单里现在有什么"判**。
    """
    snapshot = getattr(dialog, "_island_metric_controls", None)
    candidates = tuple(snapshot) if snapshot else metric_order()
    return tuple(metric_id for metric_id in candidates
                 if getattr(dialog, _metric_attr(metric_id), None) is not None)


def build_island_network_rows(dialog) -> list[SettingRow]:
    """岛侧行：声明清单里每个第三方组件一行（无组件时为空）。

    每个指标一行：SettingRow 只有一个 label/一个 buddy 控件，多个开关挤一行会让
    后几个开关拿不到可见的标签与可访问名（label.setBuddy 一位一控）。行随域导航
    每次重建（行壳随旧页 deleteLater，控件对象复用）。**没有控件的 id 不建行**：
    清单可能在窗口打开之后变动，那一行的开关并不存在。

    **每行都建在宿主上（``parent=dialog``）**：行壳建出来时还没进卡片，而
    :func:`_install_visibility` 当场就要按依赖位 ``setVisible``——无父控件的
    ``setVisible(True)`` 会当场开出一个顶层窗口。
    """
    create_network_controls(dialog)
    rows = [
        SettingRow(key, title, hint, getattr(dialog, _metric_attr(metric_id), None),
                   parent=dialog)
        for metric_id, key, title, hint in metric_rows()
        if getattr(dialog, _metric_attr(metric_id), None) is not None
    ]
    _install_visibility(dialog)
    return rows


def build_menu_rows(dialog) -> list[SettingRow]:
    """菜单侧一行：右键菜单「网络信息」入口显隐。"""
    create_network_controls(dialog)
    return [
        SettingRow(
            "network_info_menu",
            "「网络信息」菜单入口",
            "右键菜单里显示「网络信息」：公网 IP、IP 属地（及是否在中国大陆）、"
            "Google / GitHub 可达性。只在打开弹窗时取一次（约 1 KB），不轮询；"
            "关掉后菜单里保留该入口并置灰，悬停能看到关闭原因。",
            dialog.network_info_menu_check,
        ),
    ]


def _install_visibility(dialog) -> None:
    """把岛侧显隐依赖接上（岛开关 → 信息槽开关 → 指标行）。

    依赖位（``_visibility_dependencies``）与 ``settings_pet_controls`` 写的那些位
    按 AND 合成，两边互不干扰、与调用顺序无关。信号只连一次；行壳每次域导航重建
    都是新的，故信号回调统一读 ``dialog._island_network_sync`` 上的最新闭包。
    """

    def apply(key: str, visible: bool, dependency: str) -> None:
        dialog._set_setting_rows_visible((key,), visible, dependency=dependency)

    def sync(*_args) -> None:
        island_on = bool(dialog.island_enabled_check.isChecked())
        info_on = bool(dialog.island_info_check.isChecked())
        # 指标行同进同出（都是"信息槽上的附加段"，含第三方组件行）。
        for _metric_id, key, _title, _hint in metric_rows():
            apply(key, island_on and info_on, "island_info_slot_shown")

    dialog._island_network_sync = sync
    if not getattr(dialog, "_island_network_visibility_wired", False):
        dialog._island_network_visibility_wired = True
        for checkbox in (dialog.island_enabled_check, dialog.island_info_check):
            checkbox.toggled.connect(lambda *_a, host=dialog: host._island_network_sync())
    sync()


def save_network_settings(dialog) -> None:
    """_write_config 委托：把指标列表与网络信息菜单开关写回 config。

    写回列表 = **保留配置里的既有顺序** + 新勾选的按典范序追尾：复选框只表达
    "在/不在"（顺序属于配置，列表序 = 用户优先级 = 尾部先折叠）。无条件按典范序
    重写会把用户手改的顺序压回去。

    **只覆盖本次表单真正建过控件的 id**（:func:`_form_metric_ids`）：窗口打开之后
    清单可能变动（用户装 / 卸了组件），那些 id 在表单里没有控件——① 取它的值会
    ``getattr`` 抛 AttributeError，把整条保存链断在写入之前；② 把它当"用户没勾"
    淘汰，会静默删掉用户的偏好。所以"表单没覆盖的 id"一律按磁盘现状保留，顺序也
    留在原位。
    """
    if getattr(dialog, "network_info_menu_check", None) is None:
        return
    covered = _form_metric_ids(dialog)
    checked = {metric_id for metric_id in covered
               if getattr(dialog, _metric_attr(metric_id)).isChecked()}
    kept = [metric_id for metric_id in _checked_metrics(dialog)
            if metric_id not in covered or metric_id in checked]
    dialog.config.set("island_metrics",
                      kept + [m for m in covered if m in checked and m not in kept])
    dialog.config.set("network_info_menu_enabled",
                      bool(dialog.network_info_menu_check.isChecked()))
