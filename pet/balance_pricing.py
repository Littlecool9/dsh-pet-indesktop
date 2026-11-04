# -*- coding: utf-8 -*-
"""DeepSeek 余额折算与峰谷计价的纯函数（Qt-free）。

余额数据的网络查询和界面落在 ``pet.modules.balance`` 模块里；这里的函数只做
纯计算，核心的灵动岛（``pet/dynamic_island.py``）在绘制余额/峰谷信息时需要它们。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

# DeepSeek 满额基准（¥）：余额 ≥ 该值视为 100%（未消耗），余额按比例折算为已用百分比
DEEPSEEK_FULL_BALANCE_CNY = 20.0

# 余额事件动画档位顺序（与上游 assets/config.jsonc 一致）：
# index = p === 100 ? 5 : Math.floor(p / 20)
BALANCE_EVENT_NAMES = (
    '余额-钱袋满溢',  # 0 ≤ p < 20（几乎未消耗）
    '余额-金袋叮当',  # 20 ≤ p < 40
    '余额-钱袋如常',  # 40 ≤ p < 60
    '余额-数金皱眉',  # 60 ≤ p < 80
    '余额-袋空如洗',  # 80 ≤ p < 100（告急）
    '余额-分文不剩',  # p === 100（全部用完，格外档）
)

_BEIJING_TZ = ZoneInfo('Asia/Shanghai')


def balance_percent(total: str | float | None) -> float | None:
    """把 DeepSeek 余额折算为“已用百分比”（0 = 未消耗，100 = 耗尽）。

    余额 20 元 → 0%，10 元 → 50%，0 元 → 100%；负数按 0 处理（透支视为已用完）。
    金额非法返回 None，上层不应触发档位动画。
    """
    raw = str(total or '').strip()
    if raw == '':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    remaining = max(0.0, value) / DEEPSEEK_FULL_BALANCE_CNY * 100.0
    return max(0.0, min(100.0, 100.0 - remaining))


def balance_event_index(p: float) -> int:
    """余额事件档位索引：p === 100 → 5，否则 Math.floor(p / 20) 夹到 0..4。"""
    if p >= 100.0:
        return 5
    idx = int(p // 20)
    return idx if idx < 5 else 4


def _beijing_now(now: datetime | None = None) -> datetime:
    """把入参统一转到北京时间；None 取当前北京时间。"""
    if now is None:
        return datetime.now(_BEIJING_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=_BEIJING_TZ)
    return now.astimezone(_BEIJING_TZ)


def deepseek_pricing_tier(now: datetime | None = None) -> str:
    """DeepSeek 峰谷计价档位（北京时间）。

    高峰：周一至周五 9:00–12:00、14:00–18:00；其余为空闲（低谷）。
    周六/周日全天空闲；调休补班的周六/周日按官方口径仍是空闲，不是工作日高峰。
    """
    bj = _beijing_now(now)
    if bj.weekday() >= 5:
        return 'idle'
    hour = bj.hour
    return 'peak' if (9 <= hour < 12) or (14 <= hour < 18) else 'idle'


# 一天内的计价切换时刻：09:00 / 14:00 进入高峰，12:00 / 18:00 离开高峰。
_PRICING_BOUNDARIES = (time(9, 0), time(12, 0), time(14, 0), time(18, 0))

# 切换扫描窗口（天）：跨过整段周末也不过两三天，40 天留足余量。
_PRICING_SCAN_DAYS = 40


def _next_pricing_switch(now: datetime | None = None) -> tuple[str, datetime]:
    """返回 (下一档位, 下一档位开始时间)，按北京时间计算。

    逐个扫描未来 09:00/12:00/14:00/18:00 边界，取**最早**一个档位与当前不同的
    时刻，跨越周末无需为每种日历情形单独写分支。
    """
    bj = _beijing_now(now)
    tz = bj.tzinfo or _BEIJING_TZ
    current = deepseek_pricing_tier(bj)
    day = bj.date()
    for offset in range(_PRICING_SCAN_DAYS + 1):
        candidate_day = day + timedelta(days=offset)
        for boundary in _PRICING_BOUNDARIES:
            candidate = datetime.combine(candidate_day, boundary, tzinfo=tz)
            if candidate <= bj:
                continue
            tier = deepseek_pricing_tier(candidate)
            if tier != current:
                return tier, candidate
    # 扫描窗口内没有翻转（理论上不会发生）：退回次日 09:00。
    fallback = datetime.combine(day + timedelta(days=1), time(9, 0), tzinfo=tz)
    return deepseek_pricing_tier(fallback), fallback


def next_pricing_switch(now: datetime | None = None) -> tuple[str, datetime]:
    """公开入口：返回 (下一档位, 下一档位开始时间)，按北京时间计算。"""
    return _next_pricing_switch(now)


def beijing_now(now: datetime | None = None) -> datetime:
    """公开入口：返回当前/入参的北京时间（供 UI 层自行定时刷新）。"""
    return _beijing_now(now)


_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _format_switch_time(now: datetime, next_time: datetime) -> str:
    """把下一档位切换时间格式化为易读文案。

    当天切换只显示 HH:MM；跨天切换显示“明天 HH:MM”，更远的日期按 **ISO 周**
    决定措辞：同一周内用“周四 HH:MM”，跨周才用“下周四 HH:MM”。避免把周五晚上
    的“09:00”误解为次日早晨，也避免把同一周的周四说成“下周四”。
    """
    if next_time.date() == now.date():
        return f"{next_time:%H:%M}"
    days = (next_time.date() - now.date()).days
    if days == 1:
        return f"明天 {next_time:%H:%M}"
    same_week = next_time.date().isocalendar()[:2] == now.date().isocalendar()[:2]
    prefix = "" if same_week else "下"
    return f"{prefix}{_WEEKDAY_CN[next_time.weekday()]} {next_time:%H:%M}"


def format_switch_time(now: datetime, next_time: datetime) -> str:
    """公开入口：把下一档位切换时间格式化为易读文案。"""
    return _format_switch_time(now, next_time)


def resolve_tier_labels(
    mode: str = "default",
    custom_peak: str = "",
    custom_idle: str = "",
) -> tuple[str, str]:
    """根据设置返回 (高峰文本, 空闲文本)。

    - default：高峰 / 空闲
    - liangwen：梁文峰 / 梁文谷
    - custom：使用用户自定义文本，留空回退默认
    """
    mode = str(mode or "default").strip().lower()
    if mode == "liangwen":
        return "梁文峰", "梁文谷"
    if mode == "custom":
        peak = str(custom_peak or "").strip() or "高峰"
        idle = str(custom_idle or "").strip() or "空闲"
        return peak, idle
    return "高峰", "空闲"


def deepseek_pricing_hint(
    now: datetime | None = None,
    peak_label: str | None = None,
    idle_label: str | None = None,
) -> str:
    """生成余额气泡下方的 DeepSeek 峰谷提示文案。

    如「DeepSeek 当前高峰 · 下一空闲 12:00」「DeepSeek 当前空闲 · 下一高峰 09:00」。
    peak_label/idle_label 可由设置项自定义（如梁文峰/梁文谷）。
    """
    bj = _beijing_now(now)
    tier = deepseek_pricing_tier(bj)
    next_tier, next_time = _next_pricing_switch(bj)
    peak_text = str(peak_label or "高峰")
    idle_text = str(idle_label or "空闲")
    label = peak_text if tier == 'peak' else idle_text
    next_label = idle_text if next_tier == 'idle' else peak_text
    time_text = _format_switch_time(bj, next_time)
    return f'DeepSeek 当前{label} · 下一{next_label} {time_text}'


def deepseek_pricing_hint_html(
    now: datetime | None = None,
    peak_label: str | None = None,
    idle_label: str | None = None,
    peak_color: str = "#e5484d",
    idle_color: str = "#30a46c",
) -> str:
    """生成带颜色的 DeepSeek 峰谷提示 HTML（QLabel 可直接渲染）。

    默认高峰红、低谷绿；用户自定义文案会做 HTML 转义，防止破坏富文本。
    """
    bj = _beijing_now(now)
    tier = deepseek_pricing_tier(bj)
    next_tier, next_time = _next_pricing_switch(bj)
    peak_text = escape(str(peak_label or "高峰"))
    idle_text = escape(str(idle_label or "空闲"))

    def span(text: str, color: str) -> str:
        return f'<span style="color:{color}">{text}</span>'

    label = span(peak_text, peak_color) if tier == 'peak' else span(idle_text, idle_color)
    next_label = span(idle_text, idle_color) if next_tier == 'idle' else span(peak_text, peak_color)
    time_text = _format_switch_time(bj, next_time)
    return f'DeepSeek 当前{label} · 下一{next_label} {time_text}'


__all__ = [
    "BALANCE_EVENT_NAMES",
    "DEEPSEEK_FULL_BALANCE_CNY",
    "balance_event_index",
    "balance_percent",
    "beijing_now",
    "deepseek_pricing_hint",
    "deepseek_pricing_hint_html",
    "deepseek_pricing_tier",
    "format_switch_time",
    "next_pricing_switch",
    "resolve_tier_labels",
]
