# -*- coding: utf-8 -*-
"""Config 键白名单收口测试（批3 子项3）。

pet/config.py 里 __init__ 的默认值 dict（约 498-566 行）与 reload() 的白名单
元组（约 656-691 行）是两份独立维护的键列表。本测试把现状文档化并加护栏：

实测两集合**不一致**（现状文档化，不修产品代码）：
- 默认值 dict 共 80 键；reload 白名单共 75 键。
- 差异 = 默认值多出 4 键：{version, proactive_screen, agent_link, chat}。
  这 4 键在 reload() 里走专门路径（version 末尾强制回写 4；
  proactive_screen / agent_link / chat 分别经 _merge_*_data 合并），
  不属于普通白名单键，故不并入白名单元组。

护栏语义（新增键漏登记立即红）：
- 默认值键 - 特例键 ⊆ 真实白名单（默认值加键而白名单漏登记 → 失败）；
- 真实白名单 ⊆ 默认值键（白名单出现孤儿键 → 失败）；
- 两集合与显式快照一致（现状文档化，改键必须同步改快照）。
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from pet import config as config_mod
from pet.config import Config

# reload() 白名单键集合现状快照（与 pet/config.py reload() 的
# "for key in (...)" 元组一致；任何增删必须同步更新本快照）。
RELOAD_WHITELIST_SNAPSHOT = frozenset(
    {
        "agent_cost_enabled",
        "allow_cross_screen",
        "anim_menu_stay_open",
        "animation_gap_seconds",
        "auto_hide_fullscreen",
        "autostart_wanted",
        "balance_refresh_minutes",
        "balance_tier_color_enabled",
        "balance_tier_label_idle",
        "balance_tier_label_peak",
        "balance_tier_labels_mode",
        "character",
        "character_aliases",
        "chat_always_on_top",
        "chat_background",
        "chat_background_fill",
        "chat_background_opacity",
        "chat_bg_crops",
        "chat_follow_pet",
        "chat_ui_style",
        "click_show_balance",
        "click_sound_enabled",
        "click_sound_pack",
        "click_sound_volume",
        "context_menu_appearance",
        "context_menu_layout",
        "cursor_hidden_passthrough",
        "dialogue_last_scope",
        "dialogue_mode",
        "dialogue_phrases",
        "dynamic_island",
        "edge_probe_enabled",
        "experimental_shared_decode",
        "facing",
        "ffmpeg_recycle_minutes",
        "first_frame_cache_max_mb",
        "focus_mode",
        # 全局快捷键（进程级；空串 = 不绑）
        "hotkey_open_chat",
        "hotkey_look_screen",
        "hotkey_screen_capture",
        "harness_autostart",
        "harness_launch_target",
        "island_metrics",
        "lock_position",
        "media_prewarm",
        "modern_chat_background",
        "modern_chat_background_fill",
        "modern_chat_background_opacity",
        "modern_chat_card_opacity",
        "mouse_through",
        "network_info_menu_enabled",
        "no_move",
        "on_top",
        "pet_opacity",
        "playback_speed",
        "pnpm_bin",
        "predict_prewarm_lead_ms",
        "quick_launch_apps",
        "quiet_also_on_fullscreen",
        "quiet_minutes_default",
        "bubble_text_scale",
        "rx",
        "ry",
        "scale",
        "screen_name",
        "self_talk_bubble_style",
        "self_talk_duration_seconds",
        "self_talk_enabled",
        "self_talk_image_chance",
        "self_talk_image_dir",
        "self_talk_image_scale",
        "self_talk_max_interval",
        "self_talk_min_interval",
        "self_talk_texts",
        "settings_process_isolation",
        "shift_drag",
        "spawn_inherit_dynamic_island",
        "spawn_inherit_size",
        "spawn_scale",
        "system_notifications_enabled",
        "todo_reminder_enabled",
        "todo_reminder_lead_minutes",
        "user_customized",
    }
)

# 默认值 dict 里不走普通白名单、由 reload() 专门路径处理的键（现状文档化）。
SPECIAL_CASED_KEYS = frozenset({"version", "proactive_screen", "agent_link", "chat"})

# 默认值 dict 键集合现状快照 = 白名单 ∪ 特例键。
# 2026-09-22 加入自言自语配图概率（self_talk_image_chance）。
# 2026-10-07 深夜批次再加：网络信息菜单 1（network_info_menu_enabled）、
# 免打扰 2（quiet_minutes_default/quiet_also_on_fullscreen）、动画菜单 1
# （anim_menu_stay_open）。
# 后实测（2026-10-07 夜间整合后复测）：白名单字面量 139 + 特例 5 = 144。
# 2026-10-07 P1 Slice C 加灵动岛指标 1（island_metrics，列表序=优先级），白名单 140。
DEFAULTS_SNAPSHOT = RELOAD_WHITELIST_SNAPSHOT | SPECIAL_CASED_KEYS


def _actual_reload_whitelist() -> frozenset:
    """测试探针：从 config.py 源码提取 reload() 白名单元组的真实键集合。

    白名单是 reload() 方法内的字面量，运行期无法经实例访问，故用
    inspect.getsource + 正则提取。格式变更导致提取失败时以明确信息
    失败（提示同步更新本探针），而不是静默放行。
    """
    reload_src = inspect.getsource(config_mod.Config.reload)
    m = re.search(r"for key in \((.*?)\):\n", reload_src, re.S)
    assert m, "从 reload() 源码找不到白名单元组，请检查 config.py 的白名单格式"
    return frozenset(re.findall(r'"([a-zA-Z0-9_]+)"', m.group(1)))


def _actual_defaults_keys(tmp_path) -> frozenset:
    """运行期默认值键集合：无配置文件时 Config.data 即默认值 dict 的键。"""
    cfg = Config(base=tmp_path)
    return frozenset(cfg.data)


def test_defaults_snapshot_matches_current(tmp_path):
    """默认值 dict 键集合 == 显式快照（现状文档化；新增键不改快照立即红）。"""
    assert _actual_defaults_keys(tmp_path) == DEFAULTS_SNAPSHOT


def test_reload_whitelist_snapshot_matches_current():
    """reload 白名单真实字面量 == 显式快照（现状文档化）。"""
    assert _actual_reload_whitelist() == RELOAD_WHITELIST_SNAPSHOT


def test_every_defaults_key_is_whitelisted_or_special_cased(tmp_path):
    """核心护栏：默认值 dict 新增键必须登记白名单（或列入特例集），否则立即红。"""
    defaults = _actual_defaults_keys(tmp_path)
    whitelist = _actual_reload_whitelist()
    assert defaults - SPECIAL_CASED_KEYS <= whitelist


def test_whitelist_has_no_orphan_keys(tmp_path):
    """白名单键都必须存在于默认值 dict（无孤儿白名单键）。"""
    defaults = _actual_defaults_keys(tmp_path)
    assert _actual_reload_whitelist() <= defaults


def test_special_cased_keys_are_the_only_difference(tmp_path):
    """默认值与白名单的差集恰好是文档化的特例键（特例集不得悄悄扩大/缩小）。"""
    defaults = _actual_defaults_keys(tmp_path)
    whitelist = _actual_reload_whitelist()
    assert defaults - whitelist == SPECIAL_CASED_KEYS
    assert whitelist - defaults == frozenset()


# ---------------------------------------------------------------- 脏值归一化
# 消费统计开关此前只在默认值 dict 与 reload 白名单里登记，没进
# _normalize_pet_settings：字符串布尔被 bool() 误开（bool('false') is True）。
# 下面固定这条修复。

def _dirty_cost_config(tmp_path):
    """把配置键写成脏值落盘，再走真实加载路径（reload + _normalize_pet_settings）。"""
    cfg_dir = tmp_path / config_mod.APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 4,
                "agent_cost_enabled": "yes",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return Config(base=tmp_path)


def test_dirty_cost_key_is_normalized(tmp_path):
    """脏 config.json 加载后：布尔判真。"""
    cfg = _dirty_cost_config(tmp_path)

    assert cfg.data["agent_cost_enabled"] is True


def test_set_normalizes_cost_key(tmp_path):
    """set() 的归一化名单同样要覆盖该键（设置页写回的值不得绕过钳制）。"""
    cfg = Config(base=tmp_path)

    cfg.set("agent_cost_enabled", "yes")
    assert cfg.data["agent_cost_enabled"] is True


# ------------------------------------------------- 动画菜单连播（#221）
def _anim_menu_config(tmp_path, raw) -> Config:
    """把 ``anim_menu_stay_open`` 写成脏值落盘，再走真实加载路径。"""
    cfg_dir = tmp_path / config_mod.APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, "anim_menu_stay_open": raw}, ensure_ascii=False),
        encoding="utf-8",
    )
    return Config(base=tmp_path)


def test_anim_menu_stay_open_defaults_to_closing_after_action(tmp_path):
    """默认 False = 点一个动作就收起菜单（#221 的产品决策）。

    该键是**菜单行为类**偏好：不进设置页（菜单行为类偏好，不进设置页），用户手改
    config.json 才切到连播。
    """
    assert Config(base=tmp_path).data["anim_menu_stay_open"] is False


def test_set_normalizes_network_keys(tmp_path):
    """set() 路径同样归一（设置页写回的值不得绕过布尔归一）。"""
    cfg = Config(base=tmp_path)
    cfg.set("network_info_menu_enabled", "off")
    assert cfg.data["network_info_menu_enabled"] is False


def test_network_info_menu_key_survives_reload_round_trip(tmp_path):
    """落盘 → 重启加载：网络信息菜单键是普通白名单键，不得被默认值冲掉。"""
    cfg = Config(base=tmp_path)
    cfg.set("network_info_menu_enabled", False)
    assert cfg.save() is True
    restored = Config(base=tmp_path)
    assert restored.data["network_info_menu_enabled"] is False


# ------------------------------------------------- 自启目标（harness_launch_target）
def _launch_target_config(tmp_path, raw: str) -> Config:
    """把 ``harness_launch_target`` 写成指定原始值落盘，再走真实加载路径。"""
    cfg_dir = tmp_path / config_mod.APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 4, "harness_launch_target": raw}, ensure_ascii=False),
        encoding="utf-8",
    )
    return Config(base=tmp_path)


def test_harness_launch_target_accepts_service_and_falls_back_to_auto(tmp_path):
    """归一化认 ``service``（新增的自启目标），非法值仍回落 ``auto``。

    语义收紧（2026-10）：auto 不再解析成 desktop，而是只拉起 dsh 服务；设置页
    新增「仅 dsh 服务」项后，该值必须能落盘、重载后不被归一化抹掉。
    """
    assert _launch_target_config(tmp_path / "svc", "service").get("harness_launch_target") == "service"
    assert _launch_target_config(tmp_path / "auto", "auto").get("harness_launch_target") == "auto"
    for i, bad in enumerate(("desktop-gui", "SERVICE2", "", "0")):
        cfg = _launch_target_config(tmp_path / f"bad{i}", bad)
        assert cfg.get("harness_launch_target") == "auto", f"非法值 {bad!r} 必须回退 auto"


def test_set_harness_launch_target_keeps_service(tmp_path):
    """set() 路径同样不吞 service（设置页保存走 set → save）。"""
    cfg = Config(base=tmp_path)
    cfg.set("harness_launch_target", "service")
    assert cfg.data["harness_launch_target"] == "service"


def test_dirty_cost_config_does_not_break_settings_page(tmp_path):
    """设置页（settings_pet_controls）面对脏配置必须能构造出来。"""
    from PySide6.QtWidgets import QApplication

    from pet.modern_settings_dialog import ModernSettingsDialog

    QApplication.instance() or QApplication([])
    cfg = _dirty_cost_config(tmp_path)

    dialog = ModernSettingsDialog(cfg, include_ai=False)

    assert dialog.agent_cost_check.isChecked() is True


# ---------------------------------------------------------------- 交付前审查 P1-3 / P2-a / P2-b


def _write_config(tmp_path, payload: dict) -> None:
    cfg_dir = tmp_path / config_mod.APP_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_huge_integer_literal_falls_back_to_default(tmp_path):
    """超长整数字面量（json 产出 Python int）不得让 Config() 抛 OverflowError。

    回归：``_float_or_default`` 只捕 TypeError/ValueError，``float(10**400)``
    抛 OverflowError → Config.__init__ 失败 → pet/app.py 的 Config() 不在 try
    里 → 启动直接崩（无窗口）。
    """
    huge = int("9" * 400)
    _write_config(
        tmp_path,
        {
            "version": 4,
            "click_sound_volume": huge,
        },
    )
    cfg = Config(base=tmp_path)

    assert cfg.data["click_sound_volume"] == 0.70


def test_set_with_huge_integer_does_not_raise(tmp_path):
    """set() 路径同样不能因 OverflowError 抛（设置页写回同一助手）。"""
    cfg = Config(base=tmp_path)
    cfg.set("click_sound_volume", int("9" * 400))
    assert cfg.data["click_sound_volume"] == 0.70


# ------------------------------------------- 退役键的静默迁移（2026-10-08）
def test_retired_menu_template_key_is_discarded_silently(tmp_path):
    """旧版菜单退役后，配置里的菜单模板键必须静默丢弃：读入即弃 + 不再写回。

    旧存档（含用户手改的 `"legacy"`）只能表现为"什么都没发生"：不抛异常、
    不回退旧布局、不影响启动；下一次落盘时键从文件里消失。
    """
    cfg = _load_with(tmp_path, context_menu_template="legacy")
    assert "context_menu_template" not in cfg.data
    assert cfg.get("context_menu_template") is None
    assert cfg.get("context_menu_template", "modern") == "modern"


def test_retired_menu_template_key_is_not_written_back(tmp_path):
    """丢弃必须落到盘上：save() 之后 config.json 里不再有这个键。"""
    import json

    cfg = _load_with(tmp_path, context_menu_template="modern")
    assert cfg.save() is True
    payload = json.loads((cfg.dir / "config.json").read_text(encoding="utf-8"))
    assert "context_menu_template" not in payload


def test_retired_menu_template_key_is_dropped_in_slot_config(tmp_path):
    """每个 slot 配置同样丢弃（子肥鱼各有自己那份 config-slot-N.json）。"""
    import json

    slot_dir = tmp_path / "slot"
    (slot_dir / config_mod.APP_DIR_NAME).mkdir(parents=True, exist_ok=True)
    _write_config(slot_dir, {"version": 4, "context_menu_template": "legacy"})
    slot_path = slot_dir / config_mod.APP_DIR_NAME / "config.json"
    slot_path.rename(slot_path.with_name("config-slot-3.json"))
    cfg = Config(base=slot_dir, instance_id="slot-3")
    assert "context_menu_template" not in cfg.data
    assert cfg.get("context_menu_template") is None


# ------------------------------------------------- 脏值家族：合法 JSON 不得阻断启动
#
# 全产品审查 C3（2026-10-08）：三族脏值都能让 ``Config()`` 构造直接抛异常，
# 而启动路径（``pet/app.py`` 的 Config()）与自救入口（``pet/__main__.py`` 的
# 独立设置页同样先构造 Config()）都没有 try —— 一个手改出来的 config.json
# 就能让程序连设置恢复都进不去：
#
# - list / dict 撞 ``x not in {"..."}`` 成员判断 → TypeError: unhashable；
# - ``10**400``（json 合法数字字面量 → Python 大整数）撞 ``float()`` /
#   ``math.isfinite()`` → OverflowError；
# - ``Infinity`` / ``NaN``（Python json.loads 默认接受）撞 ``int()`` → OverflowError。
#
# 下面把这一族**逐键**钉住：构造成功 + 回默认值。探针口径见本文件末尾的
# ``test_dirty_value_scan_covers_every_config_key``（穷举全键 × 全脏值）。

_HUGE = int("9" * 400)


def _load_with(tmp_path, **payload):
    """按真实加载路径读一份脏配置（reload + _normalize_pet_settings）。"""
    payload.setdefault("version", 4)
    _write_config(tmp_path, payload)
    return Config(base=tmp_path)


def _island_coordinate_config(tmp_path, axis: str, value):
    return _load_with(tmp_path, dynamic_island={"enabled": True, axis: value})


def test_unhashable_enum_keys_fall_back_to_default(tmp_path):
    """枚举键撞 list/dict：成员判断不得抛 TypeError: unhashable type。"""
    for i, (key, expected) in enumerate((("chat_ui_style", "modern"),)):
        for j, dirty in enumerate(([1, 2], {"a": 1})):
            cfg = _load_with(tmp_path / f"{i}-{j}", **{key: dirty})
            assert cfg.data[key] == expected, f"{key}={dirty!r} 必须回落 {expected}"


def test_unhashable_enum_keys_keep_legal_values(tmp_path):
    """非回归：合法枚举值原样保留（保护不能顺手吃掉合法值）。"""
    assert _load_with(
        tmp_path / "classic", chat_ui_style="classic").get("chat_ui_style") == "classic"


def test_huge_island_coordinates_fall_back_to_auto_position(tmp_path):
    """灵动岛坐标超大整数：回 None（自动定位），不得 OverflowError。"""
    for axis in ("x", "y"):
        for i, dirty in enumerate((_HUGE, -_HUGE)):
            cfg = _island_coordinate_config(tmp_path / f"{axis}{i}", axis, dirty)
            assert cfg.data["dynamic_island"][axis] is None


def test_nonfinite_and_huge_island_opacity_fall_back(tmp_path):
    """灵动岛不透明度：超大整数/NaN/Infinity 落在 [0.4, 1.0]，不得抛异常。

    超范围数值按区间夹取（与全文件数值键同规），非数值/溢出/NaN 回默认 1.0。
    """
    cases = (
        (_HUGE, 1.0),            # float() 溢出 → 默认
        (float("nan"), 1.0),     # 不可比较 → 默认
        (float("inf"), 1.0),     # 超上限 → 夹到 1.0
        (float("-inf"), 0.4),    # 超下限 → 夹到 0.4
    )
    for i, (dirty, expected) in enumerate(cases):
        cfg = _load_with(
            tmp_path / f"opacity{i}", dynamic_island={"enabled": True, "opacity": dirty}
        )
        assert cfg.data["dynamic_island"]["opacity"] == expected, f"opacity={dirty!r}"


def test_huge_quiet_minutes_falls_back_to_default(tmp_path):
    """免打扰默认时长：超大整数回默认档（float() 溢出不得冒泡）。"""
    cfg = _load_with(tmp_path, quiet_minutes_default=_HUGE)
    assert cfg.data["quiet_minutes_default"] == config_mod.DEFAULT_QUIET_MINUTES


def test_nonfinite_int_keys_fall_back_to_default(tmp_path):
    """int() 型数值键遇 Infinity/NaN：不得 OverflowError，落在可用区间内。"""
    cases = ((float("inf"), 100, 100), (float("-inf"), 10, 10), (float("nan"), 100, 84))
    for i, (dirty, background, card) in enumerate(cases):
        cfg = _load_with(
            tmp_path / f"opacity{i}",
            chat_background_opacity=dirty,
            modern_chat_background_opacity=dirty,
            modern_chat_card_opacity=dirty,
        )
        assert cfg.data["chat_background_opacity"] == background, f"{dirty!r}"
        assert cfg.data["modern_chat_background_opacity"] == background, f"{dirty!r}"
        assert cfg.data["modern_chat_card_opacity"] == card, f"{dirty!r}"


def test_nonfinite_menu_appearance_int_keys_fall_back(tmp_path):
    """菜单外观的圆角/字号：Infinity/NaN 回可用值（不抛），合法值照常夹取。"""
    cases = (
        (float("inf"), 18, 18),
        (float("-inf"), 6, 10),
        (float("nan"), 12, 13),      # NaN → 默认
        (999, 18, 18),               # 越界数值 → 夹取
    )
    for i, (dirty, radius, font_size) in enumerate(cases):
        cfg = _load_with(
            tmp_path / f"appearance{i}",
            context_menu_appearance={"corner_radius": dirty, "ui_font_size": dirty},
        )
        assert cfg.data["context_menu_appearance"]["corner_radius"] == radius, f"{dirty!r}"
        assert cfg.data["context_menu_appearance"]["ui_font_size"] == font_size, f"{dirty!r}"


def test_nonfinite_version_does_not_break_reload(tmp_path):
    """顶层 version 非有限：reload 的迁移判定不得抛（回 1 = 老配置路径）。"""
    for i, dirty in enumerate((float("inf"), float("-inf"), float("nan"))):
        cfg = _load_with(tmp_path / f"version{i}", version=dirty)
        assert cfg.data["version"] == 4, "归一化后 version 仍必须回写当前版本"


def test_dirty_value_scan_covers_every_config_key(tmp_path):
    """穷举探针：每个配置键 × 每种脏值都必须能构造出 Config（家族护栏）。

    这是"同族残留"的机器判据——新增键只要又走裸 ``x in {...}`` / ``int()`` /
    ``float()`` / ``math.isfinite()``，这里立刻红，并指出是哪个键哪种脏值。
    """
    dirty_values = {
        "list": [1, 2],
        "dict": {"a": 1},
        "huge": _HUGE,
        "nan": float("nan"),
        "inf": float("inf"),
        "neginf": float("-inf"),
        "str": "abc",
        "none": None,
    }
    keys = sorted(Config(base=tmp_path / "seed").data)
    failures: list[str] = []
    for key in keys:
        for label, dirty in dirty_values.items():
            case = tmp_path / f"{key[:40]}-{label}"
            try:
                _load_with(case, **{key: dirty})
            except Exception as exc:  # noqa: BLE001 - 探针要把任何异常都记下来
                failures.append(f"{key}={label}: {type(exc).__name__}: {exc}")
    assert failures == [], "脏值不得阻断 Config() 构造：\n" + "\n".join(failures)
