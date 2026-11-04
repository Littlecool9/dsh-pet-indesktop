# -*- coding: utf-8 -*-
"""快速对话气泡（Quick Chat）——陪伴线。

点击桌宠弹出的头顶小气泡输入框；回车发送，回复在气泡内显示。发送与回复
都走 SurfCore（``/chat``），与 SurfCore 的 QQ / 记忆 / 人设共用同一份对话。
气泡自己不持有会话、不直连模型 API：它只调用宿主服务里的陪伴线桥
（``pet.module_host.module_service(shell, "surfcore").companion``），由模块把
HTTP 放到后台线程，回复经宿主事件总线回到 GUI 线程。

离线（服务缺失或未连上）时发送按钮禁用并在气泡内写明原因，绝不回退直连 API。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .chat.markdown_view import markdown_to_html
from .speech_bubble import BUBBLE_STYLE_PRESETS
from .speech_bubble_text import truncate_bubble_text

_PAGE_SIZE = 500

# 气泡内回复的展示上限：超长回答不进气泡（头顶气泡只有几百像素），
# 截断到 _REPLY_PREVIEW_LIMIT 字并提示看完整回复。
_REPLY_PREVIEW_LIMIT = 150
_REPLY_PREVIEW_SUFFIX = "…"

#: 与 SurfCore 模块的 ``OFFLINE_HINT`` 同一句（核心不得 import 模块，故此处留字面量）。
SURFCORE_OFFLINE_REASON = "SurfCore 未连接：启动 DSH 后会自动连上"


def _surface_radius(preset: dict) -> float:
    """气泡主体圆角。

    breath_bubble 是有机水滴形（speech_bubble 专属几何，preset 里 radius=0）：
    quick_chat 不支持该形状，按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置在桌宠气泡与快速对话两套观感。这里用大圆角
    近似，与 speech_bubble 同设置不破解；普通预设用自己的 radius。
    """
    if preset.get("shape") == "breath_bubble":
        return 22.0
    return float(preset.get("radius", 14))


def _reply_text(result) -> str | None:
    """从 ``/chat`` 响应里取回复正文；形状不对返回 None（不猜内容）。"""
    if not isinstance(result, dict):
        return None
    reply = result.get("reply")
    if isinstance(reply, dict):
        text = reply.get("text")
    elif isinstance(reply, str):
        text = reply
    else:
        text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return None


def _result_message_id(result) -> str:
    if not isinstance(result, dict):
        return ""
    reply = result.get("reply")
    if isinstance(reply, dict):
        return str(reply.get("id") or "")
    return ""


def _result_error_hint(result) -> str:
    if isinstance(result, dict):
        error = result.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
    return "SurfCore 没有返回内容，稍后再试。"


class QuickChatBubble(QFrame):
    def __init__(self, config, pet_window=None, parent=None, companion=None):
        super().__init__(parent)
        self.config = config
        self.pet_window = pet_window
        self.companion = None
        self._online_callback = self._on_companion_online
        self._pending = False
        self._request_pet_window = None
        self.setObjectName("quick-chat-bubble")
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(320)
        self.setMaximumWidth(460)

        style_id = str(config.get("self_talk_bubble_style", "classic_top") or "classic_top")
        self._preset = BUBBLE_STYLE_PRESETS.get(style_id, BUBBLE_STYLE_PRESETS["classic_top"])
        self._tail_up = False

        self._reply_full = ""       # 回复全文（截断前）
        self._reply_text = ""       # 气泡内展示文本（超上限截断）
        self._reply_truncated = False
        self._page = 0
        self._pages: list[str] = []
        self._deactivate_check_pending = False

        self._build()
        self._connect()
        self.set_companion(companion)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("快速对话")
        title.setObjectName("quick-chat-title")
        self.title_label = title  # 子类（灵动岛气泡）改标题用
        header.addWidget(title)
        header.addStretch(1)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("quick-chat-hint")
        header.addWidget(self.hint_label)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("quick-chat-close")
        self.close_btn.setFixedSize(24, 24)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.output = QLabel("")
        self.output.setObjectName("quick-chat-output")
        self.output.setWordWrap(True)
        self.output.setMinimumHeight(60)
        self.output.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.output_scroll = QScrollArea()
        self.output_scroll.setObjectName("quick-chat-output-scroll")
        self.output_scroll.setWidgetResizable(True)
        self.output_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.output_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output_scroll.setMinimumHeight(60)
        self.output_scroll.setMaximumHeight(220)
        self.output_scroll.setWidget(self.output)
        layout.addWidget(self.output_scroll)

        self.page_widget = QWidget()
        self.page_row = QHBoxLayout(self.page_widget)
        self.page_row.setContentsMargins(0, 0, 0, 0)
        self.prev_btn = QPushButton("←")
        self.page_label = QLabel("")
        self.next_btn = QPushButton("→")
        for btn in (self.prev_btn, self.next_btn):
            btn.setObjectName("quick-chat-page")
            btn.setFixedSize(28, 24)
        self.open_chat_btn = QPushButton("去聊天窗")
        self.open_chat_btn.setObjectName("quick-chat-open")
        self.page_row.addWidget(self.prev_btn)
        self.page_row.addWidget(self.page_label)
        self.page_row.addWidget(self.next_btn)
        self.page_row.addStretch(1)
        self.page_row.addWidget(self.open_chat_btn)
        layout.addWidget(self.page_widget)
        self.page_widget.setVisible(False)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入消息，回车发送…")
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("quick-chat-send")
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        bg = self._preset["background"]
        fg = self._preset["foreground"]
        border = self._preset["border"]
        self.setStyleSheet(f"""
            QLabel#quick-chat-title, QLabel#quick-chat-hint, QLabel#quick-chat-output,
            QLabel#quick-chat-page {{ background: transparent; color: {fg}; border: none; }}
            QScrollArea#quick-chat-output-scroll {{ background: transparent; border: none; }}
            QPushButton {{
                background: {border}; color: {fg}; border: none; border-radius: 8px;
                padding: 3px 8px;
            }}
            QPushButton:hover {{ background: {fg}; color: {bg}; }}
            QLineEdit {{
                background: {bg}; color: {fg}; border: 1px solid {border};
                border-radius: 8px; padding: 5px 8px;
            }}
        """)

    def _connect(self) -> None:
        self.close_btn.clicked.connect(self.close)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.prev_btn.clicked.connect(lambda: self._show_page(self._page - 1))
        self.next_btn.clicked.connect(lambda: self._show_page(self._page + 1))
        self.open_chat_btn.clicked.connect(self._open_full_chat)

    # ------------------------------------------------------------ 陪伴线服务
    def set_companion(self, companion) -> None:
        """接入（或断开）SurfCore 陪伴线桥；None = 离线。"""
        if companion is self.companion:
            self._sync_availability()
            return
        old = self.companion
        if old is not None:
            remove = getattr(old, "remove_listener", None)
            if callable(remove):
                try:
                    remove(self._online_callback)
                except Exception:
                    pass
        self.companion = companion
        if companion is not None:
            add = getattr(companion, "add_listener", None)
            if callable(add):
                try:
                    add(self._online_callback)
                except Exception:
                    pass
        self._sync_availability()

    def _on_companion_online(self, _online: bool) -> None:
        self._sync_availability()

    def online(self) -> bool:
        return bool(getattr(self.companion, "online", False))

    def _sync_availability(self) -> None:
        online = self.online()
        self.send_btn.setEnabled(online)
        self.input.setEnabled(online)
        if online:
            if self.hint_label.text() == SURFCORE_OFFLINE_REASON:
                self.hint_label.setText("")
            self.hint_label.setToolTip("")
            return
        self.hint_label.setText(SURFCORE_OFFLINE_REASON)
        self.hint_label.setToolTip(SURFCORE_OFFLINE_REASON)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(6, 8, -6, -8)
        radius = _surface_radius(self._preset)
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        tail = QPainterPath()
        tip_x = rect.center().x()
        if self._tail_up:
            tip = QPointF(tip_x, rect.top() - 6)
            tail.moveTo(QPointF(tip_x - 8, rect.top() + 2))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + 8, rect.top() + 2))
        else:
            tip = QPointF(tip_x, rect.bottom() + 6)
            tail.moveTo(QPointF(tip_x - 8, rect.bottom() - 2))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + 8, rect.bottom() - 2))
        tail.closeSubpath()
        surface = body.united(tail).simplified()

        # 柔和阴影
        shadow = QPainterPath(surface)
        shadow.translate(0, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._preset.get("shadow", "#6b542b")))
        painter.drawPath(shadow)

        # 气泡主体
        painter.setBrush(QColor(self._preset["background"]))
        painter.setPen(QPen(QColor(self._preset["border"]), 1))
        painter.drawPath(surface)
        painter.end()

    def position_near_pet(self) -> None:
        pet = self.pet_window
        if pet is None or not hasattr(pet, "visible_content_rect"):
            return
        anchor = pet.visible_content_rect()
        screen = QGuiApplication.screenAt(anchor.center())
        available = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        w = self.width()
        h = self.height()
        x = anchor.center().x() - w // 2
        y = anchor.top() - h - 8
        self._tail_up = False
        if y < available.top():
            y = anchor.bottom() + 8
            self._tail_up = True
        x = max(available.left() + 4, min(x, available.right() - w - 4))
        self.move(x, y)
        self.update()

    def show_for_pet(self, pet_window=None) -> None:
        if pet_window is not None:
            self.pet_window = pet_window
        self.position_near_pet()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    # ------------------------------------------------------------ 发送
    def _send(self) -> None:
        if self._pending:
            return
        if not self.online():
            self._sync_availability()
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.output.setText("")
        self._set_reply_text("")
        self._page = 0
        self._pages = []
        self.page_widget.setVisible(False)
        self.hint_label.setText("思考中…")
        self._pending = True
        self._request_pet_window = self.pet_window
        companion = self.companion
        send = getattr(companion, "send", None)
        accepted = False
        if callable(send):
            try:
                accepted = bool(send(text, self._on_chat_done))
            except Exception:
                accepted = False
        if accepted:
            return
        self._pending = False
        if not self.online():
            self._sync_availability()
        else:
            self._show_error("发送失败，稍后再试。")

    def _on_chat_done(self, result, error) -> None:
        if not self._pending:
            return
        self._pending = False
        if error is not None:
            self._show_error(getattr(error, "hint", "") or str(error) or "请求失败，稍后再试。")
            return
        text = _reply_text(result)
        if text is None:
            self._show_error(_result_error_hint(result))
            return
        note = getattr(self.companion, "note_local_reply", None)
        if callable(note):
            try:
                note(_result_message_id(result))
            except Exception:
                pass
        self._set_reply_text(text)
        self.hint_label.setText("")
        if self._request_presentation_valid():
            self._render_reply()
        else:
            self.hide()

    def _show_error(self, hint: str) -> None:
        self.hint_label.setText("")
        self._set_reply_text(str(hint or "请求失败，稍后再试。"))
        self._render_reply()

    def _request_presentation_valid(self) -> bool:
        target = getattr(self, "_request_pet_window", self.pet_window)
        valid = getattr(target, "presentation_valid", None)
        return target is self.pet_window and (not callable(valid) or bool(valid()))

    def request_in_flight(self) -> bool:
        """是否有自己发出的、尚未到终态的请求在途。"""
        return self._pending

    # ------------------------------------------------------------ 显示
    def _set_reply_text(self, full_text: str) -> None:
        """记录回复全文，并算出气泡内展示文本（超限截断）。"""
        self._reply_full = str(full_text or "")
        self._reply_text = truncate_bubble_text(
            self._reply_full, _REPLY_PREVIEW_LIMIT, _REPLY_PREVIEW_SUFFIX
        )
        self._reply_truncated = self._reply_text != self._reply_full

    def _set_page_controls_visible(self, on: bool) -> None:
        """显示/隐藏分页箭头与页码（截断预览时只保留「去聊天窗」按钮）。"""
        for widget in (self.prev_btn, self.page_label, self.next_btn):
            widget.setVisible(on)

    def _render_reply(self) -> None:
        text = self._reply_text
        if len(text) > _PAGE_SIZE:
            self._pages = [text[i:i + _PAGE_SIZE] for i in range(0, len(text), _PAGE_SIZE)]
            self._show_page(0)
            self._set_page_controls_visible(True)
            self.page_widget.setVisible(True)
            return
        self._pages = []
        self._set_page_controls_visible(not self._reply_truncated)
        self.page_widget.setVisible(self._reply_truncated)
        self._set_output_markdown(text)

    def _show_page(self, index: int) -> None:
        if not self._pages:
            return
        self._page = max(0, min(index, len(self._pages) - 1))
        self._set_output_markdown(self._pages[self._page])
        self.page_label.setText(f"{self._page + 1}/{len(self._pages)}")

    def _set_output_markdown(self, text: str) -> None:
        """回复按 Markdown 渲染（与现代聊天窗同一 markdown_to_html 口径）。"""
        if not text:
            self.output.setText("")
            return
        self.output.setTextFormat(Qt.TextFormat.RichText)
        self.output.setText(markdown_to_html(text))
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < len(self._pages) - 1)

    def _open_full_chat(self) -> None:
        pet = self.pet_window
        if pet is not None and callable(getattr(pet, "on_open_chat", None)):
            pet.on_open_chat()
        elif hasattr(self, "open_chat_callback") and callable(self.open_chat_callback):
            self.open_chat_callback()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            if not self._deactivate_check_pending:
                self._deactivate_check_pending = True
                QTimer.singleShot(0, self, self._close_if_still_inactive)
        return super().event(event)

    def _close_if_still_inactive(self) -> None:
        self._deactivate_check_pending = False
        if self.isVisible() and QApplication.activeWindow() is not self:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.set_companion(None)
        super().closeEvent(event)
