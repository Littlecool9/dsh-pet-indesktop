"""Action registration and tree rendering for the shared Menu Action Model."""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QWidgetAction

from ..focus_ui import build_focus_menu
from .icons import custom_file_menu_icon, vector_menu_icon
from .quick_launch import add_quick_launch_menu, configured_quick_apps
from .shared import (
    add_action,
    add_agent_link_menu,
    add_autostart,
    add_balance,
    add_edge_probe,
    add_hide_pet,
    add_look_screen,
    add_agent_cost,
    add_no_move,
    add_on_top,
    add_proactive_menu,
    add_quiet_mode_menu,
    add_quit,
    add_return_corner,
    add_screen_capture_menu,
    add_submenu,
    build_animation_categories,
    build_character_menu,
    build_size_menu,
    build_speed_menu,
)


ACTION_LABELS = {
    "chat": "AI 对话", "look_screen": "看看屏幕",
    "screen_capture": "截图提问",
    "animations_hub": "播放动画", "character": "切换角色", "playback_speed": "播放速率",
    "size": "大小", "no_move": "不移动",
    "on_top": "窗口置顶", "autostart": "开机自启",
    "return_corner": "回到右下角", "hide_pet": "隐藏桌宠",
    "edge_probe": "边缘探头",
    "agent_cost": "显示本轮消费",
    "quick_launch": "快捷启动", "balance": "DeepSeek 余额",
    "proactive_screen": "主动识屏", "todo_panel": "待办提醒",
    "quiet_mode": "免打扰", "focus_mode": "专注模式",
    "modern_settings": "桌宠设置", "quit": "退出",
}


Builder = Callable[[QMenu, object], object]
Availability = Callable[[object], bool]
Enablement = Callable[[object], bool]


ACTION_ICONS = {
    "chat": "chat", "look_screen": "screen",
    "screen_capture": "size",
    "animations_hub": "play", "character": "character", "playback_speed": "speed",
    "size": "size", "no_move": "pause",
    "on_top": "pin", "autostart": "autostart",
    "return_corner": "corner", "hide_pet": "hide",
    "edge_probe": "corner",
    "agent_cost": "balance",
    "quick_launch": "application", "balance": "balance", "harness": "harness",
    "proactive_screen": "screen", "todo_panel": "todo",
    "quiet_mode": "pause", "focus_mode": "pause",
    "modern_settings": "settings", "quit": "quit",
}

CUSTOM_ICON_CHOICES = (
    ("默认图标", "default"), ("无图标", "none"),
    ("对话", "chat"), ("屏幕", "screen"), ("播放", "play"),
    ("角色", "character"), ("速度", "speed"), ("尺寸", "size"),
    ("桌宠", "pet"), ("交互", "interaction"), ("置顶", "pin"),
    ("隐藏", "hide"), ("应用", "application"), ("余额", "balance"),
    ("清除", "clear"), ("网页", "web"),
    ("自动化", "automation"), ("设置", "settings"), ("待办", "todo"),
)


@dataclass(frozen=True)
class MenuActionSpec:
    build: Builder
    available: Availability = lambda _pet: True
    enabled: Enablement = lambda _pet: True
    disabled_reason: str | Callable[[object], str] = "当前功能未启用"
    # 模块自带条目：标签/图标由模块声明，核心不维护第二份。
    label: str = ""
    icon: str = ""


def _callback_available(name: str) -> Availability:
    return lambda pet: callable(getattr(pet, name, None))


def _build_chat(menu, pet):
    return add_action(menu, "AI 对话", "chat", pet.on_open_chat, close_on_trigger=True)


def _build_animations(menu, pet):
    submenu = add_submenu(menu, "播放动画", "play")
    build_animation_categories(submenu, pet, icons=False, leaf_role_icons=True)
    return submenu


def _build_settings(menu, pet):
    return add_action(menu, "桌宠设置", "settings", pet.on_open_modern_settings, close_on_trigger=True)


