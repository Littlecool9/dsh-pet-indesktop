# -*- coding: utf-8 -*-
"""桌宠槽位身份与运行时标记。

多宠已删除（只剩 slot 0）：跨进程 slot 文件锁、旧 spawn 迁移与多身份落种
都不再存在；``config-slot-N.json``（N > 0）只会被留在盘上、不再读写。

保留面：

- ``backup_corrupt_config``：``Config._load`` 的核心依赖（损坏配置备份）；
- **runtime 标记 API**（``write/delete/read_live_instances``）：独立设置进程
  避让桌宠几何的通道。

纯 Python 实现，不依赖 Qt。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .config import atomic_replace_with_retry


def _atomic_write_text(path: Path, text: str) -> None:
    """temp + ``os.replace`` 原子写入（缺陷 18）。失败上抛 OSError，由调用方处理。

    本文件的两处写盘（slot 落种 / runtime 标记）此前都是 ``path.write_text``
    直写：读者（主进程 Config._load、独立设置进程 read_live_instances）会在
    写盘中途读到半截 JSON。临时名带 PID 且以 ``.tmp`` 结尾（不匹配
    ``runtime-*.json`` / ``pet-runtime-v2-*.json`` 两个 glob，不会被读侧当成
    标记）；替换走 config 的退避重试（骑过 Windows 读句柄造成的瞬时共享
    冲突），任何出口都清掉临时文件。
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        atomic_replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def backup_corrupt_config(config_file: Path) -> Path | None:
    """损坏配置备份：使用毫秒时间戳加 PID 后缀，连续恢复不覆盖旧备份。"""
    if not config_file.is_file():
        return None
    timestamp = int(time.time() * 1000)
    backup_file = config_file.with_name(f"{config_file.name}.corrupt-{timestamp}-{os.getpid()}")
    try:
        shutil.copy2(config_file, backup_file)
        return backup_file
    except Exception as exc:
        logging.error("备份损坏配置文件失败: %s -> %s (%s)", config_file, backup_file, exc)
        return None


