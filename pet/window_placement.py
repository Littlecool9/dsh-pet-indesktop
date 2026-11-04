"""Window placement helpers for runtime markers and multi-instance avoidance.

The functions in this module keep the runtime-marker policy independent from the
Qt window implementation.  PetWindow retains thin compatibility methods that
pass itself as the host, so existing callers and test patches continue to work.

多显示器活动区域也在这里：``desktop_area()`` 取一次拖拽的桌面快照
（``DesktopArea``），``band_bounds()`` 按宠物当前所在的屏幕带收窄它，
``move_window_towards`` / ``throw_bounds`` 在有快照时用它、没有快照时逐位退回
本屏语义（单屏用户与漫游/落位/边缘探头不受影响）。见
``docs/PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md``。
"""

from __future__ import annotations

from typing import Any

import logging

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

from . import catalog

from . import slot_manager as slot_manager_mod


def pid_alive(pid: int) -> bool:
    """Check whether a process is alive using the platform-aware slot manager."""
    return slot_manager_mod.pid_alive(pid)


def runtime_marker_versioned(host: Any) -> bool:
    """本窗是否用版本化 runtime 标记名。

    4.4b：进程内多窗常开化（``experimental_single_process_spawn`` 键删除）——
    同 pid 多窗恒可能存在，故**恒用** ``pet-runtime-v2-<pid>-slot-<N>.json``
    （旧名 ``runtime-<pid>.json`` 无法区分同进程的多个窗）。读取侧
    （``slot_manager.read_live_instances``）同时认两种命名，回滚兼容不变。
    """
    return True


def write_runtime_marker(host: Any) -> None:
    """Register the host's current position for later instances to avoid."""
    slot_manager_mod.write_runtime_marker(
        host.cfg.dir,
        host.cfg.instance_id,
        host.x(),
        host.y(),
        host._w,
        host._h,
        versioned=runtime_marker_versioned(host),
    )


# ================================================================ 尺寸


def screen_available(host, screen_name: str | None = None):
    """返回指定或窗口所在屏幕；macOS 上 host.screen() 失效时兜底主屏。"""
    if screen_name:
        for screen in QGuiApplication.screens():
            if screen.name() == screen_name:
                return screen
    scr = host.screen()
    if scr is None:
        scr = QGuiApplication.primaryScreen()
    return scr


def visible_content_rect(host) -> QRect:
    """Return the current visible character bounds in global coordinates.

    The pet window includes a transparent canvas and landing padding. The
    alpha mask is the source of truth for the actual visible character, so
    other windows can be placed beside the character instead of beside the
    transparent canvas.
    """
    frame_rect = host.frameGeometry()
    local_rect = host.character_local_region()
    if not local_rect.isEmpty():
        return QRect(frame_rect.topLeft() + local_rect.topLeft(), local_rect.size())
    mask = host.mask()
    if not mask.isEmpty():
        local_rect = mask.boundingRect()
        if not local_rect.isEmpty():
            return QRect(frame_rect.topLeft() + local_rect.topLeft(), local_rect.size())
    return frame_rect


def bubble_anchor_rect(host) -> QRect:
    """气泡定位锚点：碰撞稳定边界（当前动画各帧轮廓的并集）换算到全局坐标。

    不能用当前帧轮廓（visible_content_rect 的 _mask_bounds 分支）做气泡
    锚点——待机动画每帧的 alpha 包围盒都在小幅晃动，气泡每秒重放
    一次就会跟着每秒跳一次（实机探针实测：鱼静止时气泡每秒 ±10px 抖动、
    偶发 40px 候选位跳变）。并集边界在同一段动画内恒定，气泡只在鱼真正
    移动/换动画/缩放时才挪。轮廓还没算出来时回退当前帧轮廓。
    """
    local = getattr(host, "_collision_local_bounds", None)
    if local is None or local.isEmpty():
        return host.visible_content_rect()
    frame_rect = host.frameGeometry()
    return QRect(frame_rect.topLeft() + local.topLeft(), local.size())


