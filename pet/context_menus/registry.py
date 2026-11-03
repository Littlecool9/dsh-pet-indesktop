"""Action registration and tree rendering for the shared Menu Action Model."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QWidgetAction

from ..focus_ui import build_focus_menu
from .icons import custom_file_menu_icon, vector_menu_icon
from .quick_launch import add_quick_launch_menu, configured_quick_apps
from .shared import (
    NETWORK_INFO_DISABLED_REASON,
    add_action,
    add_agent_link_menu,
    add_autostart,
    add_balance,
    add_clear_spawned_pets,
    add_drag_physics,
    add_edge_probe,
    add_golden_spin,
    add_harness,
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
    add_spawn_pet,
    add_submenu,
    add_network_info,
    network_info_menu_enabled,
    build_animation_categories,
    build_character_menu,
    build_size_menu,
    build_speed_menu,
)


ACTION_LABELS = {
    "chat": "AI 对话", "look_screen": "看看屏幕",
    "screen_capture": "截图提问",
    "animations_hub": "播放动画", "character": "切换角色", "playback_speed": "播放速率",
    "size": "大小", "drag_physics": "拖动物理", "no_move": "不移动",
    "on_top": "窗口置顶", "autostart": "开机自启",
    "return_corner": "回到右下角", "hide_pet": "隐藏桌宠",
    "spawn_pet": "生小肥鱼", "clear_spawned_pets": "退出子肥鱼",
    "golden_spin": "黄金回旋", "edge_probe": "边缘探头",
    "agent_cost": "显示本轮消费",
    "quick_launch": "快捷启动", "balance": "DeepSeek 余额",
    "proactive_screen": "主动识屏", "todo_panel": "待办提醒",
    "quiet_mode": "免打扰", "focus_mode": "专注模式",
    "network_info": "网络信息",
    "modern_settings": "桌宠设置", "quit": "退出",
}


Builder = Callable[[QMenu, object], object]
Availability = Callable[[object], bool]
Enablement = Callable[[object], bool]


ACTION_ICONS = {
    "chat": "chat", "look_screen": "screen",
    "screen_capture": "size",
    "animations_hub": "play", "character": "character", "playback_speed": "speed",
    "size": "size", "drag_physics": "physics", "no_move": "pause",
    "on_top": "pin", "autostart": "autostart",
    "return_corner": "corner", "hide_pet": "hide",
    "spawn_pet": "spawn", "clear_spawned_pets": "clear",
    "golden_spin": "play", "edge_probe": "corner",
    "agent_cost": "balance",
    "quick_launch": "application", "balance": "balance", "harness": "harness",
    "proactive_screen": "screen", "todo_panel": "todo",
    "quiet_mode": "pause", "focus_mode": "pause",
    "network_info": "web",
    "modern_settings": "settings", "quit": "quit",
    "voice_chime_now": "chat", "voice_chime_toggle": "chat",
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
    disabled_reason: str = "当前功能未启用"


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


def _build_voice_chime_now(menu, pet):
    return add_action(menu, "立即报时", "chat", pet.on_voice_chime_now, close_on_trigger=True)


def _flag_toggle_spec(key: str, on_label: str, off_label: str, icon: str,
                      callback: str):
    """布尔开关菜单项的规约工厂：按配置当前值翻转标签，点击回回调。

    语音报时开关此前把「读配置 → 选标签 → add_action」内联在建造器里，这里
    收成一处；标签翻转、图标、回调与 close_on_trigger 语义逐点
    不变。注意 `enabled` 只影响展示标签，不影响回调可用性（可用性仍由
    `MenuActionSpec.available` 的 `_callback_available` 判定）。
    """
    def _build(menu, pet):
        cfg = getattr(pet, "cfg", None)
        enabled = bool(cfg.get(key, False)) if cfg is not None else False
        return add_action(
            menu, on_label if enabled else off_label, icon,
            getattr(pet, callback), close_on_trigger=True,
        )

    return _build


def _network_info_enabled(pet) -> bool:
    """「网络信息」入口的运行时启用态：设置里开着才可用（默认开）。

    **只影响 enabled，不影响 available**：关掉开关时入口保留布局位置、渲染成
    "灰掉 + 说明"（CONTEXT.md 的 Runtime Disabled），不把节点从菜单树里过滤掉——
    过滤只用于"能力不可用"，本例里就是回调缺失（纯桌宠变体）。
    """
    return network_info_menu_enabled(pet)


_build_voice_chime_toggle = _flag_toggle_spec(
    "voice_chime_enabled", "关闭语音报时", "启用语音报时", "chat",
    "on_toggle_voice_chime",
)

class MenuActionRegistry:
    """Resolve capability-aware action IDs and render a resolved menu tree."""

    def __init__(self) -> None:
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
            "drag_physics": MenuActionSpec(add_drag_physics),
            "no_move": MenuActionSpec(add_no_move),
            "on_top": MenuActionSpec(add_on_top),
            "autostart": MenuActionSpec(lambda menu, pet: add_autostart(menu, pet)),
            "return_corner": MenuActionSpec(add_return_corner),
            "hide_pet": MenuActionSpec(add_hide_pet),
            "spawn_pet": MenuActionSpec(add_spawn_pet, _callback_available("on_spawn_pet")),
            "clear_spawned_pets": MenuActionSpec(
                add_clear_spawned_pets,
                _callback_available("on_clear_spawned_pets"),
            ),
            # 始终可用：消费统计与其它开关无关。
            "agent_cost": MenuActionSpec(add_agent_cost),
            "golden_spin": MenuActionSpec(
                add_golden_spin,
                _callback_available("trigger_golden_spin"),
            ),
            "edge_probe": MenuActionSpec(add_edge_probe),
            "quick_launch": MenuActionSpec(
                lambda menu, pet: add_quick_launch_menu(menu, pet.cfg),
                enabled=lambda pet: bool(configured_quick_apps(pet.cfg)),
                disabled_reason="尚未配置快捷启动应用",
            ),
            "balance": MenuActionSpec(add_balance, _callback_available("on_show_balance")),
            "harness": MenuActionSpec(add_harness, _callback_available("on_open_chat")),
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
            "voice_chime_now": MenuActionSpec(
                _build_voice_chime_now, _callback_available("on_voice_chime_now")
            ),
            "voice_chime_toggle": MenuActionSpec(
                _build_voice_chime_toggle, _callback_available("on_toggle_voice_chime")
            ),
            # 天气：回调缺失 = 能力不可用（隐藏）；开关关掉 = 运行时置灰、位置保留
            # （CONTEXT.md 的 Capability Unavailable / Runtime Disabled 口径）。
            "network_info": MenuActionSpec(
                add_network_info,
                _callback_available("on_network_info"),
                enabled=_network_info_enabled,
                disabled_reason=NETWORK_INFO_DISABLED_REASON,
            ),
            "quit": MenuActionSpec(add_quit),
        }

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._specs)

    def available_ids(self, pet) -> frozenset[str]:
        return frozenset(
            action_id
            for action_id, spec in self._specs.items()
            if spec.available(pet)
        )

    def enabled_ids(self, pet) -> frozenset[str]:
        return frozenset(
            action_id
            for action_id, spec in self._specs.items()
            if spec.available(pet) and spec.enabled(pet)
        )

    def disabled_reason(self, action_id: str) -> str:
        spec = self._specs.get(action_id)
        return spec.disabled_reason if spec is not None else "当前不可用"

    def default_icon(self, action_id: str) -> str:
        return ACTION_ICONS.get(action_id, "")

    def label(self, action_id: str) -> str:
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
                        action.setToolTip(self.disabled_reason(action_id))
                        if isinstance(action, QWidgetAction) and action.defaultWidget() is not None:
                            action.defaultWidget().setEnabled(False)
            rendered += 1
            if section:
                previous_section = section


MENU_ACTIONS = MenuActionRegistry()
