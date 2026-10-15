"""Application-owned focus clock and one bounded background observation pipeline."""
from __future__ import annotations

import copy
import io
import logging
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .focus_mode import (focus_prompt, normalize_focus_config,
                         parse_observation, shared_focus_session)
from .proactive_limiter import ProactiveLimiter


def foreground_observation_available():
    return sys.platform == "win32"


class FocusController(QObject):
    changed = Signal()
    _result = Signal(int, str, str, str)

    def __init__(self, config, presentation, *, identity_config=None, session=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.presentation = presentation
        self.identity_config = identity_config or (lambda: config)
        self.session = session or shared_focus_session()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._result.connect(self._deliver)
        self._busy = False
        self._closed = False
        self._next_check = 0.0
        self._last_speech = None
        self._recent = []
        self._last_config = None
        self.limiter = ProactiveLimiter(config.dir / "focus_ai_state.json", {})
        self._previous_phase = self.session.phase
        self._previous_status = self.session.status
        self.session.add_listener(self._transition)

    def _transition(self):
        if self._closed:
            return
        old_phase, old_status = self._previous_phase, self._previous_status
        self._previous_phase, self._previous_status = self.session.phase, self.session.status
        self._next_check = time.monotonic() + self._preferences()["check_minutes"] * 60
        if self.session.status == "running":
            self.timer.start()
        else:
            self.timer.stop()
        self._recent.clear()
        if self.session.focusing:
            for host in getattr(self.presentation, "_windows", lambda: [])():
                cancel = getattr(host, "_cancel_move", None)
                if callable(cancel):
                    cancel()
        if self.session.focusing and not self._preferences()["work_context"]:
            self.session.observation = "未填写工作背景，仅提供专注鼓励；可在设置中长期保存背景。"
        if self.session.status == "idle":
            self._last_speech = None
        if (self.session.status == "running"
                and (old_status == "idle" or old_phase != self.session.phase)):
            self._play_phase_sound("agent-start" if self.session.phase == "focus" else "agent-done")
        elif self.session.status == "idle" and old_status != "idle":
            self._play_phase_sound("agent-done")
        self.changed.emit()

    def _play_phase_sound(self, sound_id):
        from . import window_alerts
        if window_alerts.quiet_blocked(self.presentation):
            return
        try:
            from .click_sound import play_sound, resolve_builtin_sound
            path = resolve_builtin_sound(sound_id)
            if path is not None:
                play_sound(path, volume=0.65)
        except Exception:
            # Device/backend failures must never interrupt the timer or cycle.
            logging.getLogger(__name__).warning("专注提示音播放失败", exc_info=True)

    def _preferences(self):
        return normalize_focus_config(self.config.get("focus_mode"))

    def _tick(self):
        self.session.tick(self._preferences())
        self.changed.emit()
        if self.session.focusing and time.monotonic() >= self._next_check:
            self.request_observation()

    def request_observation(self):
        """Snapshot GUI-owned data, then perform OS capture/network only on the worker."""
        if self._closed or self._busy or not self.session.focusing:
            return False
        from . import window_alerts
        if (not self.presentation.has_presentation_target()
                or window_alerts.quiet_blocked(self.presentation)
                or getattr(self.presentation, "_sticky_bubble_active", False)
                or time.monotonic() < getattr(self.presentation, "_bubble_busy_until", 0.0)):
            return False
        cfg = self._preferences()
        self._next_check = time.monotonic() + cfg["check_minutes"] * 60
        limit_cfg = {"preset": "custom", "cooldown_minutes": cfg["check_minutes"],
                     "min_request_interval_seconds": cfg["check_minutes"] * 60,
                     "daily_cap": cfg["daily_cap"], "dry_run": False}
        self.limiter.update_config(limit_cfg, dry_run=False)
        allowed, reason = self.limiter.allow()
        if not allowed:
            explanation = {"daily_cap_reached": "今日请求额度已用完，明天恢复",
                           "paused_by_circuit_breaker": "连续请求失败，今天停止自动请求",
                           "min_request_interval_cooldown": "请求间隔冷却中",
                           "cooldown_active": "陪伴提醒冷却中"}.get(reason, reason)
            self.session.observation = f"专注 AI 暂停：{explanation}"
            self.changed.emit()
            return False
        identity = self.identity_config()
        try:
            from . import catalog
            from .chat.prompt import PromptBuilder
            settings = identity.chat_settings()
            provider = copy.copy(settings.active_config)
            provider.api_key = identity.resolve_api_key(provider)
            character = str(identity.get("character", catalog.DEFAULT_CHARACTER))
            root = catalog.resolve_character_video_dir(character).parent.parent
            persona = PromptBuilder(root).effective_system_prompt(settings, character)
            visual = bool(cfg["screen_enabled"] and cfg["work_context"] and foreground_observation_available())
            prompt = focus_prompt(persona, cfg["work_context"], visual=visual)
        except Exception as exc:
            self.session.observation = f"专注 AI 不可用：{type(exc).__name__}"
            self.changed.emit()
            return False
        if self._last_config != cfg:
            self._recent.clear()
            self._last_config = cfg
        token = self.session.generation
        self._busy = True
        self.session.observation = "正在观察前台窗口……" if visual else "正在准备专注鼓励……"
        self.changed.emit()
        threading.Thread(target=self._request, args=(token, provider, prompt, visual, tuple(self._recent)),
                         daemon=True, name="focus-observation").start()
        return True

    def _request(self, token, provider, prompt, visual, recent):
        # No Qt/widget/config access on this thread. All output is queued to _deliver.
        try:
            from . import vision
            if self._closed or token != self.session.generation:
                self._publish(token, "", "", "cancelled")
                return
            if not self.limiter.try_acquire()[0]:
                self._publish(token, "", "", "请求频率或额度限制")
                return
            def consume_budget():
                return (not self._closed and token == self.session.generation
                        and self.session.focusing and self.limiter.consume_budget())

            if visual:
                info = vision.foreground_window_info()
                if not info:
                    raise RuntimeError("当前没有可观察的前台窗口")
                image = vision.capture_window_rect(info["rect"])
                if image is None:
                    raise RuntimeError("前台窗口截图不可用")
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, "JPEG", quality=70)
                reply = vision._post_vision_request(
                    buffer.getvalue(), "", prompt, provider,
                    consume_budget=consume_budget,
                    user_text="观察当前前台窗口，结合工作背景判断。近期判断：" + ", ".join(recent))
                kind, message = parse_observation(reply)
            else:
                # Use the same transport, provider/key rules, and per-HTTP budget as vision.
                messages = [{"role": "system", "content": prompt},
                            {"role": "user", "content": "请用自己的口吻，简短地陪我专注。"}]
                message = vision._post_vision_request(
                    b"", "", prompt, provider, messages_override=messages,
                    consume_budget=consume_budget).strip()[:180]
                kind = "encouragement"
            if (visual and not reply.strip()) or (not visual and not message):
                raise RuntimeError("模型返回空内容")
            self.limiter.record_success()
            # A settings edit while the request is in flight invalidates its task context too.
            self._publish(token, kind, message, "")
        except Exception as exc:
            if not self._closed and token == self.session.generation:
                self.limiter.record_failure()
            self._publish(token, "", "", f"{type(exc).__name__}: {str(exc)[:160]}")

    def _publish(self, token, kind, message, error):
        if self._closed:
            return
        try:
            self._result.emit(token, kind, message, error)
        except RuntimeError:
            pass  # QApplication may already have destroyed this QObject during exit.

    def _deliver(self, token, kind, message, error):
        self._busy = False
        if self._closed or token != self.session.generation or not self.session.focusing:
            return
        if self._last_config != self._preferences():
            self.session.observation = "设置已更新，下一次使用新的工作背景与偏好。"
            self.changed.emit()
            return
        if error:
            self.session.observation = f"专注 AI 暂不可用：{error}"
            self.changed.emit()
            return
        labels = {"on_task": "当前画面与工作相关", "off_task": "当前画面可能偏离工作",
                  "uncertain": "当前画面不足以判断", "encouragement": "专注陪伴"}
        self.session.observation = labels.get(kind, "当前画面不足以判断")
        if kind != "encouragement":
            self._recent = (self._recent + [kind])[-3:]
        now = time.monotonic()
        cooldown = 300 if kind == "off_task" else self._preferences()["check_minutes"] * 60
        from . import window_alerts
        if (message and self.presentation.has_presentation_target()
                and not window_alerts.quiet_blocked(self.presentation)
                and not getattr(self.presentation, "_sticky_bubble_active", False)
                and now >= getattr(self.presentation, "_bubble_busy_until", 0.0)
                and (self._last_speech is None or now - self._last_speech >= cooldown)):
            self.presentation.show_bubble(message, duration_ms=8000)
            self._last_speech = now
        self.changed.emit()

    def stop(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.session.remove_listener(self._transition)
        self.session.stop()
