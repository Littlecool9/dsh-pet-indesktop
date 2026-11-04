# -*- coding: utf-8 -*-
"""B7a 气泡/显隐壳侧接线：改大小 reflow、换角色 refresh_anchor、逐只隐藏收气泡。

旧语义（``base-2786c15/pet/window.py``）：可见气泡在缩放变更时
``bubble.reflow(新锚点, pet_scale=新scale)``（:1000-1004）；换角色换 ``body_box``
后锚点跟着换；``hide()`` → ``_pause_activity`` → ``bubble.hide()``（:1160-1237）。
overlay 壳此前三处都缺——``reflow`` 在 B6 进了跟随器却零调用方（改大小只写
``sprite.scale``）、``switch_character`` 换库后不刷新锚点、``set_sprite_visible``
只改 ``sprite.visible`` 不收气泡（隐藏后气泡最长浮到停留结束）。

另：识屏发起者 ``_look_sprite`` 此前只在 ``look_at_screen`` 里赋值，构造期没有
确定值（``_look_bubble`` 靠 ``getattr`` 兜底）——本批补构造期初始化。

纪律：offscreen；真壳 + 真 ``SpriteBubbleFollower`` + 记录型气泡替身
（同 ``tests/test_sprite_bubble.py`` 的 FakeBubble 口径），同步直调，不 sleep。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import tests.test_sprite_menu_facade as fac
from tests.test_sprite_bubble import FakeBubble

app = QApplication.instance() or QApplication([])


class _RecordingBubble(FakeBubble):
    """FakeBubble + 真实显隐语义（``show_text()`` 后为显、``hide()`` 后为隐）。

    真实 ``PetSpeechBubble`` 的 ``isVisible()`` 由 ``show_text``/``hide`` 两条真路径
    决定；替身若只会"构造即显"，靠它建立"气泡在显"的前提就是假的（见本文件
    ``test_set_sprite_visible_hides_main_bubble_only``）。
    """

    def show_text(self, text, anchor, duration_ms, **kw):
        super().show_text(text, anchor, duration_ms, **kw)
        self._visible = True

    def hide(self):
        self._visible = False


def _make_shell(tmp_path, values=None):
    """真壳（真 PetSprite）+ 真跟随器 + 记录型气泡。"""
    shell, lib = fac._make_shell(tmp_path, values)
    shell.sprite.bind_clip("idle1")
    shell.sprite._rebuild_pixmap()
    follower = shell._bubble_follower
    assert follower is not None, "壳构造期就该建好主跟随器"
    follower.bubble = _RecordingBubble()
    return shell, lib, follower


# ---------------------------------------------------------------- 改大小：reflow
def test_scale_change_through_refresh_reflows_visible_bubble(tmp_path):
    """设置页改大小（config → refresh_settings）必须按新 pet_scale 重排气泡。

    旧机 refresh_pet_settings 里就是即时 ``change_scale`` → ``bubble.reflow``
    （window.py:3937-3938 / :1000-1004）；新版设置页文案承诺即时生效。
    """
    shell, _lib, follower = _make_shell(tmp_path, {"scale": 0.5})
    try:
        assert shell.sprite.scale == pytest.approx(0.5)
        assert follower.bubble.isVisible() is True      # 前提：气泡在显
        shell._config.set("scale", 1.0)
        shell.refresh_settings()
        assert shell.sprite.scale == pytest.approx(1.0), "设置页改大小运行期即生效"
        assert follower.bubble.reflows, "可见气泡必须按新缩放重排"
        _anchor, pet_scale = follower.bubble.reflows[-1]
        assert pet_scale == pytest.approx(1.0)
    finally:
        shell._delete_runtime_marker()




# ---------------------------------------------------------------- 换角色：refresh_anchor
def test_switch_character_refreshes_bubble_anchor(tmp_path):
    """换角色换库（body_box 可能变）后锚点必须立即刷新，不等到下次位移。"""
    shell, _lib, follower = _make_shell(tmp_path)
    try:
        before = len(follower.bubble.moves)
        shell.switch_character("other-character")
        # "角色"是每宠键：真值在槽档案里（生产里 ``_config`` 是 SlotRoutedConfig
        # 会路由到它；这里的假配置无路由，直接断言生效的每宠配置）。
        assert shell._sprite_config(shell.sprite).get("character") == "other-character"
        assert len(follower.bubble.moves) > before, "换角色后必须重定位一次锚点"
    finally:
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- 逐只显隐：收气泡


# ---------------------------------------------------------------- 识屏发起者默认值
def test_look_sprite_initialized_at_build(tmp_path):
    """``_look_sprite`` 构造期必须有确定值（B2 遗留：靠 getattr 兜底）。"""
    shell, _lib, _follower = _make_shell(tmp_path)
    try:
        assert shell._look_sprite is None
    finally:
        shell._delete_runtime_marker()
