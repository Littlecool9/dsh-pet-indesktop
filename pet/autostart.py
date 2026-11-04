# -*- coding: utf-8 -*-
"""开机自启动管理（Windows）。

- Windows：HKCU Run 注册表键（无需管理员权限）。

设计原则：**系统自启配置是唯一真相**。菜单勾选状态直接查它们，不与 config.json
冗余存储，避免两处状态不同步。

命令按运行形态自适应：
- PyInstaller 打包（sys.frozen）：先用 `start /D` 切到 exe 所在目录再启动 exe；
- 源码运行：用 `pythonw -m pet`（带工作目录）。
"""

from __future__ import annotations

import os
import re
import sys
import winreg
from pathlib import Path

from .config import APP_DIR_NAME

# Windows 自启注册表值名按变体隔离（如 dsh-pet-standalone-webm-chat）。
# 每个变体只管理自己的值，避免“关无 Chat 版把 Chat 版也关了”。
VALUE_NAME = APP_DIR_NAME
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# 历史/各变体可能写入过的值名；仅用于启动时清理“指向已不存在路径”的失效项，
# 不影响其他仍有效的变体自启。
KNOWN_VALUE_NAMES = (
    "dsh-pet-standalone",
    "dsh-pet-standalone-webm",
    "dsh-pet-standalone-webm-chat",
    "dsh-pet-standalone-gif",
    "dsh-pet-standalone-gif-chat",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _pythonw_path() -> str:
    """源码运行时，取与 python.exe 同目录的 pythonw.exe（无控制台窗口）。"""
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        return exe[: -len("python.exe")] + "pythonw.exe"
    return exe


def _win_command_is_current(command: str) -> bool:
    """判断自启命令是否已是“先切工作目录再启动”的新格式。"""
    return "cmd /c start" in command.lower()


def _iter_known_win_values() -> list[tuple[str, str]]:
    """读取注册表里所有已知 dsh-pet 自启值，返回 [(name, command), ...]。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            found = []
            for name in KNOWN_VALUE_NAMES:
                try:
                    command, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                found.append((name, str(command or "")))
            return found
    except OSError:
        return []


def _win_command_target_exists(command: str) -> bool:
    """判断自启命令引用的路径是否仍然存在。

    命令格式形如：
      cmd /c start "" /D "C:\\path\\to\\dir" "C:\\path\\to\\app.exe"
    只要任一被引用的非空路径已不存在，就视为失效自启项。
    """
    if not isinstance(command, str) or not command.strip():
        return False
    quoted = re.findall(r'"([^"]*)"', command)
    paths = [item for item in quoted if item.strip()]
    if not paths:
        return True
    return all(Path(item).exists() for item in paths)


def cleanup_stale_entries() -> int:
    """清理指向已不存在路径的失效开机自启项。

    用户“更新后直接删除旧目录但忘了关自启”时，HKCU Run 里会残留指向
    已删除路径的命令，导致每次开机弹终端报“找不到文件夹”。这里只删除
    路径已失效的已知 dsh-pet 项，不影响其他仍有效的变体自启。
    """
    removed = 0
    try:
        for name, command in _iter_known_win_values():
            if _win_command_target_exists(command):
                continue
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                try:
                    winreg.DeleteValue(key, name)
                    removed += 1
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return removed


def is_enabled() -> bool:
    """当前变体是否已注册开机自启（只查当前变体自己的注册表值）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, VALUE_NAME)
            # 兼容旧版：已开启但仍是旧命令（直接指向 exe，未切工作目录）时，
            # 自动升级为新命令，避免开机自启因 CWD 不可写而解压失败。
            # 同理：由 start-local.bat 启动时，已有的 pythonw -m pet 旧值升级为走 start-local。
            frozen_outdated = (
                getattr(sys, "frozen", False)
                and isinstance(command, str)
                and not _win_command_is_current(command)
            )
            local_outdated = (
                not getattr(sys, "frozen", False)
                and _local_launcher() is not None
                and command != _win_command()
            )
            if frozen_outdated or local_outdated:
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
                    ) as write_key:
                        winreg.SetValueEx(
                            write_key, VALUE_NAME, 0, winreg.REG_SZ, _win_command()
                        )
                except OSError:
                    # 只读场景（如权限异常）不强求升级，仍视为已启用
                    pass
            return True
    except FileNotFoundError:
        # 只认当前变体自己的值；其他变体的自启状态互不影响。
        return False


def _local_launcher() -> Path | None:
    """当前进程是否由 start-local.bat 启动（APPDATA 指向 <仓库>\\.local\\appdata）。

    是的话返回该 bat 的路径：开机自启必须也走它，否则 pythonw -m pet 会读 %APPDATA%
    下另一份配置，开机起来的桌宠和平时用的不是同一套设置。
    """
    root = _project_root()
    launcher = root / "start-local.bat"
    appdata = os.environ.get("APPDATA", "")
    if not appdata or not launcher.is_file():
        return None
    try:
        if Path(appdata).resolve() != (root / ".local" / "appdata").resolve():
            return None
    except OSError:
        return None
    return launcher


def _win_command() -> str:
    if getattr(sys, "frozen", False):
        # onefile 的 runtime_tmpdir="." 是相对“当前工作目录”解析的；
        # 开机自启（HKCU Run）默认工作目录可能是 System32 等不可写目录。
        # 用 start 先切到 exe 所在目录再启动 exe，既保证解压目录在 exe 同目录，
        # 又不会让 cmd 窗口一直等待桌宠退出。
        exe = Path(sys.executable).resolve()
        return f'cmd /c start "" /D "{exe.parent}" "{exe}"'
    launcher = _local_launcher()
    if launcher is not None:
        # start-local.bat 自己 cd 到仓库、设好 APPDATA/PYTHONUTF8，再用 start 脱离 cmd。
        return f'cmd /c "{launcher}"'
    return f'cmd /c start "" /D "{_project_root()}" "{_pythonw_path()}" -m pet'


def enable() -> bool:
    """开启自启；返回是否写入成功（回读注册表验证）。"""
    try:
        # 只写当前变体自己的值，不影响其他 Chat/无 Chat 变体的自启状态。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _win_command())
        # 回读验证，防止写入被安全软件/策略静默拦截
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def disable() -> bool:
    """关闭自启；返回是否已清除。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    return enable() if on else disable()