def _build_todo_panel(menu, pet):
    return add_action(menu, "待办提醒", "todo", pet.on_open_todo_panel, close_on_trigger=True)


class MenuActionRegistry:
    """Resolve capability-aware action IDs and render a resolved menu tree."""

    def __init__(self) -> None:
        self._module_action_ids: set[str] = set()
        self._modules_merged = False
        self._specs = {
            "chat": MenuActionSpec(_build_chat, _callback_available("on_open_chat")),
            "look_screen": MenuActionSpec(add_look_screen, _callback_available("on_look_screen")),
            # 「截图」单一入口（框选识屏）：动作在覆盖层松手后的动作条上选，
            # 注册表这一层只表达"宿主有没有这套面"。
            "screen_capture": MenuActionSpec(
                add_screen_capture_menu, _callback_available("on_screen_capture")
            ),
            "animations_hub": MenuActionSpec(_build_animations),
            "character": MenuActionSpec(lambda menu, pet: build_character_menu(menu, pet)),
            "playback_speed": MenuActionSpec(lambda menu, pet: build_speed_menu(menu, pet)),
            "size": MenuActionSpec(lambda menu, pet: build_size_menu(menu, pet)),
            "no_move": MenuActionSpec(add_no_move),
            "on_top": MenuActionSpec(add_on_top),
            "autostart": MenuActionSpec(lambda menu, pet: add_autostart(menu, pet)),
            "return_corner": MenuActionSpec(add_return_corner),
            "hide_pet": MenuActionSpec(add_hide_pet),
            # 始终可用：消费统计与其它开关无关。
            "agent_cost": MenuActionSpec(add_agent_cost),
            "edge_probe": MenuActionSpec(add_edge_probe),
            "quick_launch": MenuActionSpec(
                lambda menu, pet: add_quick_launch_menu(menu, pet.cfg),
                enabled=lambda pet: bool(configured_quick_apps(pet.cfg)),
                disabled_reason="尚未配置快捷启动应用",
            ),
            "balance": MenuActionSpec(add_balance, _callback_available("on_show_balance")),
            "agent_link": MenuActionSpec(add_agent_link_menu),
            "proactive_screen": MenuActionSpec(
                add_proactive_menu,
                lambda pet: sys.platform == "win32" and callable(getattr(pet, "on_open_chat", None)),
            ),
            # 免打扰：进程级状态，任何宿主（PetWindow / SpriteMenuFacade）都可用，
            # 不做能力判定——菜单里永远给得出入口，用户不必先找开关。
            "quiet_mode": MenuActionSpec(add_quiet_mode_menu),
            "focus_mode": MenuActionSpec(build_focus_menu),
            "modern_settings": MenuActionSpec(
                _build_settings, _callback_available("on_open_modern_settings")
            ),
            "todo_panel": MenuActionSpec(
                _build_todo_panel, _callback_available("on_open_todo_panel")
            ),
            "quit": MenuActionSpec(add_quit),
        }

    # ---- 模块菜单条目（惰性合并；设置进程同样只读清单/菜单入口）------------
    def _merge_module_specs(self) -> None:
        if self._modules_merged:
            return
        self._modules_merged = True
        try:
            from ..modules import MODULES
            from ..modules.registry import ModuleRegistry

            specs = ModuleRegistry.from_packages(MODULES, tolerant=True).menu_action_specs()
        except Exception:
            logging.exception("汇总模块菜单入口失败（菜单按内置动作继续）")
            return
        conflicts = sorted(action_id for action_id in specs if action_id in self._specs)
        if conflicts:
            raise ValueError("模块菜单动作与内置动作 id 冲突：" + "、".join(conflicts))
        self._specs.update(specs)
        self._module_action_ids.update(specs)

    def reset_module_specs(self) -> None:
        """作废已合并的模块条目并允许下次访问重读 ``MODULES``（测试/热重载）。"""
        for action_id in self._module_action_ids:
            self._specs.pop(action_id, None)
        self._module_action_ids.clear()
        self._modules_merged = False

    @property
    def ids(self) -> frozenset[str]:
        self._merge_module_specs()
        return frozenset(self._specs)

    def available_ids(self, pet) -> frozenset[str]:
        self._merge_module_specs()
        return frozenset(
            action_id
            for action_id, spec in self._specs.items()
            if spec.available(pet)
        )

    def enabled_ids(self, pet) -> frozenset[str]:
        self._merge_module_specs()
        return frozenset(
            action_id
            for action_id, spec in self._specs.items()
            if spec.available(pet) and spec.enabled(pet)
        )

    def disabled_reason(self, action_id: str, pet=None) -> str:
        self._merge_module_specs()
        spec = self._specs.get(action_id)
        if spec is None:
            return "当前不可用"
        reason = spec.disabled_reason
        if callable(reason):
            try:
                return str(reason(pet))
            except Exception:
                logging.exception("解析菜单置灰原因失败：%s", action_id)
                return "当前不可用"
        return str(reason)

    def default_icon(self, action_id: str) -> str:
        self._merge_module_specs()
        spec = self._specs.get(action_id)
        if spec is not None and spec.icon:
            return spec.icon
        return ACTION_ICONS.get(action_id, "")

    def label(self, action_id: str) -> str:
        self._merge_module_specs()
        spec = self._specs.get(action_id)
        if spec is not None and spec.label:
            return spec.label
        return ACTION_LABELS.get(action_id, action_id)

    def icon(self, widget, action_id: str, override=None) -> QIcon:
        """Resolve semantic or local-file presentation with a safe fallback."""
        if isinstance(override, dict) and override.get("kind") == "file":
            custom = custom_file_menu_icon(widget, override)
            if not custom.isNull():
                return custom
            override = None
        if override == "none":
            return QIcon()
        name = str(override or self.default_icon(action_id) or "")
        return vector_menu_icon(widget, name) if name else QIcon()

    def populate(self, menu: QMenu, pet, nodes, *, enabled_actions=None) -> None:
        self._merge_module_specs()
        enabled = frozenset(enabled_actions) if enabled_actions is not None else self.enabled_ids(pet)
        explicit_separators = any(node.get("type") == "separator" for node in nodes)
        previous_section = None
        rendered = 0
        for node in nodes:
            if node.get("type") == "separator":
                if rendered and menu.actions() and not menu.actions()[-1].isSeparator():
                    menu.addSeparator()
                previous_section = None
                continue
            section = node.get("section")
            if (
                not explicit_separators
                and rendered and section and previous_section and section != previous_section
            ):
                menu.addSeparator()
            built = None
            if node.get("type") == "submenu":
                submenu = add_submenu(
                    menu,
                    str(node.get("alias") or node.get("label") or ""),
                )
                self.populate(
                    submenu, pet, node.get("children", ()), enabled_actions=enabled,
                )
                built = submenu
                if "icon" in node:
                    submenu.menuAction().setIcon(
                        self.icon(menu, str(node.get("id") or ""), node.get("icon"))
                    )
            else:
                action_id = str(node.get("id") or "")
                spec = self._specs.get(action_id)
                if spec is not None:
                    built = spec.build(menu, pet)
                    action = built.menuAction() if isinstance(built, QMenu) else built
                    alias = str(node.get("alias") or "").strip()
                    if alias and action is not None:
                        action.setText(alias)
                        if isinstance(action, QWidgetAction):
                            widget = action.defaultWidget()
                            setter = getattr(widget, "set_title", None)
                            if callable(setter):
                                setter(alias)
                    if action is not None and "icon" in node:
                        action.setIcon(self.icon(menu, action_id, node.get("icon")))
                    if action is not None and action_id not in enabled:
                        action.setEnabled(False)
                        action.setToolTip(self.disabled_reason(action_id, pet))
                        if isinstance(action, QWidgetAction) and action.defaultWidget() is not None:
                            action.defaultWidget().setEnabled(False)
            rendered += 1
            if section:
                previous_section = section


MENU_ACTIONS = MenuActionRegistry()
