from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _slot0_config(tmp_path):
    """生产形态的配置面：slot0 身份经 ``SlotRoutedConfig`` 分流。

    每宠键（自言自语族、气泡样式、尺寸…）的真值在 ``config-slot-0.json``：
    裸全局 ``Config.set/save`` 出闸时会过滤掉它们，改不动任何一只宠。
    """
    from pet.config import Config
    from pet.settings_slot_config import route_settings_config

    return route_settings_config(Config(base=tmp_path, instance_id="slot-0"))


def _populate_modern_menu(menu, pet):
    """旧 ``populate_context_menu`` 的等价流水线（overlay 侧同一建造器 + 安装器）。"""
    from pet.context_menus import build_modern_menu
    from pet.context_menus.menu_styles import (
        apply_modern_menu_style,
        install_modern_check_indicators,
    )
    from pet.context_menus.menu_styles.common import (
        install_responsive_menu_style,
        install_stay_open_interaction,
    )

    cfg = getattr(pet, "cfg", None)
    apply_modern_menu_style(
        menu, cfg.get("context_menu_appearance", {}) if cfg is not None else {})
    build_modern_menu(menu, pet)
    install_modern_check_indicators(menu)
    install_responsive_menu_style(menu)
    install_stay_open_interaction(menu)


def test_speech_bubble_never_accepts_focus():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble()
    assert bubble.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    bubble.close()
    app.processEvents()


def test_self_talk_bubble_presets_have_distinct_visuals_and_safe_positions():
    from PySide6.QtCore import QRect, QSize

    from pet.speech_bubble import (
        BUBBLE_STYLE_PRESETS,
        bubble_rect_for_anchor,
    )

    assert list(BUBBLE_STYLE_PRESETS) == [
        "classic_top", "paper_left", "glass_right", "soft_blue_top", "breath_bubble",
    ]
    assert len({preset["background"] for preset in BUBBLE_STYLE_PRESETS.values()}) == 5
    assert {preset["placement"] for preset in BUBBLE_STYLE_PRESETS.values()} == {
        "top", "top_left", "top_right",
    }
    available = QRect(0, 0, 1440, 900)
    pet = QRect(620, 420, 220, 260)
    for preset in BUBBLE_STYLE_PRESETS.values():
        bubble = bubble_rect_for_anchor(pet, QSize(240, 92), available, preset["placement"])
        assert available.contains(bubble)
        assert not bubble.intersects(pet)


def test_breath_bubble_uses_organic_water_shape_and_detached_trailing_bubbles():
    import math

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble(style_id="breath_bubble")
    bubble.show_text("今天也要认真工作呀。", QRect(420, 460, 180, 240), 5000)
    app.processEvents()
    assert bubble._preset["shape"] == "breath_bubble"
    assert not bubble._main_bubble_path.isEmpty()
    assert len(bubble._breath_paths) == 2
    assert all(not path.isEmpty() for path in bubble._breath_paths)
    assert bubble._water_fill == "#d9f2fb"
    assert bubble._shadow_alpha == 0
    main = bubble._main_bubble_path.boundingRect()
    assert 1.17 <= main.width() / main.height() <= 1.27
    assert bubble._water_start_ratio <= 0.50
    assert bubble._highlight_width_ratios[0] <= 0.16
    assert bubble._highlight_width_ratios[1] <= 0.05

    def edge_distance(first, second):
        first_points = [first.pointAtPercent(index / 160) for index in range(161)]
        second_points = [second.pointAtPercent(index / 160) for index in range(161)]
        return min(
            math.hypot(left.x() - right.x(), left.y() - right.y())
            for left in first_points for right in second_points
        )

    first_gap = edge_distance(bubble._main_bubble_path, bubble._breath_paths[0])
    second_gap = edge_distance(bubble._breath_paths[0], bubble._breath_paths[1])
    assert 2.0 <= first_gap <= 7.0
    assert 2.0 <= second_gap <= 7.0
    assert abs(first_gap - second_gap) <= 2.0
    assert all(path.elementCount() >= 10 for path in bubble._breath_paths)
    bubble.close()
    app.processEvents()


def test_breath_bubble_size_tracks_the_visible_pet_without_dominating_it():
    from PySide6.QtCore import QRect, QSize
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import (
        PetSpeechBubble,
        breath_bubble_size_for_anchor,
        breath_bubble_size_for_scale,
    )

    app = QApplication.instance() or QApplication([])
    small_pet = QRect(420, 460, 180, 240)
    large_pet = QRect(420, 460, 360, 480)

    assert breath_bubble_size_for_anchor(small_pet) == QSize(168, 137)
    assert breath_bubble_size_for_anchor(large_pet) == QSize(216, 176)
    scale_sizes = [breath_bubble_size_for_scale(value) for value in (0.5, 0.72, 0.85, 1.0)]
    assert [size.width() for size in scale_sizes] == sorted({size.width() for size in scale_sizes})

    bubble = PetSpeechBubble(style_id="breath_bubble")
    bubble.show_text("今天也要认真工作呀。", small_pet, 5000)
    app.processEvents()
    assert bubble.size() == QSize(168, 137)
    assert bubble.width() <= small_pet.width()
    # offscreen QPA shifts windows on show(); assert the placement logic
    # directly so the visual gap contract (7px design) is platform-stable.
    bubble._place(small_pet)
    visible_bubble_bottom = bubble.y() + bubble._surface_path.boundingRect().bottom()
    visual_gap = small_pet.top() - visible_bubble_bottom
    assert 5 <= visual_gap <= 9
    visible_surface = bubble._surface_path.translated(bubble.x(), bubble.y())
    pet_path = bubble._surface_path.__class__()
    pet_path.addRect(small_pet)
    assert visible_surface.intersected(pet_path).isEmpty()
    assert 1.17 <= bubble._main_bubble_path.boundingRect().width() / bubble._main_bubble_path.boundingRect().height() <= 1.27
    bubble.close()
    app.processEvents()


def test_breath_bubble_reflows_on_pet_scale_change_and_summarizes_markdown():
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    pet = QRect(420, 460, 220, 260)
    bubble = PetSpeechBubble(style_id="breath_bubble")
    bubble.show_text(
        "## 小狐狸的星空故事\n森林边有一棵老树，树洞里住着一只小狐狸。"
        "每天傍晚它都会抬头看星星，并把看到的故事记在叶片上。"
        "它把叶片一片片夹进树洞深处的旧书里，等月亮升起来的时候，"
        "就坐在树根上给路过的旅人讲这些星星的故事，讲着讲着自己也睡着了。" * 2,
        pet,
        5000,
        pet_scale=0.5,
    )
    app.processEvents()
    small_width = bubble.width()
    assert "##" not in bubble.label.text()
    assert bubble.label.text().count("\n") <= 5  # 长文本放宽到 6 行
    assert bubble.label.text().endswith("…")  # 超出 6 行仍省略收尾

    bubble.reflow(pet, pet_scale=1.0)
    app.processEvents()
    assert bubble.width() > small_width
    assert bubble.label.pixmap().isNull()
    bubble.close()
    app.processEvents()


def test_breath_bubble_keeps_its_shape_but_adapts_to_text_and_image_content(tmp_path):
    from PIL import Image
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    pet = QRect(420, 460, 220, 260)
    bubble = PetSpeechBubble(style_id="breath_bubble")
    bubble.show_text("好女孩……", pet, 5000, pet_scale=0.72)
    app.processEvents()
    short_size = bubble.size()

    bubble.show_text(
        "今天也要认真工作，完成任务后一起去看看星星和蓝色的大海吧。",
        pet, 5000, pet_scale=0.72,
    )
    app.processEvents()
    assert bubble.width() > short_size.width()
    assert abs(bubble.width() / bubble.height() - 240 / 195) < 0.03

    image = tmp_path / "square.png"
    Image.new("RGB", (240, 240), "white").save(image)
    assert bubble.show_image(image, pet, 5000, pet_scale=0.72)
    app.processEvents()
    assert bubble.width() > short_size.width()
    assert bubble._breath_image_rect.height() >= 104
    assert abs(bubble.width() / bubble.height() - 240 / 195) < 0.03
    bubble.close()
    app.processEvents()


def test_breath_bubble_image_is_clipped_and_painted_below_water_details(tmp_path):
    from PIL import Image
    from PySide6.QtCore import QPointF, QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    image = tmp_path / "square-content.png"
    Image.new("RGB", (300, 300), "red").save(image)
    bubble = PetSpeechBubble(style_id="breath_bubble")
    assert bubble.show_image(
        image, QRect(420, 460, 220, 260), 5000, pet_scale=0.72
    )
    app.processEvents()

    # A child QLabel paints after the parent and used to cover the water,
    # outline and highlight with an un-clipped rectangular image.
    assert bubble.label.pixmap().isNull()
    assert not bubble._breath_image_rect.isEmpty()
    assert not bubble._breath_image_clip_path.isEmpty()
    assert bubble._breath_image_clip_path.contains(
        QPointF(bubble._breath_image_rect.center())
    )
    assert not bubble._breath_image_clip_path.contains(
        QPointF(bubble._breath_image_rect.topLeft())
    )
    bubble.close()
    app.processEvents()


def test_breath_image_position_uses_actual_window_size_not_hidden_label_hint(tmp_path):
    from PIL import Image
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble, bubble_rect_for_anchor

    app = QApplication.instance() or QApplication([])
    image = tmp_path / "position.png"
    Image.new("RGB", (300, 300), "blue").save(image)
    anchor = QRect(420, 460, 220, 260)
    bubble = PetSpeechBubble(style_id="breath_bubble")
    assert bubble.show_image(image, anchor, 5000, pet_scale=0.72)
    app.processEvents()
    available = app.primaryScreen().availableGeometry()
    expected = bubble_rect_for_anchor(
        anchor, bubble.size(), available, bubble._preset["placement"]
    )
    assert bubble.sizeHint() != bubble.size()
    assert bubble.x() == expected.x()
    bubble.close()
    app.processEvents()


