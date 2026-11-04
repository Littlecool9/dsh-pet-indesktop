# -*- coding: utf-8 -*-
"""库层回归：pause_warm（隐藏/切角色）必须取消在飞的首帧预热。

窗口层（PetWindow）的动画启动被拒降级语义已随 PetWindow 删除；
其等价覆盖在 sprite 行为控制器（tests/test_sprite_behavior.py）与
tests/test_sprite_physics.py 中。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_library_pause_warm_cancels_inflight_first_frame_warm(app, tmp_path, monkeypatch):
    """P1-2：pause_warm（隐藏/切角色）必须取消在飞的首帧预热。"""
    import pet.library as library_mod

    class CancelTrackingClip:
        def __init__(self, path, parent=None):
            self.path = Path(path)
            self.cancel_calls = 0

        def warm_meta(self):
            pass

        def warm_first_frame(self):
            pass

        def cancel_first_frame_warm(self):
            self.cancel_calls += 1

    monkeypatch.setattr(library_mod, "WebMClip", CancelTrackingClip)
    videos = tmp_path / "videos"
    folders = {
        "idle": ["待机呼吸休闲.webm"],
        "turn": ["东张西望.webm"],
        "move": ["螃蟹走路.webm"],
        "click": ["点击回应 - 开心跃动.webm"],
        "drag": ["被鼠标拖拽悬空反馈.webm"],
        "random": ["写代码.webm"],
    }
    for folder, files in folders.items():
        directory = videos / folder
        directory.mkdir(parents=True)
        for name in files:
            (directory / name).write_bytes(b"fake")
    lib = library_mod.MovieLibrary(asset_dir=videos)

    clips = list(lib._movies.values())
    assert clips, "库构造后应有已创建的 clip"
    assert all(c.cancel_calls == 0 for c in clips)

    lib.pause_warm()
    assert all(c.cancel_calls == 1 for c in clips), \
        "pause_warm 必须取消每个已创建 clip 的在飞首帧预热"
    app.processEvents()
