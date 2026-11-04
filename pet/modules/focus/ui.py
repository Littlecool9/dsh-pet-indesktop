# -*- coding: utf-8 -*-
"""Pomodoro commands shared by the island card and recovery context menu."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .session import PHASE_NAMES


def toggle_focus(config, service):
    service.toggle(config)


def command_label(service):
    if service.status == "running":
        return "暂停"
    if service.status == "paused":
        return "继续"
    return "开始专注"


class FocusControls(QWidget):
    def __init__(self, service, config, parent=None):
        super().__init__(parent)
        self.service = service
        self.config = config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)
        self.status = QLabel(self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)
        self.detail = QLabel(self)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail)
        buttons = QHBoxLayout()
        self.toggle = QPushButton(self)
        self.toggle.setObjectName("focusStartPause")
        self.toggle.clicked.connect(lambda: toggle_focus(config, service))
        self.end = QPushButton("结束", self)
        self.end.setObjectName("focusEnd")
        self.end.clicked.connect(service.stop)
        buttons.addWidget(self.toggle)
        buttons.addWidget(self.end)
        layout.addLayout(buttons)
        self.refresh()

    def content_height(self, width):
        return max(self.minimumSizeHint().height(), self.layout().totalHeightForWidth(width))

    def refresh(self):
        state = self.service
        text = "专注模式" if not state.engaged else PHASE_NAMES[state.phase]
        if state.engaged:
            if state.status == "paused":
                text += "（已暂停）"
            text += f" · 已完成 {state.completed} 轮"
        self.status.setText(text)
        self.detail.setText(state.observation or "工作背景与时长在设置中修改。")
        self.status.setToolTip(state.observation or "工作背景与时长在设置 → 自动化与联动 → 专注模式中修改。")
        self.toggle.setText(command_label(state))
        self.toggle.setAccessibleName(f"专注模式：{command_label(state)}")
        self.end.setAccessibleName("结束专注模式")
        self.end.setEnabled(state.engaged)


def build_focus_menu(menu, pet, service):
    sub = menu.addMenu("专注模式")
    label = sub.addAction(service.label())
    label.setEnabled(False)
    sub.addAction(command_label(service), lambda: toggle_focus(getattr(pet, "cfg", None), service))
    end = sub.addAction("结束专注", service.stop)
    end.setEnabled(service.engaged)
    return sub
