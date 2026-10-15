"""Global focus preferences, owned by the automation settings domain."""
import sys

from PySide6.QtWidgets import QPlainTextEdit

from .focus_mode import normalize_focus_config
from .settings_widgets import BrowserSpinBox, SettingRow, ToggleSwitch


def build_focus_rows(dialog):
    cfg = normalize_focus_config(dialog.config.get("focus_mode"))
    editor = QPlainTextEdit(dialog)
    editor.setObjectName("focusWorkContext")
    editor.setPlainText(cfg["work_context"])
    editor.setPlaceholderText("例如：开发 Python 桌面应用，阅读文档、查资料和观看相关教程都属于工作。")
    editor.setMinimumHeight(editor.fontMetrics().lineSpacing() * 5)
    editor.setAccessibleName("工作背景与专注目标")
    editor.setTabChangesFocus(True)
    dialog.focus_work_context = editor
    rows = [SettingRow("focus_work_context", "工作背景与专注目标", "填写一次、长期保存（最多 4000 字符），专注时自动提供给模型；不覆盖角色人设。影响所有桌宠。", editor, parent=dialog, stacked=True)]
    dialog.focus_controls = {}
    for key, label, upper in (
        ("work_minutes", "专注时长（分钟）", 180),
        ("short_break_minutes", "短休息时长（分钟）", 60),
        ("long_break_minutes", "长休息时长（分钟）", 120),
        ("long_break_every", "每几轮长休息一次", 12),
        ("check_minutes", "专注陪伴间隔（分钟）", 30),
        ("daily_cap", "每日模型请求上限", 9999),
    ):
        spin = BrowserSpinBox(dialog)
        spin.setRange(1, upper)
        spin.setValue(cfg[key])
        dialog.focus_controls[key] = spin
        hint = ("仅专注期间观察或鼓励；偏离提醒至少间隔 5 分钟。影响所有桌宠。" if key == "check_minutes"
                else "包括重试的实际请求次数；耗尽后计时照常，次日恢复。影响所有桌宠。" if key == "daily_cap"
                else "下一个阶段开始时生效；专注与休息到点后自动切换。影响所有桌宠。")
        rows.append(SettingRow(f"focus_{key}", label, hint, spin, parent=dialog))
    toggle = ToggleSwitch(dialog)
    toggle.setChecked(cfg["screen_enabled"])
    toggle.setEnabled(sys.platform == "win32")
    dialog.focus_screen_enabled = toggle
    rows.append(SettingRow("focus_screen_enabled", "专注时观察前台窗口", "仅专注期间生效。工作背景与前台窗口截图会发送至你配置的看图模型服务，产生模型费用；截图不保存。需要支持图片输入的模型；关闭后仅生成专注鼓励。当前自动观察支持 Windows。影响所有桌宠。", toggle, parent=dialog))
    return rows


def save_focus_settings(dialog):
    if not hasattr(dialog, "focus_controls"):
        return
    values = {key: spin.value() for key, spin in dialog.focus_controls.items()}
    values.update(work_context=dialog.focus_work_context.toPlainText(),
                  screen_enabled=dialog.focus_screen_enabled.isChecked())
    dialog.config.set("focus_mode", normalize_focus_config(values))
