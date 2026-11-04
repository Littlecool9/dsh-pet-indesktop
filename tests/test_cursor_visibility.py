# -*- coding: utf-8 -*-
"""Cursor visibility API adapter tests.

旧 PetWindow 的自动穿透状态机已随 pet/window.py 删除；overlay 版由
tests/test_overlay_window_capabilities.py 的 ``_on_cursor_visibility_changed`` /
``_cursor_restore_pending`` 用例覆盖。本文件只保留 ``pet.vision`` 适配层。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pet import vision


def _ns_shim(real, **overrides):
    """模块命名空间垫片：显式给出的成员覆盖，其余全部转发给真模块。

    用法是 ``monkeypatch.setattr(<被测模块>, 'sys', _ns_shim(sys, platform='nt'))``
    ——只换**被测模块里那个名字的绑定**。若写成 ``setattr(vision.sys, 'platform', …)``，
    改的其实是**全局** sys 模块。
    """
    class _Shim(SimpleNamespace):
        def __getattr__(self, item):
            return getattr(real, item)

    return _Shim(**overrides)


class FakeUser32:
    def __init__(self, flags=0, result=1, error=None):
        self.flags = flags
        self.result = result
        self.error = error
        self.seen_size = None
        self.GetCursorInfo = _FakeFunction(self._get_cursor_info)

    def _get_cursor_info(self, pointer):
        if self.error:
            raise self.error
        self.seen_size = pointer._obj.cbSize
        pointer._obj.flags = self.flags
        return self.result


class _FakeFunction:
    def __init__(self, function):
        self.function = function
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.function(*args)


@pytest.mark.parametrize(
    ('flags', 'expected'),
    [
        (vision.CURSOR_SHOWING, 'SHOWING'),
        (0, 'HIDDEN'),
        (vision.CURSOR_SUPPRESSED, 'SUPPRESSED'),
        (vision.CURSOR_SHOWING | vision.CURSOR_SUPPRESSED, 'SHOWING'),
    ],
)
def test_get_cursor_visibility_maps_flags(monkeypatch, flags, expected):
    monkeypatch.setattr(vision, 'sys', _ns_shim(sys, platform='win32'))
    user32 = FakeUser32(flags=flags)

    assert vision.get_cursor_visibility(user32) == expected
    assert user32.seen_size == vision.ctypes.sizeof(vision._CursorInfo)


@pytest.mark.parametrize('user32', [FakeUser32(result=0), FakeUser32(error=OSError())])
def test_get_cursor_visibility_failures_are_unknown(monkeypatch, user32):
    monkeypatch.setattr(vision, 'sys', _ns_shim(sys, platform='win32'))
    assert vision.get_cursor_visibility(user32) == 'UNKNOWN'
