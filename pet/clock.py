"""可补丁的单调时钟 seam。

``time.monotonic`` 是测试可 monkeypatch 的时钟命名空间（只换属性，不换对象）：
``monkeypatch.setattr("pet.clock.time.monotonic", fake)``。读它的 helper 模块
（window_alerts / window_placement / movement）一律 ``from .clock import time``
后按属性读 ``time.monotonic()``，补丁对所有读者同时生效，又不会改到标准库的
``time.monotonic``（Qt / 线程计时不受影响）。

历史：这个命名空间原先挂在 ``pet.window.time``（legacy PetWindow 模块）上，
阶段 1b-2 删 window.py 时搬到这里。
"""

from __future__ import annotations

import time as _stdlib_time
from types import SimpleNamespace

time = SimpleNamespace(monotonic=_stdlib_time.monotonic)
