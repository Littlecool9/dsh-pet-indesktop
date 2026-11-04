# -*- coding: utf-8 -*-
"""模块契约：清单（ModuleManifest）、运行时（PetModule）与宿主（ModuleHost）。

一个功能模块 = ``pet/modules/<id>/`` 一个包：

- ``pet/modules/<id>/__init__.py`` 只定义 ``MANIFEST = ModuleManifest(...)``——**必须便宜**：
  不 import Qt、不 import 运行时代码。设置进程（``python -m pet --settings``）只读清单和
  ``settings_page`` 指向的页面代码，从不启动模块运行时。
- 运行时代码放在 ``factory`` 指向的子模块里（字符串入口 ``"pkg.mod:attr"``），由主进程的
  :class:`pet.modules.registry.ModuleRegistry` 惰性 import。

模块之间不准直接 import（架构测试守着）：要用别的模块的能力，走宿主的服务表
（``host.provide("surfcore", client)`` / ``host.get("surfcore")``）或事件总线
（``host.emit(topic, payload)`` / ``host.subscribe(topic, callback)``）。
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModuleManifest:
    """模块清单（不可变，import 期就能读）。

    - ``id``：稳定 id，等于包名（``pet/modules/<id>/``）。
    - ``requires``：硬依赖的模块 id——缺了（未登记 / 未启动成功）本模块就不启动，并记录原因。
    - ``optional``：软依赖——缺了照常启动，由模块自己降级（启动前已在的才算）。
    - ``config_keys``：本模块拥有的配置键（键名不变；只是归属记在模块上）。
    - ``factory``：``"pkg.mod:attr"``，调用 ``attr(manifest)`` 得到 :class:`PetModule` 实例。
    - ``settings_page`` / ``menu_actions``：字符串入口，按需 import（见 :func:`load_entry`）。
    """

    id: str
    name: str
    factory: str
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    config_keys: tuple[str, ...] = ()
    settings_page: str | None = None
    menu_actions: str | None = None
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").isalnum() or self.id != self.id.lower():
            raise ValueError(f"模块 id 只能是小写字母/数字/下划线：{self.id!r}")
        if not self.name:
            raise ValueError(f"模块 {self.id} 缺少显示名 name")
        for entry in (self.factory, self.settings_page, self.menu_actions):
            if entry is not None and ":" not in entry:
                raise ValueError(f"模块 {self.id} 的入口必须写成 'pkg.mod:attr'：{entry!r}")
        if self.id in self.requires or self.id in self.optional:
            raise ValueError(f"模块 {self.id} 不能依赖自己")


@runtime_checkable
class PetModule(Protocol):
    """模块运行时。``stop`` 必须收干净：定时器、线程、气泡、子进程。"""

    def start(self, host: "ModuleHost") -> None: ...

    def apply_config(self, config: Any) -> None: ...

    def stop(self) -> None: ...


class ModuleHost(Protocol):
    """模块能碰到的唯一入口（应用侧实现见 ``pet.module_host``）。

    这里只声明模块框架自身要求的能力；配置、气泡、灵动岛等应用能力由具体宿主类提供，
    随模块迁移按需增加（模块只依赖它真的用到的那几个方法）。
    """

    def provide(self, name: str, service: Any) -> None: ...

    def get(self, name: str, default: Any = None) -> Any: ...

    def emit(self, topic: str, payload: Any = None) -> None: ...

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> Callable[[], None]: ...


def load_entry(entry: str) -> Any:
    """解析 ``"pkg.mod:attr"`` 字符串入口（惰性 import）。"""
    module_name, _, attr = entry.partition(":")
    if not module_name or not attr:
        raise ValueError(f"入口必须写成 'pkg.mod:attr'：{entry!r}")
    target: Any = importlib.import_module(module_name)
    for part in attr.split("."):
        target = getattr(target, part)
    return target


__all__ = ["ModuleHost", "ModuleManifest", "PetModule", "load_entry"]
