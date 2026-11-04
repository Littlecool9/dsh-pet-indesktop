# -*- coding: utf-8 -*-
"""模块化产物的打包契约（不运行 PyInstaller）。

模块是通过字符串入口惰性加载的：``pet/modules/__init__.py`` 的 ``MODULES``，
以及每个 ``MANIFEST`` 的 ``factory`` / ``menu_actions`` / ``config_schema`` /
``settings_page``。PyInstaller 从入口文件出发的静态分析看不到其中任何一条，
所以构建脚本必须显式 ``--collect-submodules pet.modules``，把每个模块包及其
子模块都拉进模块图。

这里只做静态检查 + 真的按字符串 import：
1. onedir 构建脚本的 PyInstaller 命令带 ``--collect-submodules pet.modules``；
2. 所有登记模块与磁盘上的模块包都在这个包下（一行收集覆盖全部）；
3. 每个登记模块的每条字符串入口都能 ``load_entry`` 解析。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pet.modules import MODULES
from pet.modules.base import load_entry
from pet.modules.registry import read_manifest

REPO = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO / "pet" / "modules"
BUILD_SCRIPT = REPO / "scripts" / "build_onedir.ps1"
COLLECT_FLAG = "--collect-submodules pet.modules"
ENTRY_ATTRS = ("factory", "menu_actions", "config_schema", "settings_page")


def _pyinstaller_command() -> str:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = text.index("python -m PyInstaller")
    end = text.index("$entry\n", start)
    return text[start:end]


def _module_packages() -> list[str]:
    return sorted(
        f"pet.modules.{path.name}"
        for path in MODULES_DIR.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )


def test_onedir_build_collects_the_whole_pet_modules_package():
    command = _pyinstaller_command()

    assert COLLECT_FLAG in command, (
        "PyInstaller 命令缺少 --collect-submodules pet.modules：模块由字符串入口加载，"
        "静态分析看不到，漏掉会让冻结包里的模块全部消失"
    )


def test_every_module_package_is_covered_by_that_one_collect_flag():
    packages = set(_module_packages())

    assert packages == set(MODULES), (
        "MODULES 与磁盘上的模块包必须一一对应："
        f"未登记 {sorted(packages - set(MODULES))}，登记了但不存在 {sorted(set(MODULES) - packages)}"
    )
    assert all(package == "pet.modules" or package.startswith("pet.modules.")
               for package in packages)


@pytest.mark.parametrize("package", MODULES)
def test_every_manifest_string_entry_point_is_importable(package: str):
    manifest = read_manifest(package)

    for attr in ENTRY_ATTRS:
        entry = getattr(manifest, attr)
        if entry is None:
            continue
        module_name = entry.partition(":")[0]
        assert module_name == package or module_name.startswith(package + "."), (
            f"{package}.{attr}={entry!r} 指向模块包之外；"
            f"{COLLECT_FLAG} 收集不到它，必须另行加入构建脚本"
        )
        assert load_entry(entry) is not None, f"{package}.{attr} 解析失败：{entry}"
