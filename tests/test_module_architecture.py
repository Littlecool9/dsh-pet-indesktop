# -*- coding: utf-8 -*-
"""模块边界（spec §2.2 / 阶段 2 第 1 条）：

1. 模块之间不准直接 import：``pet/modules/<a>/`` 只能 import 自己、``pet.modules`` 的框架
   （base / registry / host）和核心；要用别的模块，走宿主的服务表 / 事件总线。
2. 核心不准 import 模块：``pet/`` 下 ``pet/modules/`` 以外的代码只能碰框架
   （``pet.modules`` / ``pet.modules.base`` / ``.registry`` / ``.host``），不能 import
   ``pet.modules.<id>``——否则「删一个模块 = 删目录 + 去掉一行」就不成立。
3. 模块包的 ``__init__`` 必须便宜：不 import PySide6（设置进程只读清单）。
"""
from __future__ import annotations

import ast
from pathlib import Path

PET = Path(__file__).resolve().parents[1] / "pet"
MODULES_DIR = PET / "modules"
FRAMEWORK = {"base", "registry", "host"}


def _imports(path: Path) -> list[str]:
    """绝对化后的 import 目标（相对 import 按文件位置解析）。"""
    rel = path.relative_to(PET.parent).with_suffix("")
    # 普通模块 pet/a/b.py 与包 pet/a/__init__.py 的"所在包"都是 pet.a。
    package_parts = list(rel.parts[:-1])
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)] if node.level > 1 else package_parts
                prefix = ".".join(base)
                target = f"{prefix}.{node.module}" if node.module else prefix
            else:
                target = node.module or ""
            out.append(target)
            # ``from pet.modules import network_info`` 这种形式：把导入的名字也算成子模块
            for alias in node.names:
                out.append(f"{target}.{alias.name}")
    return out


def _module_of(target: str) -> str | None:
    """``pet.modules.<id>...`` → ``<id>``（框架子模块返回 None）。"""
    parts = target.split(".")
    if len(parts) >= 3 and parts[0] == "pet" and parts[1] == "modules":
        return None if parts[2] in FRAMEWORK or parts[2] == "MODULES" else parts[2]
    return None


def _module_packages() -> list[Path]:
    return [p for p in MODULES_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()]


def test_modules_do_not_import_each_other():
    bad = []
    for pkg in _module_packages():
        for path in pkg.rglob("*.py"):
            for target in _imports(path):
                other = _module_of(target)
                if other is not None and other != pkg.name:
                    bad.append(f"{path.relative_to(PET.parent)} -> {target}")
    assert not bad, "模块之间不准直接 import（走宿主服务表 / 事件总线）：\n" + "\n".join(bad)


def test_core_does_not_import_modules():
    bad = []
    for path in PET.rglob("*.py"):
        if MODULES_DIR in path.parents:
            continue
        for target in _imports(path):
            if _module_of(target) is not None:
                bad.append(f"{path.relative_to(PET.parent)} -> {target}")
    assert not bad, "核心不准 import 具体模块（只能用 pet.modules 框架）：\n" + "\n".join(bad)


def test_module_manifest_packages_stay_cheap():
    bad = []
    for pkg in _module_packages():
        for target in _imports(pkg / "__init__.py"):
            if target.startswith("PySide6") or target.startswith("shiboken6"):
                bad.append(f"{pkg.name}/__init__.py -> {target}")
    assert not bad, "模块包 __init__ 只放清单，不能 import Qt：\n" + "\n".join(bad)


def test_every_module_package_is_registered_and_vice_versa():
    from pet.modules import MODULES

    on_disk = {f"pet.modules.{p.name}" for p in _module_packages()}
    assert on_disk == set(MODULES), (
        "pet/modules/ 下的包与 pet.modules.MODULES 必须一一对应："
        f"未登记 {sorted(on_disk - set(MODULES))}，登记了但不存在 {sorted(set(MODULES) - on_disk)}"
    )


def test_import_resolver_sees_relative_and_from_imports(tmp_path):
    """守住解析器本身：相对 import 与 ``from pet.modules import x`` 都要算进去。"""
    sample = MODULES_DIR / "registry.py"
    targets = _imports(sample)
    assert "pet.modules.base" in targets
    assert _module_of("pet.modules.focus.runtime") == "focus"
    assert _module_of("pet.modules.registry") is None
    assert _module_of("pet.config") is None
