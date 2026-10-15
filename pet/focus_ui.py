"""Pomodoro commands shared by the island card and recovery context menu."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .focus_mode import PHASE_NAMES, shared_focus_session


def toggle_focus(config):
    state = shared_focus_session()
    if state.status == "running":
        state.pause()
    else:
        state.start(config.get("focus_mode"))


def command_label():
    state = shared_focus_session()
    if state.status == "running":
        return "暂停"
    if state.status == "paused":
        return "继续"
    return "开始专注"


class FocusControls(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
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
        self.toggle.clicked.connect(lambda: toggle_focus(config))
        self.end = QPushButton("结束", self)
        self.end.setObjectName("focusEnd")
        self.end.clicked.connect(shared_focus_session().stop)
        buttons.addWidget(self.toggle)
        buttons.addWidget(self.end)
        layout.addLayout(buttons)
        self.refresh()

    def content_height(self, width):
        return max(self.minimumSizeHint().height(), self.layout().totalHeightForWidth(width))

    def refresh(self):
        state = shared_focus_session()
        text = "专注模式" if not state.engaged else PHASE_NAMES[state.phase]
        if state.engaged:
            if state.status == "paused":
                text += "（已暂停）"
            text += f" · 已完成 {state.completed} 轮"
        self.status.setText(text)
        self.detail.setText(state.observation or "工作背景与时长在设置中修改。")
        self.status.setToolTip(state.observation or "工作背景与时长在设置 → 自动化与联动 → 专注模式中修改。")
        self.toggle.setText(command_label())
        self.toggle.setAccessibleName(f"专注模式：{command_label()}")
        self.end.setAccessibleName("结束专注模式")
        self.end.setEnabled(state.engaged)


def build_focus_menu(menu, pet):
    sub = menu.addMenu("专注模式")
    state = shared_focus_session()
    label = sub.addAction(state.label())
    label.setEnabled(False)
    sub.addAction(command_label(), lambda: toggle_focus(pet.cfg))
    end = sub.addAction("结束专注", state.stop)
    end.setEnabled(state.engaged)
    return sub