def test_standard_bubble_images_keep_retina_device_pixel_density(tmp_path, monkeypatch):
    from PIL import Image
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    image = tmp_path / "retina.png"
    Image.new("RGB", (600, 600), "blue").save(image)
    bubble = PetSpeechBubble(style_id="paper_left")
    # 打在**类**上，不打在实例上：monkeypatch 对实例属性记下的旧值是本类的
    # bound method，undo() 会把它写回 ``bubble.__dict__``，形成
    # ``bubble -> __dict__ -> bound method -> bubble`` 的自环 ⇒ 引用计数永远归不了
    # 零，Python 包装只能等周期性 GC 回收，C++ 侧 QWidget 也就落到任意时点销毁
    # （实测落在别的用例的 import 里，属于 conftest 记的「Garbage-collecting /
    # no Python frame」原生崩溃家族；本用例的顶层窗口清扫因此看不到它，收口失效）。
    # ``devicePixelRatioF`` 来自 QWidget、不在 ``PetSpeechBubble.__dict__`` 里，
    # 类级补丁的旧值是 NOTSET，undo() 走 delattr，不留自环。
    monkeypatch.setattr(PetSpeechBubble, "devicePixelRatioF", lambda self: 2.0)
    assert bubble.show_image(image, QRect(420, 460, 220, 260), 5000)
    app.processEvents()
    bubble.grab()
    assert bubble.label.pixmap().isNull()
    assert bubble._source_pixmap.width() >= bubble.label.width() * 2
    assert bubble._standard_image_rect.toRect() == bubble.label.geometry()
    bubble.close()
    app.processEvents()
    # 类级补丁不应给实例留下方法覆盖，避免 undo 恢复 bound method 形成自环。
    assert "devicePixelRatioF" not in bubble.__dict__


def test_all_bubble_presets_use_soft_layered_shadows():
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import BUBBLE_STYLE_PRESETS, PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    for style_id in BUBBLE_STYLE_PRESETS:
        bubble = PetSpeechBubble(style_id=style_id)
        bubble.show_text("阴影测试", QRect(420, 460, 220, 260), 5000)
        app.processEvents()
        assert len(bubble._shadow_layers) >= 3
        widths = [layer[0] for layer in bubble._shadow_layers]
        alphas = [layer[1] for layer in bubble._shadow_layers]
        assert widths == sorted(widths, reverse=True)
        assert alphas == sorted(alphas)
        assert alphas[0] > 0
        bubble.close()
    app.processEvents()


def test_self_talk_images_and_duration_are_normalized_and_scheduled_after_hide(tmp_path, monkeypatch):
    from PIL import Image

    from pet.config import Config, DEFAULT_SELF_TALK_DURATION_SECONDS
    from pet.speech_bubble import list_self_talk_images

    image_dir = tmp_path / "talk-images"
    image_dir.mkdir()
    Image.new("RGB", (20, 10), "blue").save(image_dir / "one.png")
    (image_dir / "ignore.txt").write_text("not an image", encoding="utf-8")

    config = _slot0_config(tmp_path)
    assert config.get("self_talk_duration_seconds") == DEFAULT_SELF_TALK_DURATION_SECONDS
    config.set("self_talk_duration_seconds", 7.5)
    config.set("self_talk_image_dir", str(image_dir))
    assert config.save() is True
    loaded = _slot0_config(tmp_path)
    assert loaded.get("self_talk_duration_seconds") == 7.5
    assert loaded.get("self_talk_image_dir") == str(image_dir)
    assert list_self_talk_images(str(image_dir)) == [image_dir / "one.png"]

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication
    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble(style_id="breath_bubble")
    assert bubble.show_image(
        image_dir / "one.png", QRect(420, 460, 220, 260),
        5000, pet_scale=0.72,
    )
    app.processEvents()
    assert not bubble._source_pixmap.isNull()
    assert not bubble._breath_image_rect.isEmpty()


def test_self_talk_image_scale_config_and_bubble_size(tmp_path):
    """气泡配图尺寸：配置 50~300 钳位 + 气泡按 image_scale 放大（双气泡形态都验证）。"""
    from PIL import Image

    from pet.config import Config

    image_dir = tmp_path / "talk-images"
    image_dir.mkdir()
    Image.new("RGB", (20, 10), "blue").save(image_dir / "one.png")

    config = _slot0_config(tmp_path)
    assert config.get("self_talk_image_scale") == 100  # 默认
    config.set("self_talk_image_scale", 250)
    assert config.save() is True
    loaded = _slot0_config(tmp_path)
    assert loaded.get("self_talk_image_scale") == 250
    # 钳位：越界/非数值
    config.set("self_talk_image_scale", 9999)
    assert config.save() is True
    assert _slot0_config(tmp_path).get("self_talk_image_scale") == 300
    config.set("self_talk_image_scale", "abc")
    assert config.save() is True
    assert _slot0_config(tmp_path).get("self_talk_image_scale") == 100

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication
    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    anchor = QRect(420, 460, 220, 260)
    normal = PetSpeechBubble()
    big = PetSpeechBubble()
    assert normal.show_image(image_dir / "one.png", anchor, 5000, image_scale=1.0)
    assert big.show_image(image_dir / "one.png", anchor, 5000, image_scale=2.5)
    assert big.label.width() > normal.label.width() * 2
    # 呼吸气泡形态同样吃缩放
    breath_normal = PetSpeechBubble(style_id="breath_bubble")
    breath_big = PetSpeechBubble(style_id="breath_bubble")
    assert breath_normal.show_image(image_dir / "one.png", anchor, 5000, pet_scale=0.72, image_scale=1.0)
    assert breath_big.show_image(image_dir / "one.png", anchor, 5000, pet_scale=0.72, image_scale=2.5)
    assert breath_big.width() > breath_normal.width()
    # 超界缩放被弹窗侧钳住（双保险）
    huge = PetSpeechBubble()
    capped = PetSpeechBubble()
    assert huge.show_image(image_dir / "one.png", anchor, 5000, image_scale=99.0)
    assert capped.show_image(image_dir / "one.png", anchor, 5000, image_scale=3.0)
    assert huge._image_scale == 3.0
    assert huge.label.width() == capped.label.width()
    app.processEvents()
    for w in (normal, big, breath_normal, breath_big, huge, capped):
        w.close()
    app.processEvents()


def test_speech_bubble_tail_is_one_surface_and_shadow_has_no_graphics_effect():
    from PySide6.QtCore import QPointF, QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    app = QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble(style_id="classic_top")
    bubble.show_text("今天也要认真工作呀。", QRect(320, 420, 180, 240), 5000)
    app.processEvents()
    assert bubble.graphicsEffect() is None
    assert not bubble._surface_path.isEmpty()
    base_center = QPointF(
        (bubble._tail_base[0].x() + bubble._tail_base[1].x()) / 2,
        (bubble._tail_base[0].y() + bubble._tail_base[1].y()) / 2,
    )
    inside_tail = QPointF(
        bubble._tail_tip.x() * 0.8 + base_center.x() * 0.2,
        bubble._tail_tip.y() * 0.8 + base_center.y() * 0.2,
    )
    assert bubble._surface_path.contains(inside_tail)
    assert bubble._surface_path.contains(base_center)
    assert bubble._shadow_offset_y <= 2
    bubble.close()
    app.processEvents()


def test_self_talk_bubble_style_is_normalized_and_persisted(tmp_path):
    from pet.config import Config

    config = _slot0_config(tmp_path)
    assert config.get("self_talk_bubble_style") == "classic_top"
    config.set("self_talk_bubble_style", "glass_right")
    assert config.save() is True
    assert _slot0_config(tmp_path).get("self_talk_bubble_style") == "glass_right"
    config.set("self_talk_bubble_style", "unknown")
    # 脏值在**落盘后的读端**被归一（路由视图对未保存的草稿按原样回显，清洗发生在
    # 同源默认那条读规则上——唯一清洗实现仍是 Config 的每宠快照规范化）。
    assert config.save() is True
    assert _slot0_config(tmp_path).get("self_talk_bubble_style") == "classic_top"