def pid_alive(pid: int) -> bool:
    """跨平台探活：Windows 用 OpenProcess + GetExitCodeProcess，其余用 kill(pid, 0)。"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION（Vista+ 即可查退出码）
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            # 句柄打得开 ≠ 进程还活着：进程被 TerminateProcess 后，只要还有人
            # 持着它的句柄（如父进程的 Popen 尚未 reap），进程对象不会销毁，
            # OpenProcess 一路成功。只有退出码仍是 STILL_ACTIVE 才算存活。
            # 同 pet/harness_launcher.py::_windows_pid_alive 的既有判定口径。
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --- 批5.2 R4：runtime 标记格式版本化（多窗每窗一份，旧 glob 不匹配）--------
# 旧版（runtime-<pid>.json）用 glob('runtime-*.json') 读取；为避免新旧混跑时
# 旧版把新版标记也计入「存活实例」而虚高计数（多开位置避让被干扰），新版标记
# 改用不与 'runtime-*.json' 匹配的 pet-runtime-v2-<pid>-slot-<N>.json 前缀。
# 4.4b：本 API 是 D7 设置进程避让几何通道（overlay 壳写、独立设置进程读），
# 与多进程多宠退役层无关，保留。
_RUNTIME_V2_PREFIX = "pet-runtime-v2-"


def _slot_label(instance_id: str) -> str:
    """从 instance_id 提取 slot 标签（用于 runtime 标记文件名）。"""
    s = str(instance_id or "").strip()
    if not s or s == "slot-0":
        return "0"
    if s.startswith("slot-"):
        return s[len("slot-"):] or "0"
    return re.sub(r"[^A-Za-z0-9_-]", "_", s) or "0"


def runtime_marker_name(instance_id: str = "", *, versioned: bool = False) -> str:
    """返回某窗 runtime 标记文件名。versioned=False 用旧名
    runtime-<pid>.json（单窗时保持旧行为）；True 用版本化新名
    pet-runtime-v2-<pid>-slot-<N>.json（批5.2 多窗，规避旧 glob 匹配）。"""
    pid = os.getpid()
    if versioned:
        return f"{_RUNTIME_V2_PREFIX}{pid}-slot-{_slot_label(instance_id)}.json"
    return f"runtime-{pid}.json"


def runtime_marker_path(config_dir: Path | str, instance_id: str = "",
                        *, versioned: bool = False) -> Path:
    """返回某窗 runtime 标记的完整路径。"""
    return Path(config_dir) / runtime_marker_name(instance_id, versioned=versioned)


def write_runtime_marker(config_dir: Path | str, instance_id: str,
                         x: int, y: int, w: int, h: int,
                         *, versioned: bool = False) -> Path:
    """写入本窗 runtime 标记（旧格式仅主窗用；versioned 多窗用）。

    写版本化标记时顺手清掉同 pid 的旧格式标记，避免同进程混用重复计数。
    写入走 temp + 原子替换（缺陷 18）：设置进程的 read_live_instances 会在
    任意时刻读这些标记，直写会被它读到半截 JSON（旧行为据此把标记当陈旧删掉，
    活进程的避让几何凭空消失）。
    """
    path = runtime_marker_path(config_dir, instance_id, versioned=versioned)
    try:
        if versioned:
            legacy = Path(config_dir) / f"runtime-{os.getpid()}.json"
            try:
                if legacy.exists():
                    legacy.unlink()
            except OSError:
                pass
        _atomic_write_text(path, json.dumps({
            'pid': os.getpid(),
            'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
        }))
    except OSError:
        pass
    return path


def delete_runtime_marker(config_dir: Path | str, instance_id: str = "") -> None:
    """删除本窗 runtime 标记（「退出这只」必须显式删，否则活 pid 的陈旧
    标记永久虚增计数/避让错乱）。新旧两种命名都尝试删（跨格式迁移兜底）。"""
    for ver in (True, False):
        try:
            path = runtime_marker_path(config_dir, instance_id, versioned=ver)
            if path.exists():
                path.unlink()
        except OSError:
            pass


def read_live_instances(
    config_dir: Path | str,
    *,
    exclude_pid: int | None = None,
    exclude_markers=None,
    pid_alive_fn=None,
) -> list[tuple[int, int, int, int, int]]:
    """读取目录内 runtime 标记，返回存活实例 (pid, x, y, w, h) 列表。

    同时认旧（runtime-<pid>.json）与新（pet-runtime-v2-*）两种命名
    （避让定位兼容新旧混跑）。**pid 已确认死亡的**标记顺手删除（避免越积越多）；
    exclude_markers（本窗自己的标记路径/文件名）跳过且保留——同 pid 多窗下不能
    再用 exclude_pid 这种按 pid 过滤的方式（会把同进程所有窗都排除）。
    pid_alive_fn 可注入（测试用）。

    缺陷 18：解析失败（半写文件）或字段非法（判不出 pid）的标记**只跳过、不删**
    ——写侧此刻可能正写到一半，删掉等于把活进程的避让标记清掉；只有确认 pid
    已死的标记才回收。
    """
    alive = pid_alive_fn if pid_alive_fn is not None else pid_alive
    try:
        exclude_names = {Path(m).name for m in (exclude_markers or ())}
    except (TypeError, OSError):
        exclude_names = set()
    instances: list[tuple[int, int, int, int, int]] = []
    try:
        files = list(Path(config_dir).glob('runtime-*.json'))
        files.extend(Path(config_dir).glob(f'{_RUNTIME_V2_PREFIX}*.json'))
    except OSError:
        return instances
    for f in files:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue  # 半写/损坏：判不出 pid，绝不删（可能是活进程正在写的文件）
        try:
            pid = int(data.get('pid', 0))
        except (AttributeError, TypeError, ValueError):
            continue  # 非对象 / pid 类型非法：同样只跳过不删
        if exclude_pid is not None and pid == exclude_pid:
            continue
        if f.name in exclude_names:
            continue
        if not alive(pid):
            # pid 已确认死亡：唯一的删除时机（陈旧标记不再虚增避让计数）。
            try:
                f.unlink()
            except OSError:
                pass
            continue
        try:
            x, y, w, h = (int(data.get(k, 0)) for k in ('x', 'y', 'w', 'h'))
        except (TypeError, ValueError):
            continue  # 进程还活着但几何非法：跳过并保留（下次写盘自然刷新）
        instances.append((pid, x, y, w, h))
    return instances
