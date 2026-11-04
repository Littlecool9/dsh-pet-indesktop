# -*- coding: utf-8 -*-
"""「DeepSeek Harness」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_action, add_submenu
from . import harness_launcher

MODULE_ID = "harness"
LABEL = "DeepSeek Harness"
ICON = "harness"


def _dialog_parent(pet):
    """模态框父窗：宿主（SpriteMenuFacade）自报 ``dialog_parent``，窗口路径用自己。"""
    return getattr(pet, "dialog_parent", None) or pet


def _available(pet) -> bool:
    return callable(getattr(pet, "on_open_chat", None))


def add_harness(menu, pet, *, icons: bool = True):
    """DeepSeek Harness 子菜单：启动 web / 启动桌面端 / 重启 / 停止。"""
    start_icon = ICON if icons else None
    submenu = add_submenu(menu, LABEL, start_icon)

    def _launch(action: str = "start", target: str = "auto") -> None:
        # 父窗口在点击时解析：宿主可能在菜单关闭后被回收，这里只读它自报的面。
        harness_launcher.launch_harness_gui(
            _dialog_parent(pet), action=action, target=target
        )

    # 全部 close_on_trigger：重启/停止的确认框是模态框，必须在原生菜单跟踪
    # 会话结束之后弹出。启动分双目标；重启/停止只作用于 web 服务进程。
    add_action(submenu, "启动 dsh web 界面", start_icon,
               lambda: _launch("start", "web"),
               close_on_trigger=True)
    add_action(submenu, "启动桌面端界面", start_icon,
               lambda: _launch("start", "desktop"),
               close_on_trigger=True)
    add_action(
        submenu, "重启服务", "play" if icons else None,
        lambda: _launch("restart"),
        close_on_trigger=True,
    )
    add_action(
        submenu, "停止服务", "quit" if icons else None,
        lambda: _launch("stop"),
        close_on_trigger=True,
    )
    return submenu


def actions() -> dict[str, MenuActionSpec]:
    return {
        MODULE_ID: MenuActionSpec(
            add_harness,
            available=_available,
            label=LABEL,
            icon=ICON,
        ),
    }


__all__ = ["add_harness", "actions"]