def test_icon_composition_ignores_low_alpha_noise_and_fills_canvas():
    from PIL import Image, ImageDraw

    script = Path("scripts/make_icon.py")
    spec = importlib.util.spec_from_file_location("make_icon_for_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    source = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((290, 120, 349, 239), fill=(40, 100, 180, 255))
    draw.point((1, 1), fill=(255, 255, 255, 1))

    icon = module.prepare_icon_image(source, side=256)
    bbox = icon.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    assert icon.size == (256, 256)
    assert bbox is not None
    assert max(bbox[2] - bbox[0], bbox[3] - bbox[1]) >= 248




def test_context_menu_has_no_template_switch_entry(tmp_path):
    """模板切换入口随旧版菜单一起退役（2026-10-08）。

    旧版菜单是**被删除**的，不是被隐藏的：即使配置里残留了已退役的模板键，
    右键出来的仍是现代树，且树里不再有任何「切换到…菜单」入口。旧版布局的
    源码级防复活断言在 ``tests/test_architecture.py``（退役符号全树零命中）。
    """
    from PySide6.QtWidgets import QApplication, QMenu

    class Config:
        def __init__(self):
            self.values = {"context_menu_template": "legacy", "character": "shenshen"}

        def get(self, key, default=None):
            return self.values.get(key, default)

    class Pet:
        on_open_chat = on_open_chat_settings = None
        on_open_modern_settings = None
        on_spawn_pet = None
        idles = turns = moves = clicks = acts = []
        playback_speed = scale = 1.0
        drag_physics = no_move = False

        def __init__(self):
            self.cfg = Config()

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    _populate_modern_menu(menu, Pet())
    labels = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert menu.objectName() == "modernContextMenu"
    assert "切换到新版菜单" not in labels
    assert "切换回旧版菜单" not in labels
    assert "桌宠控制" in labels and "工具与帮助" in labels
    menu.close()
    app.processEvents()


def test_pet_avatar_menu_icon_fills_native_slot_and_stays_centered(monkeypatch):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QStyle

    from pet.context_menus.icons import pet_avatar_menu_icon

    class FakePet:
        @staticmethod
        def icon_pixmap(size=64):
            # Reproduce a Retina source: physical dimensions are twice the
            # logical dimensions. The old painter path rendered this at 1/2 size.
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            from PySide6.QtGui import QPainter

            painter = QPainter(pixmap)
            painter.fillRect(QRect(size // 4, 0, size // 2, size), Qt.GlobalColor.blue)
            painter.end()
            pixmap.setDevicePixelRatio(2.0)
            return pixmap

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    native_size = menu.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize, None, menu)
    icon = pet_avatar_menu_icon(menu, FakePet())
    pixmap = icon.pixmap(native_size, native_size)
    # Retina menu (dpr=2) yields physical 32px backing for the same 16 logical slot.
    dpr = pixmap.devicePixelRatio() or 1.0
    assert pixmap.width() / dpr == native_size
    assert pixmap.height() / dpr == native_size
    assert icon.availableSizes()[0].width() / dpr == native_size
    # Inspect actual non-transparent pixels, not merely the QImage canvas.
    points = [
        (x, y)
        for y in range(pixmap.height())
        for x in range(pixmap.width())
        if pixmap.toImage().pixelColor(x, y).alpha() > 0
    ]
    left, right = min(x for x, _ in points), max(x for x, _ in points)
    top, bottom = min(y for _, y in points), max(y for _, y in points)
    assert (bottom - top + 1) / dpr >= native_size * 0.8
    assert abs(((left + right) / 2.0) / dpr - ((native_size - 1) / 2.0)) <= 1.0
    menu.close()
    app.processEvents()


def test_modern_context_menu_has_compact_semantic_groups(monkeypatch):
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QMenu

    import pet.catalog as catalog_mod
    import pet.context_menus.registry as registry_mod
    import pet.context_menus.shared as menu_shared

    class FakeConfig:
        def __init__(self):
            self.values = {
                "character": "shenshen",
                "on_top": True,
            }

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            return None

    class FakePet:
        on_open_chat = lambda self: None
        on_look_screen = lambda self: None
        on_show_balance = lambda self, parent=None: None
        on_open_chat_settings = lambda self: None
        on_open_modern_settings = lambda self: None
        on_spawn_pet = lambda self: None
        idles = ["待机"]
        turns = ["转向"]
        moves = ["移动"]
        clicks = ["点击"]
        acts = ["动作"]
        playback_speed = 1.0
        drag_physics = False
        no_move = False
        scale = 1.0

        def __init__(self):
            self.cfg = FakeConfig()

        def icon_pixmap(self, size=64):
            pixmap = QPixmap(size, size)
            pixmap.fill()
            return pixmap

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(menu_shared.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(catalog_mod, "list_available_characters", lambda: ["shenshen"])
    pet = FakePet()
    menu = QMenu()
    _populate_modern_menu(menu, pet)
    labels = [action.text() for action in menu.actions() if not action.isSeparator()]
    expected_labels = [
        "AI 对话",
        "看看屏幕",
        "截图提问",
        "播放动画",
        "切换角色",
        "播放速率",
        "大小",
        "桌宠控制",
        "快捷启动",
        "工具与帮助",
        "Agent 联动",
    ]
    if sys.platform == "win32":
        expected_labels.append("主动识屏")  # 仅 Windows + 有聊天能力时显示
    expected_labels.append("待办提醒")  # 待办管理面板入口（所有平台）
    expected_labels.append("专注模式")
    expected_labels.append("免打扰")    # 免打扰入口（#208，四档时长子菜单）
    expected_labels.extend([
        "桌宠设置",
        "退出",
    ])
    assert labels == expected_labels
    animation_action = next(action for action in menu.actions() if action.text() == "播放动画")
    assert animation_action.menu() is not None
    assert [action.text() for action in animation_action.menu().actions()] == [
        "待机",
        "转向",
        "移动",
        "点击回应",
        "随机动作",
    ]
    assert next(action for action in menu.actions() if action.text() == "播放速率").menu() is not None
    assert next(action for action in menu.actions() if action.text() == "大小").menu() is not None
    # 模板模式已迁入设置；默认菜单不再用低频迁移命令占据根菜单。
    assert all("旧版菜单" not in action.text() for action in menu.actions())
    menu.close()
    app.processEvents()


def test_pure_pet_context_menu_keeps_web_but_hides_harness():
    """纯桌宠（无 Chat/DSH 联动）右键菜单去掉 DeepSeek Harness。"""
    from PySide6.QtWidgets import QApplication, QMenu

    class FakeConfig:
        def get(self, key, default=None):
            return {
                "character": "shenshen",
                "context_menu_appearance": {"theme": "light"},
            }.get(key, default)

    class FakePet:
        cfg = FakeConfig()
        on_open_chat = None
        on_open_chat_settings = None
        on_open_modern_settings = None
        on_spawn_pet = None
        idles = turns = moves = clicks = acts = []
        playback_speed = scale = 1.0
        drag_physics = no_move = False

        def __getattr__(self, name):
            return None

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    _populate_modern_menu(menu, FakePet())
    def labels_in(menu):
        labels = []
        for action in menu.actions():
            if action.isSeparator():
                continue
            labels.append(action.text())
            if action.menu() is not None:
                labels.extend(labels_in(action.menu()))
        return labels

    labels = labels_in(menu)
    # Harness 入口现为子菜单（标题 "DeepSeek Harness"），纯桌宠版整块不显示
    assert "DeepSeek Harness" not in labels
    assert "启动 dsh web 界面" not in labels
    assert "启动桌面端界面" not in labels
    assert "停止服务" not in labels
    menu.close()
    app.processEvents()


def test_context_menu_always_applies_the_modern_style():
    from PySide6.QtWidgets import QApplication, QMenu, QStyle, QWidget

    class Config:
        def get(self, key, default=None):
            return {
                "character": "shenshen",
                # 固定浅色主题，避免断言随系统深色模式翻转
                "context_menu_appearance": {"theme": "light"},
            }.get(key, default)

    class Pet:
        on_open_chat = on_open_chat_settings = None
        on_open_modern_settings = None
        on_spawn_pet = None
        idles = turns = moves = clicks = acts = []
        playback_speed = scale = 1.0
        drag_physics = no_move = False

        def __init__(self):
            self.cfg = Config()

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    _populate_modern_menu(menu, Pet())
    assert menu.objectName() == "modernContextMenu"
    # The modern menu follows the compact macOS project-menu reference: a
    # white hairline surface, small system text, outline icons and subtle rules
    # between semantic groups.
    assert "background-color: rgba(255, 255, 255, 240)" in menu.styleSheet()
    assert "border: none" in menu.styleSheet()
    hairline = menu.findChild(QWidget, "modernHairlineBorder")
    assert hairline is not None
    assert hairline.property("physicalPixelWidth") == 1
    assert "border-radius: 12px" in menu.styleSheet()
    assert "font-size: 13px" in menu.styleSheet()
    assert "icon-size: 18px" in menu.styleSheet()
    assert "background-color: #eeeeee" in menu.styleSheet()
    assert "min-height: 18px" in menu.styleSheet()
    assert "padding: 3px 29px 3px 13px" in menu.styleSheet()
    assert "margin-right: 10px" in menu.styleSheet()
    assert "QMenu::separator" in menu.styleSheet()
    separator_rule = menu.styleSheet().split("QMenu::separator", 1)[1]
    assert "height: 1px" in separator_rule
    assert "background: #e5e5e5" in separator_rule
    assert Path("pet/context_menus/menu_styles/common.py").is_file()
    assert Path("pet/context_menus/menu_styles/modern.py").is_file()
    assert menu.style().styleHint(QStyle.StyleHint.SH_Menu_SubMenuPopupDelay, None, menu) == 60
    assert menu.style().styleHint(QStyle.StyleHint.SH_Menu_SubMenuSloppyCloseTimeout, None, menu) == 120
    assert menu.style().styleHint(QStyle.StyleHint.SH_Menu_SubMenuSloppySelectOtherActions, None, menu) == 1
    assert menu.style().styleHint(QStyle.StyleHint.SH_Menu_SubMenuUniDirection, None, menu) == 0
    menu.close()
    app.processEvents()


def test_submenu_inherits_the_modern_style_from_its_parent():
    """子菜单样式继承：父菜单没打上 ``menuStyle`` 属性时也必须落现代样式。

    回归背景：``inherit_menu_style`` 原先按 ``menuStyle`` 分支，取不到属性时
    默认值指向已退役的旧版样式——任何"父菜单属性还没设上"的子菜单会静默掉
    样式，露出原生外观（旧版样式已删除，默认值只能指向现代）。
    """
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.menu_styles.common import inherit_menu_style

    app = QApplication.instance() or QApplication([])
    parent = QMenu()          # 刻意不设 menuStyle 属性（默认值路径）
    submenu = QMenu(parent)
    inherit_menu_style(parent, submenu)
    assert submenu.property("menuStyle") == "modern"
    assert submenu.objectName() == "modernContextMenu"
    assert submenu.styleSheet() != "", "子菜单必须套上现代样式（不能露原生外观）"
    parent.close()
    app.processEvents()


def test_modern_menu_icons_are_crisp_outline_glyphs(monkeypatch):
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.icons import vector_menu_icon
    from pet.context_menus.menu_styles.modern import apply_modern_menu_style

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    # 固定浅色主题：深色系统下菜单图标为浅灰（深色菜单设计），
    # 该断言验证的是浅色菜单的深色轮廓图标
    apply_modern_menu_style(menu, {"theme": "light"})
    names = ("chat", "play", "character", "speed", "spawn", "settings", "web", "exit")
    cache_keys = []
    for name in names:
        icon = vector_menu_icon(menu, name)
        pixmap = icon.pixmap(18, 18)
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        cache_keys.append(icon.cacheKey())
        opaque_pixels = 0
        dark_pixels = 0
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixelColor(x, y))
                if color.alpha() > 24:
                    opaque_pixels += 1
                    if max(color.red(), color.green(), color.blue()) < 150:
                        dark_pixels += 1
        assert opaque_pixels >= 12
        assert dark_pixels >= 8
    assert len(set(cache_keys)) == len(names)
    menu.close()
    app.processEvents()


def test_modern_checked_action_is_painted_in_reserved_right_slot():
    from PySide6.QtWidgets import QApplication, QMenu, QWidget

    from pet.context_menus.menu_styles.modern import (
        apply_modern_menu_style,
        install_modern_check_indicators,
    )

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    apply_modern_menu_style(menu)
    action = menu.addAction("窗口置顶")
    action.setCheckable(True)
    action.setChecked(True)
    install_modern_check_indicators(menu)
    assert menu.property("paintChecksOnRight") is True
    assert menu.findChild(QWidget, "modernEnabledIndicator") is None
    assert menu.findChild(QWidget, "modernCheckLayer") is not None
    assert "padding:" in menu.styleSheet()
    action.setChecked(False)
    app.processEvents()
    assert action.isChecked() is False
    action.setChecked(True)
    app.processEvents()
    assert action.isChecked() is True
    menu.close()
    app.processEvents()


def test_modern_settings_panel_uses_sidebar_and_includes_ai_settings(tmp_path, monkeypatch):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import QApplication, QListWidget, QStackedWidget

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    app = QApplication.instance() or QApplication([])
    config = Config(tmp_path)
    autostart_values = []
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(settings_mod.autostart_mod, "set_enabled", autostart_values.append)
    dialog = ModernSettingsDialog(config, include_ai=True)
    assert dialog.size() == QSize(800, 560)
    assert dialog.minimumSize() == QSize(720, 500)
    assert dialog.font().pixelSize() == 13
    assert dialog.findChild(settings_mod.QFrame, "sidebarPane").width() == 200
    assert isinstance(dialog.sidebar, QListWidget)
    assert isinstance(dialog.pages, QStackedWidget)
    expected_pages = ["常规", "桌宠", "互动", "菜单", "桌面组件", "AI 与对话", "自动化与联动"]
    assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == expected_pages
    assert dialog.pages.count() == len(expected_pages)
    assert dialog.search_edit.placeholderText() == "搜索设置…"
    assert all(not dialog.sidebar.item(i).icon().isNull() for i in range(dialog.sidebar.count()))
    assert all(dialog.sidebar.item(i).sizeHint().height() >= 34 for i in range(dialog.sidebar.count()))
    assert "QListWidget#settingsSidebar::item:hover" in dialog.styleSheet()
    assert "border-right: 1px solid #e3e5e8" in dialog.styleSheet()
    assert "background: #f7f7f8" in dialog.styleSheet()
    section_titles = [label.text() for label in dialog.findChildren(settings_mod.QLabel, "sectionTitle")]
    assert {
        "应用启动", "窗口与系统", "动画与移动", "点击反馈", "自言自语",
        "显示", "菜单外观", "对话窗口", "已配置应用", "内容与布局",
        "模型与连接", "视觉能力",
    }.issubset(set(section_titles))
    if hasattr(dialog, "pro_enabled_check"):
        # 「自动化与联动」的「主动识屏」不再是一张压平的大卡（同上）。
        # 这几组只在 Windows 构造（settings_pet_controls 的平台闸门）。
        assert {"主动识屏 · 开关与节奏", "主动识屏 · 什么时候看", "主动识屏 · 看哪些软件",
                }.issubset(set(section_titles))
    advanced_titles = [
        button.text()
        for button in dialog.findChildren(
            settings_mod.SettingsDisclosureHeader,
            "advancedSectionToggle",
        )
    ]
    assert {"生成参数（高级）", "高级配色"}.issubset(set(advanced_titles))
    assert "碰撞参数（高级）" not in advanced_titles
    assert {"浅色主题", "深色主题"}.issubset(set(section_titles))
    scale_row = dialog.findChild(settings_mod.QWidget, "settingRow_scale")
    assert scale_row is not None
    assert scale_row.findChild(settings_mod.QLabel, "settingLabel").text() == "桌宠大小"
    assert scale_row.findChild(settings_mod.QLabel, "settingHint").text()
    stylesheet = dialog.styleSheet()
    assert "QLineEdit:focus" in stylesheet
    assert "QSpinBox::up-button" in stylesheet
    assert "QScrollBar::handle:vertical" in stylesheet
    assert "font-size: 13px" in stylesheet
    assert "font-size: 22px" in stylesheet
    assert "min-height: 20px" in stylesheet
    dialog.scale_combo.setCurrentIndex(dialog.scale_combo.findData(0.85))
    dialog.on_top_check.setChecked(False)
    dialog.no_move_check.setChecked(True)
    dialog.autostart_check.setChecked(True)
    assert isinstance(dialog.scale_combo, settings_mod.ModernSelect)
    assert isinstance(dialog.speed_select, settings_mod.ModernSelect)
    assert isinstance(dialog.bubble_style_select, settings_mod.ModernSelect)
    assert [dialog.bubble_style_select.itemText(index) for index in range(dialog.bubble_style_select.count())] == [
        "经典暖黄 · 正上方",
        "纸感卡片 · 左上方",
        "深色玻璃 · 右上方",
        "柔蓝对话 · 正上方",
        "吐气水泡 · 左上方",
    ]
    assert "SettingsPopup" in dialog.scale_combo.popupStyleSheet()
    assert dialog.gap_spin.maximumWidth() <= 100
    assert dialog.self_talk_duration_spin.value() == 3.2
    assert dialog.self_talk_image_dir_picker.directory is True
    texts_row = dialog.findChild(settings_mod.SettingRow, "settingRow_self_talk_texts")
    assert texts_row.property("stackedControl") is True
    assert dialog.texts_edit.maximumHeight() <= 180

    def page_index(row):
        return next(index for index in range(dialog.pages.count()) if dialog.pages.widget(index).isAncestorOf(row))

    def sidebar_index(title):
        return next(index for index in range(dialog.sidebar.count()) if dialog.sidebar.item(index).text() == title)

    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_autostart")) == 0
    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_playback_speed")) == 1
    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_self_talk_texts")) == 2
    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_scale")) == 1
    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_chat_ui_style")) == 5
    assert page_index(dialog.findChild(settings_mod.SettingRow, "settingRow_api_url")) == 5
    if settings_mod.sys.platform != "win32":
        assert dialog.auto_hide_fullscreen_check is None
    assert "台词风格" not in [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
    expression_row = dialog.findChild(settings_mod.SettingRow, "settingRow_dialogue_mode")
    assert expression_row is not None
    assert expression_row.findChild(settings_mod.QLabel, "settingLabel").text() == "表达风格"
    # 产品 hint 文案（modern_settings_dialog.py）以「自言自语、候选内容和主动气泡」起句，
    # 并显式说明同时覆盖 Agent 状态/审批/提问/错误等联动气泡。
    assert "自言自语" in expression_row.findChild(settings_mod.QLabel, "settingHint").text()
    assert "Agent 状态" in expression_row.findChild(settings_mod.QLabel, "settingHint").text()
    # 表达风格（dialogue_*）已按 spec（agent-dialogue-per-agent）全量迁入 automation 域
    # 「文案风格与模板」组；互动域不再持有 dialogue 行（见 test_express_style_rows_move_to_agent_domain）。
    assert page_index(expression_row) == sidebar_index("自动化与联动")
    dialog.show()
    dialogue_page_index = next(
        index for index in range(dialog.sidebar.count())
        if dialog.sidebar.item(index).text() == "互动"
    )
    dialog.pages.widget(dialogue_page_index).findChild(settings_mod.QScrollArea, "settingsScroll").ensureWidgetVisible(texts_row)
    app.processEvents()
    label = texts_row.findChild(settings_mod.QLabel, "settingLabel")
    hint = texts_row.findChild(settings_mod.QLabel, "settingHint")
    assert hint.y() - (label.y() + label.height()) <= 4
    prompt_row = dialog.findChild(settings_mod.SettingRow, "settingRow_system_prompt")
    prompt_label = prompt_row.findChild(settings_mod.QLabel, "settingLabel")
    prompt_hint = prompt_row.findChild(settings_mod.QLabel, "settingHint")
    assert prompt_hint.y() - (prompt_label.y() + prompt_label.height()) <= 4
    editor = dialog.quick_launch_editor
    assert editor.list.dragDropMode() == settings_mod.QAbstractItemView.DragDropMode.InternalMove
    assert editor.list.iconSize().width() >= 22
    assert editor.list.item(0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert editor.list.item(0).checkState() == Qt.CheckState.Unchecked
    assert dialog.findChild(settings_mod.QDialogButtonBox, "settingsButtons") is None
    assert dialog.save_exit_button.parent() is dialog.findChild(settings_mod.QFrame, "sidebarPane")
    dialog.speed_select.setCurrentData(1.5)
    dialog.bubble_style_select.setCurrentData("paper_left")
    dialog.self_talk_duration_spin.setValue(8.5)
    dialog.self_talk_image_dir_picker.setText(str(tmp_path.resolve()))
    dialog.ai_page.url.setText("https://example.test/v1")
    dialog.ai_page.model.setText("deepseek-test")
    dialog._save()
    # #271：空身份设置会话按 slot0 分流——每宠键落 config-slot-0.json、全局键落
    # config.json；写盘经路由视图自己的对象，与本文件既有惯例同口径：读回用新视图。
    loaded = _slot0_config(tmp_path)
    global_config = Config(tmp_path)
    assert loaded.get("scale") == 0.85
    assert global_config.get("on_top") is False
    assert global_config.get("no_move") is True
    assert loaded.get("playback_speed") == 1.5
    assert loaded.get("self_talk_bubble_style") == "paper_left"
    assert loaded.get("self_talk_duration_seconds") == 8.5
    assert loaded.get("self_talk_image_dir") == str(tmp_path.resolve())
    assert global_config.chat_settings().active_config.base_url == "https://example.test/v1"
    assert global_config.chat_settings().active_config.model == "deepseek-test"
    assert autostart_values == [True]
    app.processEvents()


def test_modern_settings_progressively_reveals_dependent_controls(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)

    vision_model = dialog.findChild(settings_mod.SettingRow, "settingRow_vision_model")
    custom_background = dialog.findChild(settings_mod.SettingRow, "settingRow_chat_background_file")
    self_talk_rows = [
        dialog.findChild(settings_mod.SettingRow, f"settingRow_{key}")
        for key in (
            "self_talk_duration", "self_talk_min", "self_talk_max",
            "self_talk_texts", "self_talk_images", "self_talk_image_scale",
            "self_talk_image_chance",
        )
    ]
    opacity = dialog.findChild(settings_mod.SettingRow, "settingRow_menu_opacity")

    assert vision_model.isHidden() is dialog.ai_page.vision_same.isChecked()
    dialog.ai_page.vision_same.setChecked(False)
    assert not vision_model.isHidden()
    assert custom_background.isHidden()
    dialog.ai_page.background_select.setCurrentData("custom")
    assert not custom_background.isHidden()
    dialog.self_talk_check.setChecked(False)
    assert all(row is not None and row.isHidden() for row in self_talk_rows)
    dialog.self_talk_check.setChecked(True)
    assert all(row is not None and not row.isHidden() for row in self_talk_rows)
    dialog.menu_translucent_check.setChecked(False)
    assert opacity.isHidden()
    dialog.menu_translucent_check.setChecked(True)
    assert not opacity.isHidden()
    dialog.close()
    app.processEvents()


def test_modern_settings_toggle_dependencies_hide_complete_setting_groups(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)

    def row(key):
        result = dialog.findChild(settings_mod.SettingRow, f"settingRow_{key}")
        assert result is not None
        return result

    island_children = [
        row(key) for key in (
            "dynamic_island_icon", "dynamic_island_name", "dynamic_island_info",
            "dynamic_island_status", "dynamic_island_info_mode",
            "dynamic_island_style", "dynamic_island_opacity",
            "dynamic_island_accent", "dynamic_island_icon_value",
            "dynamic_island_custom_text", "dynamic_island_click_action",
            "dynamic_island_event_effects", "dynamic_island_edge_dock",
        )
    ]
    dialog.island_enabled_check.setChecked(False)
    assert all(child.isHidden() for child in island_children)
    dialog.island_enabled_check.setChecked(True)
    assert not row("dynamic_island_icon_value").isHidden()
    assert row("dynamic_island_custom_text").isHidden()
    dialog.island_icon_check.setChecked(False)
    assert row("dynamic_island_icon_value").isHidden()
    dialog.island_info_check.setChecked(False)
    assert row("dynamic_island_info_mode").isHidden()
    dialog.island_info_mode_select.setCurrentData("custom")
    assert row("dynamic_island_custom_text").isHidden()
    dialog.island_info_check.setChecked(True)
    assert not row("dynamic_island_custom_text").isHidden()

    dialog.close()
    app.processEvents()


def test_windows_proactive_master_and_idle_toggles_hide_dependent_rows(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.sys, "platform", "win32")
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)

    def row(key):
        result = dialog.findChild(settings_mod.SettingRow, f"settingRow_{key}")
        assert result is not None
        return result

    child_keys = (
        "proactive_dry_run", "proactive_preset", "proactive_dwell",
        "proactive_cooldown", "proactive_min_interval", "proactive_daily_cap",
        "proactive_require_idle", "proactive_idle_seconds", "proactive_through",
        "proactive_pre_cue", "proactive_free", "proactive_whitelist",
        "proactive_whitelist_add", "proactive_memory_clear",
    )
    dialog.pro_enabled_check.setChecked(False)
    assert all(row(key).isHidden() for key in child_keys)
    dialog.pro_idle_check.setChecked(False)
    dialog.pro_enabled_check.setChecked(True)
    assert row("proactive_idle_seconds").isHidden()
    assert all(not row(key).isHidden() for key in child_keys if key != "proactive_idle_seconds")
    dialog.pro_idle_check.setChecked(True)
    assert not row("proactive_idle_seconds").isHidden()

    dialog.close()
    app.processEvents()


def test_chat_appearance_options_follow_selected_window_and_persist_independently(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)

    assert [dialog.ai_page.chat_ui_style.itemText(index) for index in range(2)] == [
        "肥鱼版 DeepSeek", "肥鱼牌小手机",
    ]
    assert dialog.ai_page.chat_ui_style.width() >= 180
    window_row = dialog.findChild(settings_mod.SettingRow, "settingRow_chat_ui_style")
    assert "宽屏现代体验" in window_row.hint_label.text()
    assert "紧凑经典体验" in window_row.hint_label.text()
    # 内置主题两种风格都可选（肥鱼版 DeepSeek 与肥鱼牌小手机一致）
    modern_options = [
        dialog.ai_page.background_select.itemText(index)
        for index in range(dialog.ai_page.background_select.count())
    ]
    assert modern_options[0] == "纯色背景"
    assert modern_options[-1] == "自定义图片"
    assert len(modern_options) > 2
    opacity_row = dialog.findChild(settings_mod.SettingRow, "settingRow_chat_background_opacity")
    fill_row = dialog.findChild(settings_mod.SettingRow, "settingRow_chat_background_fill")
    assert opacity_row.isHidden()
    assert fill_row.isHidden()

    dialog.ai_page.chat_ui_style.setCurrentData("classic")
    classic_options = [
        dialog.ai_page.background_select.itemText(index)
        for index in range(dialog.ai_page.background_select.count())
    ]
    assert classic_options[0] == "纯色背景"
    assert classic_options[-1] == "自定义图片"
    assert len(classic_options) > 2
    dialog.ai_page.background_select.setCurrentData("builtin:whale")
    assert not opacity_row.isHidden()
    assert not fill_row.isHidden()
    dialog.ai_page.background_opacity.setValue(68)
    dialog.ai_page.background_fill.setCurrentData("contain")

    dialog.ai_page.chat_ui_style.setCurrentData("modern")
    dialog.ai_page.background_select.setCurrentData("custom")
    modern_background = str((tmp_path / "modern.png").resolve())
    dialog.ai_page.background_picker.setText(modern_background)
    dialog.ai_page.background_opacity.setValue(92)
    dialog.ai_page.background_fill.setCurrentData("stretch")
    dialog._save()

    config.reload()  # #271：写盘经路由视图自己的主配置对象，原对象需 reload 才可见
    assert config.get("chat_background") == "builtin:whale"
    assert config.get("modern_chat_background") == modern_background
    assert config.get("chat_background_opacity") == 68
    assert config.get("chat_background_fill") == "contain"
    assert config.get("modern_chat_background_opacity") == 92
    assert config.get("modern_chat_background_fill") == "stretch"
    dialog.close()
    app.processEvents()


def test_quick_launch_editor_drag_order_and_checked_removal_drive_saved_menu_order(monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod

    app = QApplication.instance() or QApplication([])
    editor = settings_mod.QuickLaunchEditor([
        {"name": "A", "path": "/Applications/A.app", "kind": "application"},
        {"name": "B", "path": "/Applications/B.app", "kind": "application"},
    ])
    moved = editor.list.takeItem(1)
    editor.list.insertItem(0, moved)
    assert [item["name"] for item in editor.apps()] == ["B", "A"]
    editor.list.item(1).setCheckState(Qt.CheckState.Checked)
    editor._remove_checked()
    assert [item["name"] for item in editor.apps()] == ["B"]
    editor.close()
    app.processEvents()


def test_quick_launch_editor_uses_content_sized_rows_and_grouped_add_menu():
    from PySide6.QtWidgets import QApplication, QSizePolicy

    import pet.modern_settings_dialog as settings_mod

    app = QApplication.instance() or QApplication([])
    editor = settings_mod.QuickLaunchEditor([
        {"name": "默认浏览器", "path": "", "kind": "default_browser"},
        {"name": "Finder", "path": "/System/Library/CoreServices/Finder.app", "kind": "application"},
    ])
    editor.resize(760, 300)
    editor.show()
    app.processEvents()

    assert editor.count_label.text() == "2 个快捷项"
    assert editor.add_button.text() == "添加"
    assert [action.text() for action in editor.add_button.popupMenu().actions()] == [
        "选择应用…", "添加默认浏览器",
    ]
    assert editor.list.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert editor.list.height() <= 124
    first_row = editor.list.itemWidget(editor.list.item(0))
    second_row = editor.list.itemWidget(editor.list.item(1))
    assert first_row.name_label.text() == "默认浏览器"
    assert "系统默认" in first_row.detail_label.text()
    assert second_row.name_label.text() == "Finder"
    assert "Finder.app" in second_row.detail_label.text()
    assert editor.empty_label.isHidden()

    editor.close()
    app.processEvents()


def test_quick_launch_editor_collapses_to_a_compact_empty_state_after_last_removal():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod

    app = QApplication.instance() or QApplication([])
    editor = settings_mod.QuickLaunchEditor([
        {"name": "默认浏览器", "path": "", "kind": "default_browser"},
    ])
    editor.show()
    app.processEvents()

    editor.list.item(0).setCheckState(Qt.CheckState.Checked)
    editor._remove_checked()
    app.processEvents()

    assert editor.count_label.text() == "0 个快捷项"
    assert editor.list.isHidden()
    assert not editor.empty_label.isHidden()
    assert editor.empty_label.height() <= 72

    editor.close()
    app.processEvents()


def test_quick_launch_checkbox_can_be_selected_with_a_pointer_click():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod

    app = QApplication.instance() or QApplication([])
    editor = settings_mod.QuickLaunchEditor([
        {"name": "默认浏览器", "path": "", "kind": "default_browser"},
    ])
    editor.resize(520, 140)
    editor.show()
    app.processEvents()

    item = editor.list.item(0)
    row = editor.list.visualItemRect(item)
    QTest.mouseClick(
        editor.list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(row.left() + 14, row.center().y()),
    )
    app.processEvents()

    assert item.checkState() == Qt.CheckState.Checked
    editor.close()
    app.processEvents()


def test_config_defaults_and_normalizes_menu_appearance_and_quick_launch(tmp_path):
    from pet.config import Config

    config = Config(tmp_path)
    appearance = config.get("context_menu_appearance")
    assert {key: appearance[key] for key in ("theme", "density", "corner_radius")} == {
        "theme": "system", "density": "standard", "corner_radius": 12,
    }
    assert config.get("quick_launch_apps") == [
        {"name": "默认浏览器", "path": "", "kind": "default_browser"}
    ]
    config.set("context_menu_appearance", {"theme": "invalid", "density": "spacious", "corner_radius": 99})
    config.set("quick_launch_apps", [{"name": "  Finder  ", "path": "/System/Library/CoreServices/Finder.app"}, {}])
    appearance = config.get("context_menu_appearance")
    assert {key: appearance[key] for key in ("theme", "density", "corner_radius")} == {
        "theme": "system", "density": "spacious", "corner_radius": 18,
    }
    assert config.get("quick_launch_apps") == [
        {"name": "Finder", "path": "/System/Library/CoreServices/Finder.app", "kind": "application"}
    ]


def test_modern_menu_adds_quick_launch_submenu_and_uses_saved_appearance(monkeypatch):
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QMenu

    import pet.modules.quick_launch.menu as quick_launch_mod
    class Config:
        values = {
            "character": "shenshen",
            "on_top": True,
            "context_menu_appearance": {"theme": "dark", "density": "spacious", "corner_radius": 16},
            "quick_launch_apps": [
                {"name": "默认浏览器", "path": "", "kind": "default_browser"},
                {"name": "Finder", "path": "/System/Library/CoreServices/Finder.app", "kind": "application"},
            ],
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    class Pet:
        cfg = Config()
        on_open_chat = on_open_modern_settings = on_spawn_pet = None
        idles = turns = moves = clicks = acts = []
        playback_speed = scale = 1.0
        drag_physics = no_move = False

        def icon_pixmap(self, size=64):
            pixmap = QPixmap(size, size)
            pixmap.fill()
            return pixmap

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    launched = []
    monkeypatch.setattr(quick_launch_mod, "launch_quick_app", lambda app: launched.append(app) or True)
    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    _populate_modern_menu(menu, Pet())
    shortcut = next(action for action in menu.actions() if action.text() == "快捷启动")
    assert shortcut.menu() is not None
    assert [action.text() for action in shortcut.menu().actions()] == ["默认浏览器", "Finder"]
    assert all(not action.icon().isNull() for action in shortcut.menu().actions())
    shortcut.menu().actions()[1].trigger()
    assert launched == [Config.values["quick_launch_apps"][1]]
    assert menu.property("modernTheme") == "dark"
    assert menu.property("modernDensity") == "spacious"
    assert "background-color: rgba(37, 37, 37, 240)" in menu.styleSheet()
    assert "border-radius: 16px" in menu.styleSheet()
    menu.close()
    app.processEvents()


def test_modern_settings_search_locates_rows_and_return_does_not_close(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    dialog.show()
    dialog.search_edit.setFocus()
    dialog.search_edit.setText("API 地址")
    app.processEvents()
    assert dialog.sidebar.currentRow() == 5  # 稳定的“AI 与对话”能力域
    api_row = dialog.findChild(settings_mod.SettingRow, "settingRow_api_url")
    assert api_row.property("searchMatch") is True
    QTest.keyClick(dialog.search_edit, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog.isVisible()
    assert dialog.result() == 0
    dialog.close()
    app.processEvents()


def test_runtime_pet_icon_crops_transparent_canvas_before_scaling():
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    from pet.overlay_shell import _crop_icon_pixmap

    app = QApplication.instance() or QApplication([])
    source = QPixmap(100, 100)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.fillRect(QRect(45, 40, 10, 20), Qt.GlobalColor.blue)
    painter.end()

    icon = _crop_icon_pixmap(source, 32)
    assert max(icon.width(), icon.height()) >= 30
    app.processEvents()


def test_windows_build_regenerates_the_icon_before_pyinstaller():
    build_script = Path("scripts/build_onedir.ps1").read_text(encoding="utf-8")
    make_icon = build_script.index("scripts\\make_icon.py")
    pyinstaller = build_script.index("python -m PyInstaller")
    assert make_icon < pyinstaller
    assert "assets\\big_blue_fat_fish;assets\\big_blue_fat_fish" in build_script
    assert "pet\\menu_templates;pet\\menu_templates" in build_script


def test_modern_animation_leaf_icons_are_loaded_only_when_category_opens(monkeypatch):
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QMenu

    class Config(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class Pet:
        cfg = Config(character="shenshen", on_top=False)
        on_open_chat = on_open_modern_settings = on_spawn_pet = None
        idles = ["idle-a"]
        turns = ["turn-a"]
        moves = ["move-a"]
        clicks = ["click-a"]
        acts = ["act-a"]
        playback_speed = scale = 1.0
        drag_physics = no_move = False

        def __init__(self):
            self.icon_requests = 0

        def animation_icon_image(self, name):
            self.icon_requests += 1
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.blue if name.endswith("a") else Qt.GlobalColor.red)
            return image

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    pet = Pet()
    _populate_modern_menu(menu, pet)
    # Opening the root menu must not synchronously decode every animation.
    assert pet.icon_requests == 0
    animations = next(submenu for submenu in menu._owned_submenus if submenu.title() == "播放动画")
    idle = next(submenu for submenu in animations._owned_submenus if submenu.title() == "待机")
    assert idle.actions() == [], "根菜单构建不应同步填充动画分类动作"
    idle.aboutToShow.emit()
    placeholder_key = idle.actions()[0].icon().cacheKey()
    assert not idle.actions()[0].icon().isNull()
    deadline = time.monotonic() + 1.0
    while (
        (pet.icon_requests < 1 or idle.actions()[0].icon().cacheKey() == placeholder_key)
        and time.monotonic() < deadline
    ):
        app.processEvents()
        time.sleep(0.01)
    assert pet.icon_requests == 1
    assert not idle.actions()[0].icon().isNull()
    assert idle.actions()[0].icon().cacheKey() != placeholder_key
    menu.close()
    app.processEvents()


def test_animation_leaf_icon_crops_transparent_frame_before_filling_slot():
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QBitmap, QPainter, QPixmap, QRegion
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.icons import fitted_pet_pixmap_icon
    from pet.context_menus.menu_styles.modern import apply_modern_menu_style

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    apply_modern_menu_style(menu)
    source = QPixmap(640, 360)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.fillRect(QRect(295, 120, 50, 120), Qt.GlobalColor.blue)
    painter.end()

    rendered = fitted_pet_pixmap_icon(menu, source).pixmap(18, 18)
    bounds = QRegion(QBitmap.fromImage(rendered.toImage().createAlphaMask())).boundingRect()
    assert max(bounds.width(), bounds.height()) >= 16
    app.processEvents()


def test_reopened_animation_menu_reuses_cached_images_immediately():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.shared import build_animation_categories
    from pet.context_menus.menu_styles.modern import apply_modern_menu_style

    class Pet:
        idles = ["idle-a"]
        turns = moves = clicks = acts = []

        def animation_icon_cached_image(self, name):
            assert name == "idle-a"
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.blue)
            return image

        def animation_icon_image(self, _name):
            raise AssertionError("cached thumbnail must not be decoded again")

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    app = QApplication.instance() or QApplication([])
    root = QMenu()
    apply_modern_menu_style(root)
    build_animation_categories(root, Pet(), icons=False, leaf_role_icons=True)
    idle = root._owned_submenus[0]
    assert idle.actions() == [], "根菜单构建不应同步填充动画分类动作"
    idle.aboutToShow.emit()
    assert idle.actions(), "首次展开分类子菜单时应填充动作"
    assert not idle.actions()[0].icon().isNull()
    app.processEvents()


def test_representative_animation_decode_is_shared_across_pets(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from PySide6.QtGui import QImage

    import pet.animation_thumbnail as thumbnail

    path = tmp_path / "shared.webm"
    path.write_bytes(b"fixture")
    thumbnail._image_cache.clear()
    thumbnail._inflight.clear()
    calls = []

    def decode(_path):
        calls.append(1)
        return QImage(8, 8, QImage.Format.Format_ARGB32)

    monkeypatch.setattr(thumbnail, "_decode_representative_frame", decode)
    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(thumbnail.decode_representative_frame, [path] * 4))

    assert len(calls) == 1
    assert all(not image.isNull() for image in images)
    assert thumbnail.decode_representative_frame(tmp_path / "missing.webm").isNull()


def test_long_submenus_enable_qt_scrolling():
    from PySide6.QtWidgets import QApplication, QMenu, QStyle

    from pet.context_menus.menu_styles.common import install_responsive_menu_style

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    for index in range(100):
        menu.addAction(f"动作 {index}")
    install_responsive_menu_style(menu)
    assert menu.style().styleHint(QStyle.StyleHint.SH_Menu_Scrollable, None, menu) == 1
    app.processEvents()


def test_visible_animation_submenu_does_not_relayout_when_thumbnail_finishes():
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.shared import build_animation_categories
    from pet.context_menus.menu_styles.modern import apply_modern_menu_style

    class Pet:
        idles = ["idle-a"]
        turns = moves = clicks = acts = []

        def __init__(self):
            self.cached = {}

        def animation_icon_cached_image(self, name):
            return self.cached.get(name, QImage())

        def animation_icon_image(self, name):
            image = QImage(64, 64, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.blue)
            self.cached[name] = image
            return image

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    app = QApplication.instance() or QApplication([])
    root = QMenu()
    apply_modern_menu_style(root)
    pet = Pet()
    build_animation_categories(root, pet, icons=False, leaf_role_icons=True)
    submenu = root._owned_submenus[0]
    assert submenu.actions() == [], "根菜单构建不应同步填充动画分类动作"
    submenu.aboutToShow.emit()
    placeholder_key = submenu.actions()[0].icon().cacheKey()
    # popup() 在无交互桌面的测试环境中可能不会进入可见状态，
    # 改用 show() 稳定模拟“菜单已展开”，从而覆盖可见时不重排图标的保护逻辑。
    submenu.show()
    deadline = time.monotonic() + 1.0
    while not pet.cached and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert pet.cached
    assert submenu.actions()[0].icon().cacheKey() == placeholder_key
    submenu.hide()
    submenu.aboutToShow.emit()
    assert submenu.actions()[0].icon().cacheKey() != placeholder_key


def test_animation_hover_only_dispatches_bounded_background_work():
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.shared import build_animation_categories
    from pet.context_menus.menu_styles.modern import apply_modern_menu_style

    class Pet:
        idles = turns = moves = clicks = []
        acts = [f"act-{index}" for index in range(80)]

        def animation_icon_cached_image(self, _name):
            return QImage()

        def animation_icon_image(self, _name):
            return QImage()

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    app = QApplication.instance() or QApplication([])
    root = QMenu()
    apply_modern_menu_style(root)
    build_animation_categories(root, Pet(), icons=False, leaf_role_icons=True)
    submenu = root._owned_submenus[0]
    submenu.aboutToShow.emit()
    assert len(submenu._animation_icon_workers) <= 2
    app.processEvents()


def test_representative_animation_frame_uses_the_later_middle():
    from pet.animation_thumbnail import representative_frame_index

    assert representative_frame_index(1) == 0
    assert representative_frame_index(50) == 30
    assert representative_frame_index(100) == 61


def test_modern_menu_exposes_no_template_switch_action():
    """旧版菜单与它的「切换到…菜单」入口一起退役：注册表里不再有该动作。

    原位重开的通用能力（`reopen_context_menu`）由
    ``tests/test_sprite_menu_parity.py::test_open_full_menu_at_rebuilds_menu_at_position``
    覆盖，这里只钉"模板切换项不得复活"。
    """
    from pet.context_menus.registry import ACTION_LABELS, MENU_ACTIONS

    assert "switch_template" not in MENU_ACTIONS.ids
    assert "switch_template" not in ACTION_LABELS
    assert "切换到新版菜单" not in ACTION_LABELS.values()
    assert "切换回旧版菜单" not in ACTION_LABELS.values()


def test_color_picker_uses_stable_painted_swatch_instead_of_border_hack():
    from PySide6.QtWidgets import QApplication

    from pet.modern_settings_dialog import ColorPicker, ColorSwatchButton

    app = QApplication.instance() or QApplication([])
    picker = ColorPicker("#171717")
    assert isinstance(picker.button, ColorSwatchButton)
    assert picker.button.color().name() == "#171717"
    assert "border-left" not in picker.button.styleSheet()
    picker.edit.setText("#eeeeee")
    assert picker.button.color().name() == "#eeeeee"
    picker.close()
    app.processEvents()


def test_product_copy_has_no_external_brand_reference():
    forbidden = ("co" + "dex").lower()
    roots = [Path("pet"), Path("tests"), Path("docs"), Path("README.md")]
    hits = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".py", ".qss", ".md", ".json"}:
                continue
            # Competitive research records source names by design; they are
            # evidence, not user-facing product copy.
            if (
                path.name in {"agent_link.py", "test_agent_link.py"}
                or path.name.endswith("-RESEARCH.md")
                # Contributor/change reports are repository evidence, not
                # user-facing product copy and may mention external brands.
                or path.name.startswith("README-CHANGE-")
                or path.name.startswith("PR-REPORT-")
            ):
                continue
            if forbidden in path.read_text(encoding="utf-8", errors="ignore").lower():
                hits.append(str(path))
    assert hits == []


def test_context_menu_leaf_actions_stay_open_until_focus_is_lost():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.menu_styles.common import install_stay_open_interaction

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    action = menu.addAction("拖动物理")
    action.setCheckable(True)
    install_stay_open_interaction(menu)
    menu.popup(QPoint(30, 30))
    app.processEvents()
    rect = menu.actionGeometry(action)
    pos = rect.center()
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos, menu.mapToGlobal(pos),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(menu, event)
    app.processEvents()
    assert action.isChecked() is True
    assert menu.isVisible() is True
    menu.close()
    app.processEvents()


def test_window_opening_menu_action_uses_native_close_path():
    from PySide6.QtWidgets import QApplication, QMenu

    from pet.context_menus.shared import add_action

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    action = add_action(menu, "桌宠设置", None, lambda: None, close_on_trigger=True)
    assert action.property("closeOnTrigger") is True
    menu.close()
    app.processEvents()


def test_dsh_converged_state_wiring_drives_thinking(tmp_path, monkeypatch):
    """单读方合并后：收敛器状态/真人消息仍打通联动管线。

    回归（原 dsh_state tracker 接线用例的继任者）：DshMonitor 是桥目录唯一
    读方，收敛输出经 ``dsh_state_changed`` / ``dsh_user_message`` 到管理器——
    thinking/真人消息注入 ``notify_dsh_state``、offline 收交互，AppShell 侧只剩
    灵动岛活跃指示（无岛时绝不崩）。
    """
    from PySide6.QtWidgets import QApplication

    from pet.app import AppShell
    from pet.config import Config

    QApplication.instance() or QApplication([])
    owner = AppShell(QApplication.instance(), Config(tmp_path))
    owner._start_modules()
    manager = owner._shared.agent_link
    monitor = manager.monitors["dsh"]
    monitor._running = True  # 仿真活体监视器（迟到信号隔离闸只放活在跑的信号）

    notified: list[str] = []
    dismissed: list[bool] = []
    monkeypatch.setattr(manager, "notify_dsh_state", lambda state: notified.append(state))
    monkeypatch.setattr(manager, "dismiss_all_interactions", lambda: dismissed.append(True))

    try:
        # 收敛信号带发出时的代次（仿真监视器未真启动，_emit_gen 即其当前代次）
        gen = monitor._emit_gen
        # 真人消息 = 对话开始：与状态边沿竞态解耦的稳定触发
        monitor.dsh_user_message.emit("s1", "hi", gen)
        assert notified == ["thinking"]

        # thinking 状态也触发（turn/start 路径）；同轮重复由呈现管线去重
        notified.clear()
        monitor.dsh_state_changed.emit("working", "thinking", "turn/start", gen)
        assert notified == ["thinking"]

        # offline：收掉失效的常驻审批/问题气泡
        monitor.dsh_state_changed.emit("thinking", "offline", "", gen)
        assert dismissed == [True]

        # 非 thinking/offline/等待态不动作
        notified.clear()
        monitor.dsh_state_changed.emit("thinking", "working", "tool/call", gen)
        assert notified == []

        # AppShell 转发口在无岛时必须静默 no-op
        owner._on_dsh_state_changed("working", "thinking")
    finally:
        owner._stop_modules()
        owner._shared.stop_all()


def test_external_character_dirs_uses_variant_then_legacy_fallback(tmp_path, monkeypatch):
    """外部角色目录应优先变体目录，并保留旧 dsh-pet-standalone 目录兜底。"""
    import sys

    import pet.catalog as catalog_mod
    from pet import config as config_mod

    monkeypatch.setattr(config_mod, "APP_DIR_NAME", "dsh-pet-standalone-webm-chat")
    root = tmp_path
    monkeypatch.setenv("APPDATA", str(tmp_path))
    dirs = catalog_mod.external_character_dirs()
    variant = root / "dsh-pet-standalone-webm-chat" / "characters"
    legacy = root / "dsh-pet-standalone" / "characters"
    assert variant in dirs
    assert legacy in dirs
    assert dirs.index(variant) < dirs.index(legacy)  # 新目录优先


def test_external_character_dirs_dedupes_base_dir(tmp_path, monkeypatch):
    """非变体（APP_DIR_NAME == 默认）时旧目录不被重复追加。"""
    import sys

    import pet.catalog as catalog_mod
    from pet import config as config_mod

    monkeypatch.setattr(config_mod, "APP_DIR_NAME", "dsh-pet-standalone")
    root = tmp_path
    monkeypatch.setenv("APPDATA", str(tmp_path))
    dirs = catalog_mod.external_character_dirs()
    base = root / "dsh-pet-standalone" / "characters"
    assert dirs.count(base) == 1
def test_self_talk_deleted_external_dir_falls_back_to_text_not_bundled(tmp_path):
    """回归：用户显式配置的外部图片目录被删后，不再回退内置彩蛋池
    （用户删目录的意图就是不要再看图）。"""
    from pet.overlay_shell import _resolve_self_talk_image_dir

    gone = tmp_path / "deleted_dir"
    assert _resolve_self_talk_image_dir(str(gone)) == ""

    existing = tmp_path / "pics"
    existing.mkdir()
    assert _resolve_self_talk_image_dir(str(existing)) == str(existing)

    # 相对路径（内置 assets）仍走既有回退解析
    assert _resolve_self_talk_image_dir("") == ""
# --- Custom image-directory gallery regression (2026-09-03) ---


def test_image_directory_picker_opens_right_drawer_with_three_column_masonry(tmp_path):
    from PIL import Image
    from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout

    from pet.modern_settings_dialog import ImagePreviewDrawer, ResourcePathPicker

    short = tmp_path / "01-one.png"
    # 名字要够长（卡片文本按宽度截断显示、tooltip 显示全名），但不能长到触发
    # Windows MAX_PATH：tmp_path 本身已有 ~90 字符，*8 的重复拼出 262 字符的
    # 绝对路径，在未开启长路径支持（LongPathsEnabled=0）的 Windows 上
    # Image.save() 直接 FileNotFoundError。*3 仍是长名字，够验证截断与 tooltip。
    long = tmp_path / ("02-" + "very-long-image-name-" * 3 + ".jpg")
    Image.new("RGB", (40, 80), "red").save(short)
    Image.new("RGB", (100, 40), "blue").save(long)
    Image.new("RGB", (80, 80), "green").save(tmp_path / "03-square.png")
    Image.new("RGB", (120, 50), "yellow").save(tmp_path / "04-fourth.png")
    (tmp_path / "ignore.txt").write_text("ignore", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    host = QDialog()
    host.resize(1000, 680)
    layout = QVBoxLayout(host)
    picker = ResourcePathPicker(str(tmp_path), directory=True, image_preview=True, parent=host)
    layout.addWidget(picker)
    host.show()
    app.processEvents()

    assert picker.preview_button.text() == "预览"
    assert host.findChild(ImagePreviewDrawer, "imagePreviewDrawer") is None
    picker.preview_button.click()
    app.processEvents()
    drawer = host.findChild(ImagePreviewDrawer, "imagePreviewDrawer")
    assert drawer is not None and not drawer.isHidden()
    assert drawer.geometry().right() == host.rect().right()
    assert drawer.flow.layout.column_count == 3
    assert drawer.count_label.text() == "4 张图片"
    assert len(drawer.flow.cards) == 4
    assert drawer.flow.cards[1].toolTip() == long.name
    assert drawer.flow.cards[3].y() < drawer.flow.cards[0].geometry().bottom()
    assert drawer.flow.cards[3].x() == drawer.flow.cards[1].x()
    host.close()
    app.processEvents()


def test_cleanup_old_pet_logs(tmp_path):
    """审查 GLM-M2 回归：启动时清理超龄 pet-*.log，不动新日志与其他文件。"""
    import os
    import time

    from pet.app import _cleanup_old_pet_logs

    old = tmp_path / "pet-111.log"
    old.write_text("x", encoding="utf-8")
    old_ts = time.time() - 8 * 86400
    os.utime(old, (old_ts, old_ts))
    old_backup = tmp_path / "pet-111.log.1"
    old_backup.write_text("x", encoding="utf-8")
    os.utime(old_backup, (old_ts, old_ts))
    fresh = tmp_path / "pet-222.log"
    fresh.write_text("y", encoding="utf-8")
    other = tmp_path / "config.json"
    other.write_text("z", encoding="utf-8")
    os.utime(other, (time.time() - 30 * 86400,) * 2)  # 老但非 pet 日志

    assert _cleanup_old_pet_logs(tmp_path) == 2
    assert not old.exists() and not old_backup.exists()
    assert fresh.exists() and other.exists()


def test_modern_settings_reject_saves_config(tmp_path):
    """审查 DS-M9 回归：Esc（reject）路径与 X 一样落盘。"""
    from PySide6.QtWidgets import QApplication

    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    cfg = _slot0_config(tmp_path)
    dlg = settings_mod.ModernSettingsDialog(cfg, include_ai=False)
    dlg.self_talk_image_scale_spin.setValue(180)
    dlg.reject()
    app.processEvents()
    assert _slot0_config(tmp_path).get("self_talk_image_scale") == 180


def test_settings_image_directories_use_preview_but_audio_folders_do_not(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)
    assert dialog.self_talk_image_dir_picker.preview_button is not None
    assert dialog.click_sound_picker.folder_picker.preview_button is None
    dialog.reject()
    app.processEvents()


def test_clear_proactive_memory_reports_failure_truthfully(tmp_path, monkeypatch):
    """清空陪伴记忆失败时不得再报"已清空"（按 clear() 返回值分支）。

    设置页是**独立进程**（`python -m pet --settings`），与主进程后台主动识屏
    写同一份记忆文件；拿不到跨进程锁就是"这次没清"。之前无条件弹"已清空"，
    用户看到的是"清了还在"。
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    import pet.modern_settings_dialog as settings_mod
    import pet.proactive as proactive_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)

    class _RefusingMemory:
        """拿不到锁的 ProactiveMemory 替身（真实失败路径，不是异常）。"""

        def __init__(self, path):
            self.path = path

        def clear(self):
            return False

    monkeypatch.setattr(proactive_mod, "ProactiveMemory", _RefusingMemory)

    shown: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda _p, title, text: shown.append(("info", title, text))))
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda _p, title, text: shown.append(("warn", title, text))))

    dialog._on_pro_clear_memory()

    assert shown, "清空失败必须有用户可见反馈（不能静默）"
    assert all(kind != "info" for kind, _, _ in shown), f"失败仍报了成功：{shown}"
    assert shown[0][0] == "warn", shown
    assert "失败" in shown[0][1], f"标题必须表明失败：{shown[0]}"
    dialog.close()
    app.processEvents()


def test_clear_proactive_memory_reports_success_and_removes_file(tmp_path, monkeypatch):
    """对照组：真清空成功仍报"已清空"，且文件确实被删（返回值不是摆设）。"""
    from PySide6.QtWidgets import QApplication, QMessageBox

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)

    mem_file = config.dir / "proactive_screen_memory.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem_file.write_text(
        json.dumps({"entries": [{"ts": 1.0, "process": "A.exe", "activity": "上网"}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    shown: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda _p, title, text: shown.append(("info", title, text))))
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda _p, title, text: shown.append(("warn", title, text))))

    dialog._on_pro_clear_memory()

    assert [kind for kind, _, _ in shown] == ["info"], shown
    assert not mem_file.exists(), "报了已清空就必须真的删掉文件"
    dialog.close()
    app.processEvents()


def test_clear_proactive_memory_reports_failure_when_probe_fails(tmp_path, monkeypatch):
    """探测失败（stat 报 EACCES/EIO/WinError）时设置页必须走既有的**失败分支**。

    这条走**真实** `ProactiveMemory`（不是替身）：`clear()` 内部的存在性探测抛错。
    以前异常从 `_on_pro_clear_memory` 直接穿出去——用户既没看到"已清空"也没看到
    "清空失败"，只有一个异常；`clear()` 现在返回 False，走 `cleared is False`
    分支弹警告，记忆文件一个字节都不动。
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)

    mem_file = config.dir / "proactive_screen_memory.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem_file.write_text(
        json.dumps({"entries": [{"ts": 1.0, "process": "A.exe", "activity": "上网"}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    before = mem_file.read_bytes()

    real_stat = Path.stat
    targets = {mem_file, mem_file.resolve()}

    def denied_probe(self, *args, **kwargs):
        # 只让记忆文件的探测失败（EACCES/WinError 5 这类 is_file 会原样上抛的错误）
        if Path(self) in targets:
            raise OSError(5, "Access is denied", None, 5)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied_probe)

    shown: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda _p, title, text: shown.append(("info", title, text))))
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda _p, title, text: shown.append(("warn", title, text))))

    dialog._on_pro_clear_memory()

    assert shown, "清空失败必须有用户可见反馈（探测失败也不许静默）"
    assert all(kind != "info" for kind, _, _ in shown), f"失败仍报了成功：{shown}"
    assert shown[0][0] == "warn" and "失败" in shown[0][1], shown
    assert mem_file.read_bytes() == before, "报失败时记忆文件不得被动过"
    dialog.close()
    app.processEvents()
