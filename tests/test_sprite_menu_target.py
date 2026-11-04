# -*- coding: utf-8 -*-
"""右键菜单作用对象 = 被点的那一只（批 B2）。

旧版一窗一宠，菜单以 ``pet=self`` 建造，条目天然作用在本窗那一只。overlay 单窗
多宠后 facade 的写操作却硬编码 ``shell.sprite``（主宠），读勾选态/素材清单却用
被点 sprite → 右击子肥鱼改的是主肥鱼、菜单勾选态还停在子宠的旧档。

本文件锁六处缺口（审计 raw.txt F1/F2/F3/A/G）：

1. ``switch_clip`` / ``trigger_move`` / ``set_playback_speed`` / ``change_scale`` /
   ``change_scale`` / ``set_playback_speed`` / ``go_default_corner`` 作用于被点 sprite，素材清单读它的库；
   子宠设置写它自己的 ``config-slot-N.json``（B7b；主配置一字不动）；
2. ``hide`` 只隐藏被点的那只（主宠 = 宿主窗，维持整窗隐藏语义）；
3. ``look_at_screen(sprite=...)`` 记住发起者；
4. ``DeepSeek 余额`` 的父窗传**发起的那一只**的代次呈现器（手动结果归发起者），


装配：真 ``OverlayShell`` + 真 ``PetSprite`` + 真 ``Config``；子宠走真
``shell.spawn_pet()``；余额复用 ``pet.app`` 的真实展示实现（只桩网络边界）。
纪律：offscreen；同步直调 + 事件同步轮询（不赌固定 sleep）。
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pet.app as app_mod
import tests.test_overlay_window_capabilities as cap
import tests.test_sprite_menu_facade as fac
import tests.test_sprite_menu_parity as parity
from pet.config import Config
from pet.overlay_shell import OverlayShell
from pet.pet_sprite import PetSprite
from pet.sprite_menu_facade import SpriteMenuFacade, build_sprite_full_menu

app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 装配
class _MiniAppShell:
    """最小真实 AppShell 面：余额复用 ``pet.app`` 的真实展示实现。"""

    def __init__(self, instance=None) -> None:
        self.instance = instance

    def show_balance(self, parent=None) -> None:
        app_mod._show_balance_payload(
            parent, {"text": "余额 12.34", "info": {"total": 12.34}})


class _TargetInstance(parity._StubInstance):
    """PetInstance 面：子宠库带可辨识动作池（判定菜单读的是哪只的库）。"""

    def __init__(self, config, *, chat=True, app_shell=None) -> None:
        super().__init__(config, chat=chat)
        if app_shell is not None:
            self.shell = app_shell
        self.library_calls = 0

    def _create_library(self, character_id):
        self.library_calls += 1
        lib = fac.RichLibrary()
        if self.library_calls > 1:          # 第 2 次起 = 子宠库
            lib.acts = ["child_act"]
            lib._clips["child_act"] = fac.FakeClip("child_act", 24)
        return lib


def _make_shell(tmp_path, *, chat=True, values=None, app_shell=None):
    config = Config(base=tmp_path)
    for key, value in (values or {}).items():
        config.set(key, value)
    instance = _TargetInstance(config, chat=chat, app_shell=app_shell)
    screen = cap.FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    shell = OverlayShell(
        app, instance, screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    return shell, instance, config


def _spawn_child(shell):
    """真壳 spawn 出一只子宠（前置不成立就直接红，不放行）。"""
    shell.spawn_pet()
    assert shell._spawned, "spawn_pet 未产出子宠（用例前置不成立）"
    return shell._spawned[0]


def _find_deep(container, label: str):
    """递归找条目（modern 模板把条目录在分组子菜单里）。"""
    for action in container.actions():
        if action.isSeparator():
            continue
        if action.text() == label:
            return action
        submenu = action.menu()
        if submenu is not None:
            found = _find_deep(submenu, label)
            if found is not None:
                return found
    return None


def _require(container, label: str):
    action = _find_deep(container, label)
    assert action is not None, f"菜单缺项 {label}"
    return action


def _wait_until(predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


# ---------------------------------------------------------------- F1 六类条目
def test_child_menu_acts_on_clicked_sprite_not_main(tmp_path):
    """右击子肥鱼：六类写操作 + 素材清单都落到子宠，主宠一字不动。"""
    shell, _instance, config = _make_shell(tmp_path)
    try:
        main = shell.sprite
        child = _spawn_child(shell)
        assert child is not main
        facade = SpriteMenuFacade(shell, child)
        menu = build_sprite_full_menu(shell, child)

        # 素材清单读被点 sprite 的库（子宠库带 child_act 标记）
        assert facade._cats()["acts"] == ["child_act"]
        assert facade.acts == ["child_act"]

        # 播放动画（随机动作 / 待机族）：子宠绑 clip，主宠不变
        main_clip = main._clip_name
        facade.switch_clip("child_act")
        assert child._clip_name == "child_act"
        assert child.library._clips["child_act"].started is True
        assert main._clip_name == main_clip

        # 移动素材
        assert facade.trigger_move("walk") is True
        assert child._clip_name == "walk"
        assert main._clip_name == main_clip

        # 播放速率（菜单「播放速率」→ 1.5x）
        main_speed = main.playback_speed
        child_speed = child.playback_speed
        speed_menu = _require(menu, "播放速率").menu()
        next(a for a in speed_menu.actions() if a.text() == "1.5x").trigger()
        assert child.playback_speed == 1.5
        assert child.playback_speed != child_speed
        assert main.playback_speed == main_speed
        assert config.get("playback_speed") != child.playback_speed, "子宠设置不得写主配置"

        # 大小（菜单「大小」→ 320px = SCALE_STEPS[0]）
        main_scale = main.scale
        config_scale = config.get("scale")
        size_menu = _require(menu, "大小").menu()
        next(a for a in size_menu.actions() if a.text() == "320px").trigger()
        assert child.scale == 0.5
        assert main.scale == main_scale
        assert config.get("scale") == config_scale, "子宠设置不得写主配置"

        # 回到右下角
        main_pos = main.pos
        _require(menu, "回到右下角").trigger()
        assert child.pos == shell._default_corner_pos(shell._bounds, child.rect())
        assert main.pos == main_pos
    finally:
        shell.clear_spawned_pets()
        shell._delete_runtime_marker()


def test_child_menu_settings_keep_master_config_clean(tmp_path):
    """子宠设置写**它自己**的 slot 配置，主配置一个键都不许被写脏（B7b）。

    原断言只锁"主配置不变"（那时子宠 per-slot 持久化未接、只改运行态）；现在同一
    条用例再补一条"写到了该子宠自己的 config-slot-N.json"，确认它落盘而不是丢。
    """
    import json

    shell, _instance, config = _make_shell(tmp_path)
    try:
        child = _spawn_child(shell)
        facade = SpriteMenuFacade(shell, child)
        before = {key: config.get(key) for key in
                  ("scale", "playback_speed")}
        facade.change_scale(0.5)
        facade.set_playback_speed(1.6)
        after = {key: config.get(key) for key in before}
        assert after == before
        assert child.scale == 0.5 and child.playback_speed == 1.6
        slot = json.loads((config.dir / "config-slot-1.json").read_text(
            encoding="utf-8"))
        assert slot["scale"] == 0.5
        assert slot["playback_speed"] == 1.6
    finally:
        shell.clear_spawned_pets()
        shell._delete_runtime_marker()


def test_main_menu_still_persists_to_master_config(tmp_path):
    """主宠菜单（回归守）：逐只设置落 **slot0 档案**，全局那份不被回写。

    契约随规范 §五更新：``scale`` / ``playback_speed`` 都是每宠键，真值在
    ``config-slot-0.json``（与子宠那条用例同构）；主配置里那份旧值不参与，
    也不许被当成"第二真值"改写。
    """
    shell, _instance, config = _make_shell(tmp_path)
    try:
        import json

        facade = SpriteMenuFacade(shell)
        assert facade.sprite is shell.sprite
        before = {key: config.get(key) for key in
                  ("scale", "playback_speed")}
        facade.change_scale(0.5)
        facade.set_playback_speed(1.6)
        assert shell.sprite.scale == 0.5
        slot = json.loads((config.dir / "config-slot-0.json").read_text(
            encoding="utf-8"))
        assert slot["scale"] == 0.5
        assert slot["playback_speed"] == 1.6
        assert {key: config.get(key) for key in before} == before
    finally:
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- F3 隐藏桌宠
def test_hide_child_keeps_window_and_other_pets(tmp_path):
    """右击子肥鱼「隐藏桌宠」只藏这一只（窗口与主宠照旧）。"""
    shell, _instance, _config = _make_shell(tmp_path)
    try:
        child = _spawn_child(shell)
        shell.overlay.show()
        app.processEvents()
        assert shell.overlay.isVisible()
        facade = SpriteMenuFacade(shell, child)
        facade.hide()
        assert child.visible is False
        assert shell.sprite.visible is True
        assert shell.overlay.isVisible(), "隐藏子宠不得隐藏整窗（其它宠还在）"
    finally:
        shell.clear_spawned_pets()
        shell._delete_runtime_marker()


def test_hide_main_keeps_whole_window_semantics(tmp_path):
    """主宠 = 宿主窗：维持整窗隐藏语义（托盘顶层「显示 / 隐藏」可恢复）。

    主宠逐只隐藏会留下空的可交互合成窗，且无子宠时托盘没有逐只菜单可恢复，
    故主宠保持 ``set_pet_visible(False)``。
    """
    shell, _instance, _config = _make_shell(tmp_path)
    try:
        shell.overlay.show()
        app.processEvents()
        SpriteMenuFacade(shell).hide()
        assert not shell.overlay.isVisible()
    finally:
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- G 看看屏幕
def test_look_screen_remembers_clicked_sprite(tmp_path, monkeypatch):
    """「看看屏幕」记住发起者；答复气泡落**发起者自己**那只（B7b 起子宠有气泡）。"""
    shell, _instance, _config = _make_shell(tmp_path)
    started: list = []

    class _Thread:
        def __init__(self, *args, **kwargs):
            started.append(kwargs.get("target"))

        def start(self):
            pass

    try:
        child = _spawn_child(shell)
        child_bubble = shell._bubble_followers[child].bubble
        assert child_bubble is not None, "子宠必须有自己的气泡控件"
        monkeypatch.setattr("pet.overlay_shell.threading.Thread", _Thread)
        menu = build_sprite_full_menu(shell, child)
        _require(menu, "看看屏幕").trigger()
        assert started, "worker 线程必须被启动"
        assert shell._look_sprite is child, "发起者必须被记住"
        assert child_bubble._raw_text == "让我看看…"
        # worker 回报：答复仍给发起者（子宠自己的气泡，不再回主宠头顶）
        shell._on_look_done("我看到了浏览器", "[看看屏幕] 前台窗口：chrome", False)
        assert shell._look_busy is False
        assert "我看到了浏览器" in child_bubble._raw_text
        assert getattr(shell._speech_bubble, "_raw_text", "") != "我看到了浏览器"
        # 第二条证据：不走菜单、直接走 facade 接缝也必须绑被点 sprite
        # （busy/冷却期提前返回，仍会先记发起者）
        shell._look_sprite = None
        SpriteMenuFacade(shell, child).on_look_screen()
        assert shell._look_sprite is child
        # 无参调用 = 主宠（兼容既有调用面）
        shell.look_at_screen()
        assert shell._look_sprite is shell.sprite
    finally:
        shell.clear_spawned_pets()
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- A 余额
def test_balance_targets_the_initiating_pet(
        tmp_path, monkeypatch):
    """余额落**发起的那一只**（真 ``overlay.show()`` + 子宠定位）。

    A10/F04 契约（2026-10-10 终审）：手动服务结果归**发起 sprite**——右击子肥鱼查余额，
    气泡必须冒在子肥鱼头上；子宠没有联动动作链，余额档位动画**不许**改播到主肥鱼身上。
    旧用例钉的"余额也必须落壳"是错的合同：其理由（"OverlayWindow 没有 show_bubble"）
    早在 A10 就让位给代次呈现器了。

    """
    mini = _MiniAppShell()

    shell, instance, _config = _make_shell(tmp_path, app_shell=mini)
    mini.instance = instance
    # 壳级气泡面 + 主宠联动动画入口：两者都不该被子宠发起的余额使用。
    bubbles: list = []
    monkeypatch.setattr(
        shell, "show_bubble",
        lambda text, duration_ms=3200, **kw: bubbles.append(text) or True)
    link_anims: list = []
    monkeypatch.setattr(shell, "request_link_anim", lambda name: link_anims.append(name))
    try:
        child = _spawn_child(shell)
        shell.overlay.show()
        app.processEvents()
        menu = build_sprite_full_menu(shell, child)

        _require(menu, "DeepSeek 余额").trigger()

        # 真实呈现面：余额进**子宠自己那只气泡**（真 PetSpeechBubble 的 _raw_text）
        child_bubble = shell._bubble_followers[child].bubble
        assert child_bubble is not None, "前提：子宠有自己的气泡跟随器"
        assert "余额 12.34" in str(child_bubble._raw_text), \
            "余额必须冒在发起的那一只头上（旧合同让它落壳 = 冒在主肥鱼头上）"
        main_bubble = shell._bubble_follower.bubble
        assert main_bubble is not None and "余额 12.34" not in str(main_bubble._raw_text), \
            "主宠气泡不许被子宠发起的余额占用"
        assert bubbles == [], "余额不该再走壳的气泡面"
        assert link_anims == [], \
            "子宠没有联动动画链：余额档位动画不许改播到主肥鱼（不播好过错播）"

    finally:
        shell.clear_spawned_pets()
        shell._delete_runtime_marker()
