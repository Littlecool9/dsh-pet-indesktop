# -*- coding: utf-8 -*-
"""Minimal Win32 process helpers for the foreground-window probe.

The FPS monitor used to borrow ``Win32ProcessApi`` from the deleted memory-trim
action. Only the foreground lookup / image-name subset is needed here, so this
neutral module keeps that small ctypes surface without the trimming machinery.
"""
from __future__ import annotations

import ctypes
import ntpath
import sys

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
TRIM_ACCESS = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA

_INVALID_HANDLE = ctypes.c_void_p(-1).value
_INVALID_HANDLE_MASK = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
_INVALID_HANDLE_VALUES = frozenset({_INVALID_HANDLE, 0xFFFFFFFF})


def _invalid_handle(handle) -> bool:
    if not handle:
        return True
    return (int(handle) & _INVALID_HANDLE_MASK) in _INVALID_HANDLE_VALUES


def _load_library(name: str):
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise OSError("当前平台没有 WinDLL（前台窗口查询仅支持 Windows）")
    return loader(name, use_last_error=True)


class Win32ProcessApi:
    """kernel32 / user32 的 ctypes 薄封装（仅前台窗口与进程名）。"""

    supported = sys.platform == "win32"

    def __init__(self, kernel32=None, user32=None) -> None:
        self._kernel32 = kernel32 if kernel32 is not None else _load_library("kernel32")
        self._user32 = user32 if user32 is not None else _load_library("user32")
        if kernel32 is not None and user32 is not None:
            self.supported = True
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        k32, user32 = self._kernel32, self._user32
        try:
            k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.restype = ctypes.c_int
            k32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            k32.QueryFullProcessImageNameW.restype = ctypes.c_int
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
            ]
            user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
        except AttributeError:  # pragma: no cover - 替身少写方法时回退默认转换
            pass

    def open_process(self, pid: int) -> int:
        return self._kernel32.OpenProcess(TRIM_ACCESS, 0, int(pid)) or 0

    def close_handle(self, handle) -> None:
        if not _invalid_handle(handle):
            self._kernel32.CloseHandle(handle)

    def image_name(self, handle) -> str:
        buffer = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(len(buffer))
        if not self._kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return ntpath.basename(buffer.value or "")

    def foreground_pid(self) -> int | None:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_uint32()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
