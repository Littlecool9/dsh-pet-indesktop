# -*- coding: utf-8 -*-
"""「Agent 联动」模块的配置 schema（Qt-free，由 ``pet.module_config`` 惰性加载）。

``agent_link`` 仍是全局配置块（落主 ``config.json``，键名/路由不变），默认值与
清洗随功能一起搬进模块：删掉模块 = 删目录 + 删 ``MODULES`` 那一行。
"""
from __future__ import annotations

import re
from typing import Any

from ..base import ModuleConfigSchema

KEY = "agent_link"

# 内置联动 Agent 键：custom_agents 的 key 不得与之重复
_BUILTIN_KEYS = ("dsh", "claude", "cursor", "opencode")
# 自定义联动 Agent 条目上限（防配置文件被塞爆）
_CUSTOM_AGENT_MAX = 8

# DSH 联动线减法（2026-10）退役的 agent_link 子键：事件汇报概率门
# （report_gates 及旧布尔/百分比前身）、卡住检测、行为模式检测、探索看门狗。
# 读入即丢弃，不再写回。
_REMOVED_KEYS = (
    "report_gates",
    "notify_state", "notify_activity", "notify_approval", "notify_done",
    "notify_exec_failed", "report_probability",
    "stuck_detect", "stuck_worried_threshold", "stuck_intervene_threshold",
    "stuck_window_seconds", "stuck_cooldown_seconds", "stuck_reminder_text",
    "pattern_detect", "pattern_w6_control", "pattern_w10_warn",
    "pattern_w10_control", "pattern_macro_w6_explore", "pattern_macro_w6_action",
    "pattern_macro_w10_explore", "pattern_macro_w10_action",
    "pattern_min_steps_between", "pattern_cooldown_seconds",
    "exploration_watchdog_enabled", "exploration_watchdog_warning_threshold",
    "exploration_watchdog_control_threshold", "exploration_watchdog_cooldown_steps",
    "exploration_watchdog_early_grace_minutes", "exploration_watchdog_long_run_minutes",
    "exploration_watchdog_long_think_seconds",
)


def _float_or_default(value: Any, default: float, low: float, high: float) -> float:
    """与 ``Config._float_or_default`` 同口径：NaN/溢出/非数值回默认，否则夹取。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if number != number:  # NaN：夹取夹不出来的脏值，回默认
        return default
    return max(low, min(high, number))


def default_agent_link_data() -> dict:
    return {
        "dsh": False,
        "claude": False,
        "cursor": False,
        "opencode": False,
        # 自定义联动 Agent（协议见 docs/AGENT_LINK_PROTOCOL.md §4）：只读监听
        # 用户指定的事件文件，不写外部配置、无需授权弹窗，默认空
        "custom_agents": [],
        # 音效配置
        "sound_enabled": False,
        "sound_start_path": "builtin:agent-start",
        "sound_done_path": "builtin:agent-done",
        "sound_error_path": "builtin:agent-error",
        "sound_volume": 0.65,
        "sound_cooldown_seconds": 2.0,
        "sound_start_enabled": True,
        "sound_done_enabled": True,
        "sound_error_enabled": True,
    }


def clean_custom_agents(raw: Any) -> list[dict]:
    """清洗自定义联动 Agent 列表（agent_link.custom_agents）。

    条目 {key, name, path}：key 为小写标识（不得与内置键/其他条目重复），
    name 为显示名（缺省用 key），path 为事件文件路径（支持 ~，允许暂不存在）。
    非法条目直接丢弃，超出上限截断。"""
    if not isinstance(raw, list):
        return []
    result: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if len(result) >= _CUSTOM_AGENT_MAX:
            break
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", key):
            continue
        if key in _BUILTIN_KEYS or key in seen:
            continue
        path = str(item.get("path") or "").strip()[:500]
        if not path:
            continue
        name = str(item.get("name") or "").strip()[:50] or key
        seen.add(key)
        result.append({"key": key, "name": name, "path": path})
    return result


def clean_agent_link_data(raw: Any) -> dict:
    defaults = default_agent_link_data()
    if not isinstance(raw, dict):
        return dict(defaults)
    result = dict(defaults)
    # 保留传入的额外合法键（例如 thinking_text, thinking_texts 等）
    result.update(raw)
    result["custom_agents"] = clean_custom_agents(raw.get("custom_agents"))
    for key in (
        "dsh",
        "claude",
        "cursor",
        "opencode",
        "sound_enabled",
        "sound_start_enabled",
        "sound_done_enabled",
        "sound_error_enabled",
    ):
        if key in raw:
            result[key] = bool(raw[key])
    for key in ("sound_start_path", "sound_done_path", "sound_error_path"):
        if key in raw:
            val = str(raw[key] or "").strip()[:500]
            result[key] = val or defaults[key]
    if "sound_volume" in raw:
        result["sound_volume"] = _float_or_default(
            raw.get("sound_volume"), defaults["sound_volume"], 0.0, 1.0)
    if "sound_cooldown_seconds" in raw:
        result["sound_cooldown_seconds"] = _float_or_default(
            raw.get("sound_cooldown_seconds"),
            defaults["sound_cooldown_seconds"], 0.0, 30.0,
        )
    # 减法后退役的键（概率门 / 卡住检测 / 行为模式 / 探索看门狗，含它们的旧
    # 布尔/百分比前身）：读入即丢弃，保存时不再写回，配置里不留死键。
    for dead_key in _REMOVED_KEYS:
        result.pop(dead_key, None)
    return result


def _normalize(data: dict) -> None:
    data[KEY] = clean_agent_link_data(data.get(KEY))


SCHEMA = ModuleConfigSchema(
    defaults={KEY: default_agent_link_data()},
    normalize=_normalize,
    global_keys=(KEY,),
    normalize_on_reload=True,
)

__all__ = [
    "KEY", "SCHEMA",
    "clean_agent_link_data", "clean_custom_agents", "default_agent_link_data",
]
