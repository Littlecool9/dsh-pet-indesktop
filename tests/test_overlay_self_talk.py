# -*- coding: utf-8 -*-
"""overlay 拓扑「自言自语」集成回归：模块调度 + 壳气泡呈现 + 配图缓存。

调度/选择已迁到 ``pet.modules.self_talk``；本文件用真实 OverlayShell + 真实
模块运行时验证两者接线（周期、显隐对称、配置热改、配图分支仍走既有气泡面）。
SurfCore 每小时一条的降级矩阵在 ``tests/test_self_talk_module.py`` 用假服务测。
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

import pet.overlay_shell as overlay_shell_mod
import tests.test_overlay_window_capabilities as cap
import tests.test_sprite_menu_facade as fac
from pet.modules.host import ModuleHostBase
from pet.modules.self_talk.module import SelfTalkModule
from pet.overlay_shell import OverlayShell
from pet.pet_sprite import PetSprite

app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 脚手架
class TalkConfig(cap.CapConfig):
    """自言自语最小配置面。"""


def _talk_values(**over):
    """自言自语最小确定性配置：间隔钉死 5s、时长 1s（after_display 可算准）。"""
    values = {
        "self_talk_enabled": True,
        "self_talk_texts": ["自言自语台词"],
        "self_talk_duration_seconds": 1.0,
        "self_talk_min_interval": 5.0,
        "self_talk_max_interval": 5.0,
        "self_talk_image_chance": 0,
    }
    values.update(over)
    return values


def _make_shell(tmp_path, values=None):
    """真实 PetSprite + RichLibrary 的壳（点击链路需要 click 素材池）。"""
    config = TalkConfig(tmp_path, values)
    instance = cap.CapInstance(config)
    screen = cap.FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    shell = OverlayShell(
        app, instance, screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    lib = fac.RichLibrary()
    shell.lib = lib
    shell.sprite.library = lib
    shell.overlay.click_feedback = None
    return shell, config


class ShellTalkHost(ModuleHostBase):
    """把模块接到真实壳（宿主能力与 AppModuleHost 同形）。"""

    def __init__(self, shell, config) -> None:
        super().__init__()
        self.shell = shell
        self.config = config
        self.module: SelfTalkModule | None = None

    def pet_config(self):
        return self.config

    def self_talk_ready(self) -> bool:
        return self.shell.self_talk_ready()

    def prepare_self_talk(self, *, images, image_scale) -> None:
        self.shell.prepare_self_talk(images=images, image_scale=image_scale)

    def show_self_talk(self, *, text=None, image=None, duration_ms=3200,
                       image_scale=None) -> bool:
        return self.shell.show_self_talk(
            text=text, image=image, duration_ms=duration_ms, image_scale=image_scale)

    def set_self_talk_visible(self, visible: bool) -> None:
        if self.module is not None:
            self.module.set_visible(visible)

    def apply_module_config(self) -> None:
        if self.module is not None:
            self.module.apply_config(self.config)


def _make_talk(tmp_path, values=None):
    shell, config = _make_shell(tmp_path, values)
    host = ShellTalkHost(shell, config)
    module = SelfTalkModule()
    host.module = module
    shell._instance.shell = SimpleNamespace(
        _module_host=host, _apply_module_config=host.apply_module_config)
    module.start(host)
    shell.overlay.show()
    module.apply_config(config)
    return shell, config, module, host


def _cleanup(shell, module=None) -> None:
    if module is not None:
        module.stop()
    shell._delete_runtime_marker()


# ---------------------------------------------------------------- 1. 周期气泡
def test_periodic_timer_timeout_shows_bubble_and_reschedules(tmp_path):
    """周期定时器到点 → 气泡出文本；显示后按 after_display 重排（+时长）。"""
    shell, _config, module, _host = _make_talk(tmp_path, _talk_values())
    try:
        assert module.timer.isActive() is True
        assert module.timer.interval() == 5000

        module.handle_timeout()

        assert shell._speech_bubble is not None
        assert shell._speech_bubble._raw_text == "自言自语台词"
        assert module.last_text == "自言自语台词"
        # 已展示 → 下一次排在 max(1000, (5 + 1) * 1000)
        assert module.timer.interval() == 6000
    finally:
        _cleanup(shell, module)


def test_self_talk_disabled_does_not_arm_timer(tmp_path):
    """总开关关闭时不排程（周期气泡是独立开关，不能只看文本池非空）。"""
    shell, _config, module, _host = _make_talk(
        tmp_path, _talk_values(self_talk_enabled=False))
    try:
        assert module.timer.isActive() is False
    finally:
        _cleanup(shell, module)


# ---------------------------------------------------------------- 2. 显隐对称
def test_hide_stops_timer_and_show_reschedules(tmp_path):
    """隐藏期 timer 停（防止对不可见壳冒泡）；恢复显示重排。"""
    shell, _config, module, _host = _make_talk(tmp_path, _talk_values())
    try:
        assert module.timer.isActive() is True

        shell.set_pet_visible(False)
        assert module.timer.isActive() is False

        shell.set_pet_visible(True)
        assert module.timer.isActive() is True
    finally:
        _cleanup(shell, module)


# ---------------------------------------------------------------- 3. 配图分支
def _write_png(directory, name="angry.png"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    pixmap = QPixmap(48, 32)
    pixmap.fill(QColor("red"))
    assert pixmap.save(str(path))
    return path


def test_image_branch_reaches_follower_show_image(tmp_path):
    """出图概率 100% + 缓存已热 → 走既有 ``show_image``（而不是文本分支）。"""
    image_dir = tmp_path / "talk-images"
    _write_png(image_dir)
    shell, _config, module, _host = _make_talk(tmp_path, _talk_values(
        self_talk_image_dir=str(image_dir),
        self_talk_image_chance=100,
        self_talk_image_scale=150,
    ))
    try:
        assert module.settings is not None and module.settings.images
        assert module.settings.image_scale == 1.5

        deadline = time.monotonic() + 10.0
        while (not getattr(shell, "_self_talk_image_cache", {})
                and time.monotonic() < deadline):
            QApplication.instance().processEvents()
            time.sleep(0.02)
        assert shell._self_talk_image_cache, "后台配图预热超时未完成"

        module.handle_timeout()
        assert shell._speech_bubble is not None
        assert shell._speech_bubble._content_kind == "image"
        assert shell._speech_bubble._image_scale == 1.5
        # 图片没有可朗读文本：显式记 None（点击路径据此保持安静）
        assert module.last_text is None
    finally:
        _cleanup(shell, module)


def test_deleted_absolute_image_dir_degrades_to_text(tmp_path):
    """用户删掉的外部图片目录不再回退内置彩蛋池（旧 window.py 语义）。"""
    shell, _config, module, _host = _make_talk(tmp_path, _talk_values(
        self_talk_image_dir=str(tmp_path / "gone"),
        self_talk_image_chance=100,
    ))
    try:
        assert module.settings is not None and module.settings.images == ()
        module.handle_timeout()
        assert shell._speech_bubble._raw_text == "自言自语台词"
    finally:
        _cleanup(shell, module)


# ---------------------------------------------------------------- 4. 点击链路
def _click_sprite(shell):
    """走真实 overlay 鼠标路由：同一位置 press→release = 单击 sprite。"""
    sprite = shell.sprite
    center = QPointF(sprite.rect().center())
    shell.overlay._mouse_grab = sprite
    shell.overlay._press_pos = QPointF(center)
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(center), QPointF(center),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier)
    shell.overlay.mouseReleaseEvent(event)


def test_click_with_self_talk_off_keeps_bubble_quiet(tmp_path):
    """点击自言自语关闭 → 点击只出动画，不出气泡也不排程。"""
    shell, _config, module, _host = _make_talk(
        tmp_path, _talk_values(self_talk_enabled=False))
    try:
        _click_sprite(shell)
        assert module.timer.isActive() is False
        assert getattr(shell._speech_bubble, "_raw_text", "") != "自言自语台词"
    finally:
        _cleanup(shell, module)


def test_click_show_balance_routes_to_shell_show_balance(tmp_path):
    """click_show_balance 优先：转 ``AppShell.show_balance``（旧 window.py 语义）。"""
    shell, _config, module, _host = _make_talk(
        tmp_path, _talk_values(click_show_balance=True))
    calls: list = []
    shell._instance.shell = type(
        "_Shell", (), {"show_balance": lambda self, parent=None: calls.append(parent)})()
    try:
        _click_sprite(shell)
        assert calls == [shell._sprite_host(shell.sprite)]
        assert calls[0] is not shell
        assert module.timer.interval() == 5000  # 走余额分支，不重排自言自语
    finally:
        _cleanup(shell, module)


# ---------------------------------------------------------------- 5. 配置热改
def test_refresh_settings_hot_reloads_self_talk_fields(tmp_path):
    """运行期改 self_talk 开关经 refresh_settings 即生效（不等重启）。"""
    shell, config, module, _host = _make_talk(tmp_path, _talk_values())
    try:
        assert module.timer.isActive() is True

        config.set("self_talk_enabled", False)
        shell.refresh_settings()
        assert module.settings is not None and module.settings.enabled is False
        assert module.timer.isActive() is False  # 关掉即停表

        config.set("self_talk_enabled", True)
        shell.refresh_settings()
        assert module.timer.isActive() is True  # 打开即重排
    finally:
        _cleanup(shell, module)


# ---------------------------------------------------------------- 6. 图片缓存口径
def test_warm_self_talk_images_prescales_big_images(tmp_path):
    """配图缓存按实际绘制盒预缩放（不是固定长边 640）。"""
    shell, _config = _make_shell(tmp_path, _talk_values(self_talk_image_chance=100))
    try:
        big = QPixmap(2000, 1000)
        big.fill(QColor(90, 120, 160))
        d = tmp_path / "big-imgs"
        d.mkdir()
        path = d / "big.png"
        assert big.save(str(path))
        shell.prepare_self_talk(images=[str(path)], image_scale=1.0)
        shell._self_talk_images = [path]
        shell._self_talk_image_cache = {}

        shell._warm_self_talk_images()
        deadline = time.monotonic() + 10.0
        while str(path) not in shell._self_talk_image_cache \
                and time.monotonic() < deadline:
            QApplication.instance().processEvents()
            time.sleep(0.02)

        cached = shell._self_talk_image_cache[str(path)]
        assert max(cached.width(), cached.height()) == shell._self_talk_image_cache_edge()
        assert not cached.isNull()
    finally:
        _cleanup(shell)