def _move_towards(host, x: float, y: float) -> None:
    """经统一出口落窗（虚拟窗口坐标）；轻量桩没有该出口时回退直接 move。"""
    mover = getattr(host, '_move_window_towards', None)
    if callable(mover):
        mover(x, y)
    else:
        host.move(int(round(x)), int(round(y)))


def _default_corner_pos(host, avail) -> tuple[int, int]:
    """默认右下角落位（虚拟窗口坐标）。

    有稳定身体框时按角色语义：身体右缘距可用区 CORNER_MARGIN、脚底贴
    可用区底。旧算式量的是画布窗口，实际残留 = CORNER_MARGIN + 素材透明
    边距（实测右侧 178px，而 CORNER_MARGIN 意图只有 24px）。无身体框
    （轻量桩/未声明 body_box 的角色包回退全窗口）时保持旧算式逐像素一致。
    """
    sbr_fn = getattr(host, '_stable_body_local_rect', None)
    sbr = sbr_fn() if callable(sbr_fn) else None
    if sbr is not None and (sbr.width(), sbr.height()) != (host._w, host._h):
        x = avail.right() - catalog.CORNER_MARGIN + 1 - sbr.x() - sbr.width()
        y = avail.bottom() + 1 - sbr.y() - sbr.height()
        return int(x), int(y)
    return (avail.right() - host._w - catalog.CORNER_MARGIN,
            avail.bottom() - host._h)


def save_position(host) -> None:
    """以"窗口中心相对屏幕可用区的比例"持久化位置（分辨率变化后仍正确）。
    等待目标副屏上线期间（_awaiting_saved_screen 非空）不写位置/屏名：
    当前只是临时落脚主屏，写回会把保存的副屏坐标永久覆盖。"""
    scr = host._screen_available()
    avail = scr.availableGeometry()
    if avail.width() <= 0 or avail.height() <= 0:
        return
    geometry = {'facing': host.facing, 'scale': host.scale}
    if not getattr(host, '_awaiting_saved_screen', None):
        # 存"虚拟窗口中心"比例：贴边时窗口被钳在工作区内，实际位置 + 绘制
        # 偏移才是角色的自然位置；偏移为零时与旧算式（窗口中心）逐像素一致。
        vp_fn = getattr(host, '_virtual_pos', None)
        vp = vp_fn() if callable(vp_fn) else None
        cx = (vp.x() if vp is not None else host.x()) + host._w / 2
        cy = (vp.y() if vp is not None else host.y()) + host._h / 2
        geometry.update(rx=(cx - avail.left()) / avail.width(),
                        ry=(cy - avail.top()) / avail.height(), screen_name=scr.name())
    writer = getattr(host.cfg, 'save_geometry', None)
    if callable(writer):
        token = getattr(host, '_profile_generation', None)
        if token is None or not writer(geometry, token):
            return
    else:
        for key, value in geometry.items():
            host.cfg.set(key, value)
        host.cfg.save()
    _marker_fn = getattr(host, '_write_runtime_marker', None)
    if callable(_marker_fn):
        _marker_fn()


def go_default_corner(host) -> None:
    # 用户明确要求回右下角 = 手动位置决策，撤销"等副屏上线自动恢复"
    _disarm = getattr(host, '_disarm_screen_restore_retry', None)
    if callable(_disarm):
        _disarm()
    # Position can still be written by the animation interpolation timer or
    # drag-physics timer after a direct move. Stop both first, otherwise the
    # pet briefly reaches the corner and is immediately snapped back.
    host._cancel_move()
    host._stop_physics()
    host._drag_target = None
    scr = host._screen_available()
    avail = scr.availableGeometry()
    x, y = _default_corner_pos(host, avail)
    logging.info('回到右下角 screen=%s avail=(%d,%d,%d,%d) dpr=%s -> (%d,%d)',
                 scr.name(), avail.left(), avail.top(), avail.right(),
                 avail.bottom(), scr.devicePixelRatio(), x, y)
    _move_towards(host, x, y)
    host._save_position()
