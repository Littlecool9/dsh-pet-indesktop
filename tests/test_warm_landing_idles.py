# -*- coding: utf-8 -*-
"""飞行期首帧 pin 与预算逐出回归测试。

起飞预热本身（后台 daemon 线程 + ``_ffr_landing_pinned`` 接线）已迁到
sprite 行为控制器，等价覆盖见 tests/test_sprite_physics.py 与
tests/test_flight_bubble_suppression.py。本文件保留 webm_clip 共享首帧预算
的两条纯函数语义：``_ffr_evict`` 复查 pin、``_ffr_touch`` 选型跳过飞行期 pin。
"""
from __future__ import annotations

import threading


def test_ffr_evict_respects_late_pin():
    """_ffr_evict 复查 pin：选型后才打上的 clip 不得清空（两类标志都查）。

    窗口期：_ffr_touch 选型（跳过 pinned）与 _ffr_evict 清空分两处，
    常驻/飞行期 pin 可能落在两者之间——不复查的话"绝不逐出"语义形同虚设。
    """
    import threading
    from pet import webm_clip

    class _Victim:
        def __init__(self, **flags):
            self._first_frame_lock = threading.Lock()
            self._ffr_evict_token = 7
            self._first_image = object()
            for key, value in flags.items():
                setattr(self, key, value)

    for flag in ("_ffr_pinned", "_ffr_landing_pinned"):
        pinned_victim = _Victim(**{flag: True})
        plain_victim = _Victim()
        webm_clip._ffr_evict([(pinned_victim, 7), (plain_victim, 7)])
        assert pinned_victim._first_image is not None, \
            f"被 {flag} 保护的首帧绝不可逐出"
        assert plain_victim._first_image is None, "未 pin 的照常逐出（防回归放水）"


def test_landing_pin_skips_lru_selection(monkeypatch):
    """飞行期 pin 与常驻 pin 同权参与逐出选型：LRU 从头跳过它，逐出下一个。

    突变判别：_ffr_touch 的选型失去落地标志 → 被 pin 的 a 被选中/摘表，
    victims 变成 [a] 且账面错位 → 断言红。
    """
    from pet import webm_clip

    class _Img:
        def width(self):
            return 5

        def height(self):
            return 5

    class _Clip:
        def __init__(self):
            self._first_frame_lock = threading.Lock()
            self._first_image = _Img()
            self._ffr_evict_token = None

    monkeypatch.setattr(webm_clip, "_first_frame_reg", [])
    monkeypatch.setattr(webm_clip, "_first_frame_bytes", 0)
    monkeypatch.setattr(webm_clip, "_first_frame_budget_bytes", 250)

    a, b, c = _Clip(), _Clip(), _Clip()
    a._ffr_landing_pinned = True
    webm_clip._ffr_touch(a, 100)
    webm_clip._ffr_touch(b, 100)
    victims = webm_clip._ffr_touch(c, 100)  # 300 > 250 → a 被跳过，逐出 b
    assert [v for v, _t in victims] == [b]
    assert a._first_image is not None, "被飞行期 pin 的首帧不得进逐出选型"
    assert webm_clip._first_frame_bytes == 200
