# -*- coding: utf-8 -*-
"""灵动岛 AppShell 接线测试：no-chat 变体守卫与余额刷新路径。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from pet.chat.service import ChatService
from pet.config import Config


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_shell(tmp_path: Path, **island_cfg) -> AppShell:
    """最小 AppShell 桩：__new__ 绕过完整初始化，只接灵动岛链路。"""
    cfg = Config(base=tmp_path)
    cfg.set("dynamic_island", {
        "enabled": True, "x": 400, "y": 300,
        **island_cfg,
    })
    shell = AppShell.__new__(AppShell)
    shell.config = cfg
    shell.island = None
    shell.instance = None
    shell._instances = []
    return shell


def _teardown_shell(shell) -> None:
    island = getattr(shell, "island", None)
    if island is not None:
        island.hide()
        island.deleteLater()
    ChatService.unregister_global_finished(shell._on_global_chat_finished)
    QApplication.processEvents()


def test_island_survives_no_chat_packaging_variant(tmp_path, monkeypatch):
    """P0-2 回归：pet.chat 被排除的打包变体里创建灵动岛不得抛异常。"""
    app = _qapp()
    monkeypatch.setitem(sys.modules, "pet.chat.service", None)  # 模拟变体排除
    shell = _make_shell(tmp_path)
    try:
        shell._sync_dynamic_island()  # 不应抛 ModuleNotFoundError
        assert shell.island is not None
        # 未注册全局订阅（无 chat 可订）
        assert shell._on_global_chat_finished not in ChatService._global_finished_listeners
    finally:
        _teardown_shell(shell)
        app.processEvents()


def test_quiet_balance_refresh_paths(tmp_path, monkeypatch):
    """卡片展开静默刷新：无 Key 明示 / 缓存命中直接用 / 后台查询只更新岛。"""
    import hashlib
    import time as _time
    from types import SimpleNamespace

    from pet.modules.balance.module import BalanceModule

    app = _qapp()
    shell = _make_shell(tmp_path)
    try:
        shell._sync_dynamic_island()
        island = shell.island
        module = BalanceModule()
        module.start(SimpleNamespace(config=shell.config, shell=shell))

        provider = SimpleNamespace(id="p", base_url="http://x", api_key="", verify_ssl=True)
        monkeypatch.setattr(shell.config, "chat_settings",
                            lambda: SimpleNamespace(active_config=provider))
        monkeypatch.setattr(shell.config, "resolve_api_key", lambda _p: "")

        # 1) 未配置 API Key → 明确提示，不再停留 "余额 --"
        island.expand_card()  # card_expanded → 模块挂接的静默刷新
        assert island._balance_text.startswith("未配置 API Key")

        # 2) 有 Key + 新鲜内存缓存 → 直接命中，不起后台查询
        provider.api_key = "sk-test"
        monkeypatch.setattr(shell.config, "resolve_api_key", lambda _p: "sk-test")
        digest = hashlib.sha256(b"sk-test").hexdigest()[:12]
        provider_key = "|".join(["p", "http://x", digest])
        module._balance_cache = (_time.monotonic(), {"text": "余额 ¥9.9", "info": {}}, provider_key)
        module.refresh_island()
        assert island._balance_text == "余额 ¥9.9"

        # 3) 无缓存 → 后台查询：结果回来只更新岛卡片（不冒泡/不播动画）
        island._finish_animations()  # 展开动画落定（动画表停），隔离基线
        assert not island._anim_timer.isActive()
        module._balance_cache = None
        module._quiet_balance_last = None

        def fake_worker(bridge, base_url, api_key, verify_ssl, provider_key='', **_kw):
            bridge.done.emit(True, {"text": "余额 ¥8.8", "info": {}})

        monkeypatch.setattr(module, "_balance_worker", fake_worker)
        module.refresh_island()
        for _ in range(50):
            QApplication.processEvents()
            _time.sleep(0.02)
            if island._balance_text == "余额 ¥8.8":
                break
        assert island._balance_text == "余额 ¥8.8"
        assert not island._anim_timer.isActive()  # 静默路径不播动画
    finally:
        module.stop()
        _teardown_shell(shell)
        app.processEvents()


def test_toggle_pet_from_island_routes_to_overlay_shell():
    """GPT 审查阻断：overlay 拓扑 instances[].win 恒为 None，岛单击显隐
    必须路由到 OverlayShell._toggle_pet_visible（否则岛永远调不动桌宠）。"""
    shell = AppShell.__new__(AppShell)
    calls: list = []

    class _OverlayShell:
        def _toggle_pet_visible(self):
            calls.append(1)

    shell._overlay_shell = _OverlayShell()
    shell._instances = []  # overlay 拓扑：win 全 None，旧路径必静默失效
    shell.island = None
    AppShell._toggle_pet_from_island(shell)
    assert calls == [1]


def test_aggregate_pet_visible_reads_overlay_window():
    """聚合可见态在 overlay 拓扑读唯一合成窗（不再恒 False）。"""
    import types

    shell = AppShell.__new__(AppShell)
    overlay = types.SimpleNamespace(
        overlay=types.SimpleNamespace(isVisible=lambda: True))
    shell._overlay_shell = overlay
    shell._instances = []
    assert AppShell._aggregate_pet_visible(shell) is True
    overlay.overlay = types.SimpleNamespace(isVisible=lambda: False)
    assert AppShell._aggregate_pet_visible(shell) is False


