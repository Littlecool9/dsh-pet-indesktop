# -*- coding: utf-8 -*-
"""功能模块清单。

``MODULES`` 里的顺序只是登记顺序；启动顺序由依赖决定（见 ``registry.dependency_order``）。
**删除一个模块 = 删掉它的目录 + 去掉这里的一行**；依赖它的模块会显示成「缺少依赖模块」，
菜单项置灰并写明原因。

本包的 ``__init__`` 必须便宜（设置进程也会 import）：不 import Qt、不 import 模块运行时。
"""
from __future__ import annotations

MODULES: tuple[str, ...] = (
    "pet.modules.surfcore",
    "pet.modules.harness",
    "pet.modules.agent_link",
    "pet.modules.hotkeys",
    "pet.modules.self_talk",
    "pet.modules.network_info",
    "pet.modules.focus",
    "pet.modules.quick_launch",
    "pet.modules.todo",
    "pet.modules.balance",
)

__all__ = ["MODULES"]
