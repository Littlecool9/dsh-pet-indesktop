# -*- coding: utf-8 -*-
"""模块注册表：读清单 → 按依赖排序 → 启动 / 下发配置 / 停止，失败隔离且原因可见。

它替换的是 ``AppShell`` 里那一串 ``_ensure_X_service`` / ``_sync_X_service`` / ``_X_wanted``：
每个模块自己在 ``apply_config`` 里决定开关，注册表只管生命周期顺序和异常隔离。

状态口径（与菜单「运行时不可用」语义一致）：

- ``running``：已启动。
- ``blocked``：硬依赖缺失 / 未启动成功，本模块没启动；``reason`` 写明缺哪个。
- ``failed``：创建或 ``start`` 抛异常；``reason`` 是异常摘要（详细栈进日志）。
- ``stopped``：``stop_all`` 之后。
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .base import ModuleHost, ModuleManifest, PetModule, load_entry

logger = logging.getLogger(__name__)

RUNNING = "running"
BLOCKED = "blocked"
FAILED = "failed"
STOPPED = "stopped"
PENDING = "pending"


@dataclass
class ModuleStatus:
    state: str = PENDING
    reason: str = ""


def read_manifest(package: str) -> ModuleManifest:
    """import 模块包并取 ``MANIFEST``；包名末段必须等于清单 id。"""
    mod = importlib.import_module(package)
    manifest = getattr(mod, "MANIFEST", None)
    if not isinstance(manifest, ModuleManifest):
        raise TypeError(f"{package} 没有定义 MANIFEST = ModuleManifest(...)")
    if package.rsplit(".", 1)[-1] != manifest.id:
        raise ValueError(f"{package} 的 MANIFEST.id={manifest.id!r} 必须等于包名")
    return manifest


def dependency_order(manifests: Iterable[ModuleManifest]) -> list[ModuleManifest]:
    """按 requires + optional 做稳定拓扑排序（同层保持登记顺序）；有环则报错。

    optional 也参与排序：软依赖在场时应先于本模块启动，本模块 start 时才能拿到它的服务。
    指向未登记模块的依赖不参与排序（启动时由 requires 判 blocked）。
    """
    items = list(manifests)
    by_id: dict[str, ModuleManifest] = {}
    for m in items:
        if m.id in by_id:
            raise ValueError(f"模块 id 重复登记：{m.id}")
        by_id[m.id] = m
    ordered: list[ModuleManifest] = []
    state: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(m: ModuleManifest, chain: tuple[str, ...]) -> None:
        mark = state.get(m.id)
        if mark == 1:
            return
        if mark == 0:
            raise ValueError("模块依赖成环：" + " -> ".join(chain + (m.id,)))
        state[m.id] = 0
        for dep in (*m.requires, *m.optional):
            if dep in by_id:
                visit(by_id[dep], chain + (m.id,))
        state[m.id] = 1
        ordered.append(m)

    for m in items:
        visit(m, ())
    return ordered


class ModuleRegistry:
    """进程内模块注册表（主进程一个）。"""

    def __init__(self, manifests: Iterable[ModuleManifest]) -> None:
        self._manifests = dependency_order(manifests)
        self._by_id = {m.id: m for m in self._manifests}
        self._instances: dict[str, PetModule] = {}
        self._status: dict[str, ModuleStatus] = {m.id: ModuleStatus() for m in self._manifests}
        self._started = False

    @classmethod
    def from_packages(cls, packages: Iterable[str]) -> "ModuleRegistry":
        return cls(read_manifest(p) for p in packages)

    # ---- 查询 ----------------------------------------------------------------
    @property
    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests)

    def manifest(self, module_id: str) -> ModuleManifest | None:
        return self._by_id.get(module_id)

    def status(self, module_id: str) -> ModuleStatus:
        return self._status.get(module_id, ModuleStatus(BLOCKED, f"未登记模块：{module_id}"))

    def running(self, module_id: str) -> bool:
        return self.status(module_id).state == RUNNING

    def get(self, module_id: str) -> PetModule | None:
        return self._instances.get(module_id) if self.running(module_id) else None

    def unavailable_reason(self, module_id: str) -> str:
        """菜单 / 设置页置灰时显示的原因；运行中返回空串。"""
        st = self.status(module_id)
        if st.state == RUNNING:
            return ""
        return st.reason or "模块未启动"

    # ---- 生命周期 ------------------------------------------------------------
    def start_all(self, host: ModuleHost, config: Any = None) -> None:
        if self._started:
            return
        self._started = True
        for m in self._manifests:
            missing = [dep for dep in m.requires if not self.running(dep)]
            if missing:
                names = "、".join(self._display(dep) for dep in missing)
                self._status[m.id] = ModuleStatus(BLOCKED, f"缺少依赖模块：{names}")
                logger.warning("模块 %s 未启动：缺少依赖 %s", m.id, missing)
                continue
            try:
                factory = load_entry(m.factory)
                instance = factory(m)
                instance.start(host)
            except Exception as exc:  # 一个模块坏掉不拖垮其它模块与主程序
                self._status[m.id] = ModuleStatus(FAILED, f"启动失败：{type(exc).__name__}: {exc}"[:200])
                logger.exception("模块 %s 启动失败", m.id)
                continue
            self._instances[m.id] = instance
            self._status[m.id] = ModuleStatus(RUNNING)
            if config is not None:
                self._apply_one(m.id, instance, config)

    def apply_config(self, config: Any) -> None:
        for m in self._manifests:
            instance = self.get(m.id)
            if instance is not None:
                self._apply_one(m.id, instance, config)

    def stop_all(self) -> None:
        for m in reversed(self._manifests):
            instance = self._instances.pop(m.id, None)
            if instance is None:
                continue
            try:
                instance.stop()
            except Exception:
                logger.exception("模块 %s 停止时出错", m.id)
            self._status[m.id] = ModuleStatus(STOPPED)

    # ---- 字符串入口（菜单 / 设置页）------------------------------------------
    def menu_action_specs(self) -> dict[str, Any]:
        """汇总各模块 ``menu_actions`` 入口给出的 ``{action_id: MenuActionSpec}``。

        与模块是否 running 无关：可用 / 置灰由 spec 自己的 available / enabled 判定
        （通常读 ``pet.modules.running(id)`` / ``unavailable_reason(id)``）。
        """
        specs: dict[str, Any] = {}
        for m in self._manifests:
            if not m.menu_actions:
                continue
            try:
                provided = load_entry(m.menu_actions)
                if callable(provided) and not isinstance(provided, Mapping):
                    provided = provided()
            except Exception:
                logger.exception("模块 %s 的菜单入口加载失败", m.id)
                continue
            for action_id, spec in dict(provided).items():
                if action_id in specs:
                    raise ValueError(f"菜单动作 id 冲突：{action_id}（模块 {m.id}）")
                specs[action_id] = spec
        return specs

    def settings_pages(self) -> list[tuple[str, str]]:
        return [(m.id, m.settings_page) for m in self._manifests if m.settings_page]

    # ---- 内部 ----------------------------------------------------------------
    def _display(self, module_id: str) -> str:
        m = self._by_id.get(module_id)
        return m.name if m is not None else module_id

    def _apply_one(self, module_id: str, instance: PetModule, config: Any) -> None:
        try:
            instance.apply_config(config)
        except Exception:
            logger.exception("模块 %s 应用配置失败", module_id)


__all__ = [
    "BLOCKED", "FAILED", "PENDING", "RUNNING", "STOPPED",
    "ModuleRegistry", "ModuleStatus", "dependency_order", "read_manifest",
]
