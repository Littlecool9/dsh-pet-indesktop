# -*- coding: utf-8 -*-
"""卸载清理：删除自启项、移除 Claude hooks、卸载 DSH 桥接插件。

供 `--uninstall-cleanup` 参数使用——安装包（Inno Setup）卸载时调用。两个冻结
入口（`packaging/pet_entry.py` / `pet_entry_no_chat.py`）必须在 import `pet.app`
之前分流到本模块的 :func:`main`，否则参数会当成普通启动、清理根本不会执行。

该路径不启动 QApplication/事件循环，只做必要的清理，便于「无 Qt 依赖路径」
（仍可 import Qt 模块，但不建窗口）下执行。

功能自己的清理（Claude hooks / DSH 桥接插件）由模块清单的
``extra["uninstall_cleanup"]`` 字符串入口提供；模块没登记 = 功能关闭，这里自然跳过。
多实例占用判断（语义并集：当前变体目录 + <base> 下全部变体任一认为在用即保留）
仍由本模块提供，模块侧只消费。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

# 结果留痕文件名（写在配置目录里）：冻结入口是 windowed exe，没有控制台，
# 只靠 stdout 的话卸载清理的结果在用户机器上等于消失。
RESULT_LOG_NAME = "uninstall-cleanup.log"


def other_instances_use_agent(config, agent_key: str) -> bool:
    """另一个本地安装点（变体/独立实例）是否也开着该全局 Agent 联动。

    "其他实例" = 别的变体目录的配置，或本变体目录里按 ``--instance <id>`` 隔离出来的
    旧式独立实例配置。**不含本变体自己的 ``config-slot-N.json``**：那是固定身份的每宠
    档案（``pet_profiles`` §五，全局键不落档案），历史「整表落种」复制进去的
    ``agent_link`` 只是一份旧快照——按它判定会让卸载被本变体自己残留的档案挡住，
    hooks/桥接插件清不掉。别的变体目录、旧共享目录、旧式非 slot 实例照旧保护
    （hooks/桥接插件是跨变体共享的全局状态）。
    """
    config_dir = Path(config.dir)
    seen: set[Path] = set()
    candidates: list[Path] = []
    try:
        candidates.append(config_dir / "config.json")
        candidates.extend(config_dir.glob("config-*.json"))
        candidates.extend(config_dir.parent.glob("dsh-pet-standalone*/config*.json"))
    except OSError:
        pass
    from .pet_profiles import _SLOT_PROFILE_RE

    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if config.path and path == config.path:
            continue
        if path.parent == config_dir and _SLOT_PROFILE_RE.match(path.name):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and bool((data.get("agent_link") or {}).get(agent_key, False)):
            return True
    return False


def _module_cleanup_entries() -> list:
    """各已登记模块声明的卸载清理入口（仅框架读取；坏包/坏入口只记日志）。"""
    from .modules import MODULES
    from .modules.base import load_entry
    from .modules.registry import read_manifest

    entries = []
    for package in MODULES:
        try:
            manifest = read_manifest(package)
            entry = manifest.extra.get("uninstall_cleanup")
            if entry:
                entries.append(load_entry(entry))
        except Exception:
            logging.getLogger(__name__).exception(
                "读取模块 %s 的卸载清理入口失败，已跳过", package)
    return entries


def run_uninstall_cleanup(config=None) -> dict:
    """执行卸载清理各步骤，返回结果字典（供测试与日志）。

    步骤：
    1. 删除当前变体开机自启项（autostart.disable）；
    2. 各已登记模块声明的清理（Agent 联动：移除 Claude hooks / 卸载 DSH 桥接插件）。
    """
    from . import autostart

    if config is None:
        from .config import Config
        config = Config()

    results = {"autostart": bool(autostart.disable())}
    for cleanup in _module_cleanup_entries():
        try:
            result = cleanup(config)
        except Exception:
            logging.getLogger(__name__).exception("模块卸载清理失败")
            continue
        if isinstance(result, dict):
            results.update(result)
    return results


def _describe_step(value) -> str:
    if value is True:
        return "ok"
    if value == "skipped":
        return "skipped（其他实例仍在使用，保留）"
    return "failed"


def _format_results(results: dict, error: str) -> list[str]:
    lines = ["dsh-pet 卸载清理结果："]
    if error:
        lines.append(f"  清理执行失败：{error}")
    for step, value in results.items():
        lines.append(f"  {step} = {_describe_step(value)}")
    failed = [step for step, value in results.items() if value is False]
    if error:
        lines.append("  结论：清理异常，见上面错误")
    elif failed:
        lines.append("  结论：有步骤失败（" + "、".join(failed) + "）")
    else:
        lines.append("  结论：全部完成")
    return lines


def _write_result_record(config, lines: list[str], *, ok: bool) -> bool:
    """把本次结果追加进配置目录里的留痕文件；失败只返回 False，不打断清理。"""
    try:
        config.dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(config.dir / RESULT_LOG_NAME, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] pid={os.getpid()} exit={0 if ok else 1}\n")
            for line in lines:
                handle.write(f"{line}\n")
    except Exception:
        return False
    return True


def main(config=None) -> int:
    """``--uninstall-cleanup`` 入口：执行清理、输出可诊断结果、返回退出码。

    退出码语义与 ``pet/__main__.py`` 的既有分流一致：任一步骤明确失败（False）
    或清理本身异常即 1，成功与 skipped 为 0——安装器据此判断是否需要提示用户。
    """
    logger = logging.getLogger(__name__)
    if config is None:
        try:
            from .config import Config

            config = Config()
        except Exception as exc:  # 读不到配置也要给出结果与退出码，不能抛 traceback
            lines = _format_results({}, f"配置不可读：{type(exc).__name__}: {exc}")
            for line in lines:
                print(line, flush=True)
            logger.error("卸载清理无法读取配置：%s", exc)
            return 1

    try:
        results = run_uninstall_cleanup(config)
        error = ""
    except Exception as exc:  # 清理崩了也要有结果与退出码，不能只留 traceback
        results = {}
        error = f"{type(exc).__name__}: {exc}"

    failed = [step for step, value in results.items() if value is False]
    lines = _format_results(results, error)
    for line in lines:
        print(line, flush=True)
    if error:
        logger.error("卸载清理异常：%s", error)
    elif failed:
        logger.warning("卸载清理有步骤失败：%s", "、".join(failed))
    else:
        logger.info("卸载清理完成：%s", results)

    _write_result_record(config, lines, ok=not error and not failed)
    return 1 if (error or failed) else 0
