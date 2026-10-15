"""Bounded text-only observations, cached persona farewell and local history."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading

_WRITE_LOCK = threading.Lock()
_DURATION = "{focus_duration}"


def _text(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def reply_object(reply):
    try:
        text = reply.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        raw = json.loads(text)
        return raw if isinstance(raw, dict) else {}
    except (ValueError, AttributeError, IndexError):
        return {}


def parse_work_memory(reply):
    raw = reply_object(reply)
    if raw.get("assessment") != "on_task":
        return "", ""
    return _text(raw.get("work_summary"), 80), _text(raw.get("closing_template"), 160)


def duration_text(seconds):
    seconds = max(0, int(seconds))
    if not seconds:
        return "不到1秒"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时" + (f"{minutes}分" if minutes else "") + (f"{seconds}秒" if seconds else "")
    if minutes:
        return f"{minutes}分{seconds}秒" if seconds else f"{minutes}分钟"
    return f"{seconds}秒"


class FocusNotes:
    def __init__(self):
        self.work = []
        self.template = self.character = ""

    def remember(self, kind, summary, template, character):
        if kind not in ("on_task", "encouragement"):
            return
        summary = _text(summary, 80) if kind == "on_task" else ""
        if summary and (not self.work or self.work[-1] != summary):
            self.work = (self.work + [summary])[-6:]
        template = _text(template, 160)
        if template.count(_DURATION) == 1:
            self.template, self.character = template, character

    def closing(self, seconds, character):
        duration = duration_text(seconds)
        if self.template and self.character == character:
            return self.template.replace(_DURATION, duration)
        if character == "shenshen":
            work = f"看到你在{self.work[-1]}，" if self.work else ""
            return f"陪你忙了{duration}，{work}辛苦啦！先伸个懒腰，鱼脑袋也陪你歇一下。"
        return f"这次专注了{duration}，辛苦啦，放松一下吧。"


def _record(raw):
    def number(key):
        try:
            return max(0, min(2**31 - 1, int(raw.get(key, 0))))
        except (TypeError, ValueError, OverflowError):
            return 0
    work = raw.get("observed_work", [])
    return {"ended_at": _text(raw.get("ended_at"), 40), "character": _text(raw.get("character"), 64),
            "focus_seconds": number("focus_seconds"), "completed": number("completed"),
            "work_context": _text(raw.get("work_context"), 240),
            "observed_work": [_text(item, 80) for item in work[-6:] if isinstance(item, str)]
                             if isinstance(work, list) else []}


class FocusHistory:
    """One ephemeral writer, at most ten pending/finished sessions, no Qt access."""
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._pending = deque(maxlen=10)
        self._thread = None
        self._failed = False

    def record(self, snapshot):
        record = _record(snapshot)
        record["ended_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._pending.append(record)
            if self._thread is None:
                self._thread = threading.Thread(target=self._save_pending, daemon=True, name="focus-history-writer")
                self._thread.start()

    def _save_pending(self):
        while True:
            with self._lock:
                if not self._pending:
                    self._thread = None
                    return
                batch = list(self._pending)
                self._pending.clear()
            try:
                from .config import atomic_replace_with_retry
                with _WRITE_LOCK:
                    sessions = []
                    if self.path.exists():
                        with self.path.open("rb") as stream:
                            payload = stream.read(65537)
                        if len(payload) > 65536:
                            raise ValueError("focus history exceeds size bound")
                        data = json.loads(payload)
                        if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
                            raise ValueError("invalid focus history")
                        sessions = [_record(item) for item in data["sessions"][-10:] if isinstance(item, dict)]
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temp = self.path.with_name(self.path.name + ".tmp")
                    try:
                        temp.write_text(json.dumps({"version": 1, "sessions": (sessions + batch)[-10:]},
                                                   ensure_ascii=False), encoding="utf-8")
                        atomic_replace_with_retry(temp, self.path)
                    finally:
                        temp.unlink(missing_ok=True)
            except Exception:
                with self._lock:
                    self._failed = True
                logging.getLogger(__name__).warning("专注工作摘要保存失败，保留已有文件", exc_info=True)

    def flush(self, timeout=1.0):
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        with self._lock:
            ok = self._thread is None and not self._failed
            self._failed = False
        return ok
