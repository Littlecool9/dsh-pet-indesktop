# -*- coding: utf-8 -*-
"""「Agent 联动」的卸载清理：移除 Claude hooks、卸载 DSH 桥接插件。

由 ``pet.uninstall_cleanup`` 经模块清单的 ``uninstall_cleanup`` 入口调用；
模块不在 ``MODULES`` 里时这段清理自然不发生（功能关闭）。
"""
from __future__ import annotations

import logging

from .agent_link import ClaudeCodeMonitor, DshMonitor

log = logging.getLogger("dsh-pet-standalone")


def run_cleanup(config) -> dict:
    """执行模块自己的卸载清理步骤，返回 {结果键: bool|"skipped"}。"""
    from ...uninstall_cleanup import other_instances_use_agent

    results: dict[str, bool | str] = {}
    for agent_key, result_key, uninstaller in (
        ("claude", "claude_hooks", ClaudeCodeMonitor.uninstall_hooks),
        ("dsh", "dsh_bridge", DshMonitor.uninstall_bridge),
    ):
        try:
            if other_instances_use_agent(config, agent_key):
                results[result_key] = "skipped"
            else:
                results[result_key] = bool(uninstaller())
        except Exception:
            log.exception("卸载清理 %s 失败", result_key)
            results[result_key] = False
    return results


__all__ = ["run_cleanup"]
