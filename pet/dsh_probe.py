# -*- coding: utf-8 -*-
"""DSH（DeepSeek Harness）**进程/端口只读探测**（Qt-free，核心共用）。

这些探测有两个消费者：

- ``pet/agent_link.py``（DSH 联动读方）只关心「dsh web 是否在线」「桌面端是否
  在跑」；
- ``pet/modules/harness`` 的一键启动器需要同一组事实（候选端口、进程身份）。

放在核心而不是模块里，是为了让 agent_link 不必 import 具体模块（架构测试禁止
核心 import 模块）；模块运行时反过来 import 这里是允许的。本文件**只读**，
不拉起、不终止任何进程。
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

#: dsh web 默认端口（3080 会落入 Windows winnat/Hyper-V 动态保留段）。
DEFAULT_PORT = int(os.environ.get("DSH_PORT") or 38080)

#: 桌面端自动拉起/探测目前仅 Windows 支持。
DESKTOP_SUPPORTED = os.name == "nt"

DESKTOP_APP_NAME = "DeepSeek Harness"
DESKTOP_EXE_NAME = "DeepSeek Harness.exe"


def is_running(port: int = DEFAULT_PORT) -> bool:
    """探测 127.0.0.1:port 是否有服务监听。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def candidate_ports(port: int = DEFAULT_PORT) -> list[int]:
    """复用已有实例的候选端口：配置端口优先，其次官方默认 3080。"""
    ports: list[int] = []
    for p in (int(port), 3080):
        if p not in ports:
            ports.append(p)
    return ports


def pid_image_path(pid: int) -> str | None:
    """进程可执行文件路径（身份核验用；读不到返回 None）。"""
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)
                )
                return buf.value if ok else None
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return os.readlink(f"/proc/{int(pid)}/exe")
    except Exception:
        return None


def desktop_processes() -> list[int]:
    """正在运行的桌面端进程 pid 列表（只读枚举；平台不支持/读不到返回 []）。"""
    if not DESKTOP_SUPPORTED:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        arr = (wintypes.DWORD * 4096)()
        needed = wintypes.DWORD(0)
        if not ctypes.windll.psapi.EnumProcesses(
            ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed),
        ):
            return []
        pids: list[int] = []
        for pid in arr[: needed.value // 4]:
            if not pid:
                continue
            image = pid_image_path(int(pid))
            if image and Path(image).name.lower() == DESKTOP_EXE_NAME.lower():
                pids.append(int(pid))
        return pids
    except Exception:
        logger.debug("桌面端进程枚举失败", exc_info=True)
        return []


def desktop_process_running() -> bool:
    """桌面端进程是否在跑（端口探测全 miss 时的 online 旁路判定）。"""
    return bool(desktop_processes())


__all__ = [
    "DEFAULT_PORT", "DESKTOP_APP_NAME", "DESKTOP_EXE_NAME", "DESKTOP_SUPPORTED",
    "candidate_ports", "desktop_process_running", "desktop_processes",
    "is_running", "pid_image_path",
]
