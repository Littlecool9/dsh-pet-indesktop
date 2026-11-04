# -*- coding: utf-8 -*-
"""「Agent 联动」右键菜单条目（字符串入口，两个进程都可只读加载）。"""
from __future__ import annotations

from ...context_menus.registry import MenuActionSpec
from ...context_menus.shared import add_submenu

MODULE_ID = "agent_link"
ACTION_ID = "agent_link"
LABEL = "Agent 联动"


def add_agent_link_menu(menu, pet) -> None:
    """Agent 联动二级菜单（4 个 Agent 独立开关 + 自定义 Agent 三级子菜单）。

    失败/拒绝由宿主 ``toggle_agent_link`` 自动回滚勾选态。
    """
    sub = add_submenu(menu, LABEL, None)
    agent_cfg = dict(pet.cfg.get("agent_link", {}))
    for agent_key, agent_label in (
        ("dsh", "DeepSeek Harness (DSH)"),
        ("claude", "Claude Code"),
        ("cursor", "Cursor"),
        ("opencode", "OpenCode"),
    ):
        act = sub.addAction(agent_label)
        act.setCheckable(True)
        act.setChecked(bool(agent_cfg.get(agent_key, False)))
        act.toggled.connect(lambda on, k=agent_key, a=act: pet.toggle_agent_link(k, on, a))
    # 自定义联动 Agent（config.json 的 agent_link.custom_agents，只读监听）：
    # 收进三级子菜单，避免用户配了多个自定义通道后把联动菜单撑长。
    custom_items = [
        item for item in (agent_cfg.get("custom_agents") or [])
        if str(item.get("key") or "")
    ]
    if custom_items:
        custom_sub = add_submenu(sub, "自定义联动 Agent", None)
        for item in custom_items:
            key = str(item.get("key"))
            act = custom_sub.addAction(str(item.get("name") or key))
            act.setCheckable(True)
            act.setChecked(bool(agent_cfg.get(key, False)))
            act.toggled.connect(lambda on, k=key, a=act: pet.toggle_agent_link(k, on, a))


def actions() -> dict[str, MenuActionSpec]:
    return {
        ACTION_ID: MenuActionSpec(
            add_agent_link_menu,
            label=LABEL,
        ),
    }


__all__ = ["actions", "add_agent_link_menu"]
