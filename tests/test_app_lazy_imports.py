# -*- coding: utf-8 -*-
"""内存瘦身第二刀的机器化守卫：``pet.app`` 的导入图不拖进按配置关闭的功能模块。

实测依据（tools/import_cost.py，每个模块一个全新子进程的 tracemalloc 增量）：

    MB      module
  4.75  pet.modules.balance.balance（档位文案/价格提示表；默认配置从不查余额）

这个 import 已收到真正的构造/使用点（``_show_balance_payload`` /
``_island_tier_hint`` / ``_balance_worker``），本测试用**子进程**验证「只
import pet.app 不会带出它」——进程内断言不可靠，别的用例可能已经导入过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_CHILD = r'''
import json, sys
import pet.app  # noqa: F401 - 被测：只导入入口模块，不起 QApplication
deferred = ["pet.modules.balance", "pet.balance_pricing"]
print(json.dumps({name: name in sys.modules for name in deferred}))
'''


def _run_child() -> dict:
    env = dict(os.environ)
    env.setdefault('QT_QPA_PLATFORM', 'offscreen')
    proc = subprocess.run(
        [sys.executable, '-c', _CHILD],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f'子进程导入 pet.app 失败:\n{proc.stderr[-3000:]}'
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_importing_app_defers_balance_module():
    loaded = _run_child()
    assert loaded['pet.modules.balance'] is False, (
        '余额模块（4.75MB 档位文案表）不得在 import pet.app 时常驻：'
        '默认配置不查余额，它必须留到模块按需启动'
    )
    assert loaded['pet.balance_pricing'] is False, (
        '峰谷计价纯函数也不得在 import pet.app 时常驻（灵动岛/模块用到才导入）'
    )
