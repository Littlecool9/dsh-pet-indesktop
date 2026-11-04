# -*- coding: utf-8 -*-
"""sprite 点击音效（4.1c）。

音源解析与旧架构同一入口（click_sound.resolve_click_sound_candidates：
用户自定义 click.wav 优先，内置 default 包兜底；配置键
click_sound_enabled / click_sound_pack / click_sound_volume 与设置页一致）。
播放走 click_sound.play_sound（Windows 下 wav 直放 winmm，不拉起
QtMultimedia）。

音量契约（旧契约 window.py:3522/3532-3540，0 = 静音）：

- 点击音效：单击 sprite（点击/拖拽阈值判定路由）→ 音量 = ``click_sound_volume``
  （缺省 0.70），80ms 节流防抖；
- 启用门：点击 = ``click_sound_enabled``，缺省 True；事件发生时与真正
  ``play_sound`` 前各查一次（旧实现门判就在 play 之前），故关掉再打开立即恢复、
  排队中的音效在回调前被关也不发声。

音源口径：``choose_sound`` 现挑——候选列表缓存、随机结果不缓存（设置页对
「自定义文件夹（随机）」的承诺就是随机播放）。

音效失败（无音频设备/后端错误/解析失败）一律静默降级，绝不影响主链路。
"""
from __future__ import annotations

import time
from pathlib import Path

from . import click_sound

_THROTTLE_S = 0.08
#: 候选列表缓存上限（键 = (gate, pack, data_dir)；多 sprite 各自的音效包各占一项）
_PATH_CACHE_LIMIT = 16
#: 音量键的既有缺省（``pet/config.py`` 的 click_sound_volume）
_VOLUME_DEFAULT = 0.70
_DEFAULT_PACK = {"kind": "builtin", "id": "default"}


def _pack_cache_key(pack):
    """音源包 → 可哈希的缓存键（浅拷贝快照；原对象仍原样传给解析入口）。

    pack 是 config 里的 dict（``kind``/``id``/``path`` 三个字符串字段），不能直接
    当字典键；同时也不能持原对象引用当键——原地改 id 会让 ``==`` 拿对象和它自己比、
    判不出变化（``test_pack_id_mutated_in_place_resolves_new_source`` 锁着这条）。
    """
    if isinstance(pack, dict):
        return tuple(sorted((str(key), str(value)) for key, value in pack.items()))
    try:
        hash(pack)
    except TypeError:
        return repr(pack)
    return pack


class SpriteSoundPlayer:
    """点击音效播放器（duck-typed config：get/dir 即可）。

    逐 sprite 取源（B7b）：旧架构每只桌宠是独立进程、各读自己的
    ``config-slot-N.json``（门/音量/音源包都取自己那份），点哪只响哪只的配置。
    本类通过 ``config_for(sprite)`` 把"身份 → 配置面"交给壳解析：
    ``on_click(sprite)`` 在 ``_on_sprite_click(sprite)`` 里带身份调用；拿不到
    身份（裸播放器/脚本直调）时回退构造期的 config，行为与历史一致。
    """

    def __init__(self, config, *, clock=time.monotonic, config_for=None) -> None:
        self._config = config
        self._clock = clock
        self._config_for = config_for
        self._last_play = 0.0
        # 音源按 (gate, pack, data_dir) 缓存候选列表：多 sprite 各自的音效包不同，
        # 单一槽位缓存会让每只宠的每次发声都重新解析一遍。上限很小（宠数量级）。
        self._path_cache: dict = {}
        self._source: object = None  # 兼容旧字段：最近一次解析的 source

    # ---------------------------------------------------------------- 内部
    def _cfg_for(self, sprite):
        """解析某只 sprite 的配置面（None = 用构造期 config）。"""
        if sprite is None or self._config_for is None:
            return self._config
        try:
            return self._config_for(sprite) or self._config
        except Exception:
            return self._config

    def _config_volume(self, key: str, cfg=None) -> float:
        """读一个音量键（0~1）：不得把 0.0 当缺省回退，读不到则按 config 口径回落。

        0.0 是合法用户值（设置页 0~100%，0% = 静音）；不可解析的值走
        ``pet/config.py::_float_or_default`` 同口径的缺省回落（本读取在点击
        listener 链上，异常会掀掉整条链路）。每次发声现读，故改完即生效。
        """
        try:
            value = float((self._config if cfg is None else cfg).get(key, _VOLUME_DEFAULT))
        except (TypeError, ValueError, OverflowError):
            return _VOLUME_DEFAULT
        return max(0.0, min(1.0, value))

    def _enabled(self, key: str, cfg=None) -> bool:
        """音效启用门（旧契约 window.py:770-783，缺省 True）。

        事件发生时与真正播放前各查一次、不缓存——开关关掉再打开必须立刻恢复
        （缓存把禁用记住会让"关过就再也不响"）。
        """
        return bool((self._config if cfg is None else cfg).get(key, True))

    def _resolve_path(self, gate: str, cfg=None) -> Path | None:
        """按 gate 解析本次要播的音源（不含启用门；门由 ``_play`` 各查一次）。

        点击门用 ``choose_sound`` **现挑**——候选列表缓存、随机结果不缓存。
        旧契约是"点击固定取第一个"，而设置页对「自定义文件夹（随机）」的承诺就是
        随机播放；两者打架时以用户可见文案为准（issue #308：9 个文件的目录永远只
        播文件名排序第一那个，整个进程内不变）。

        音效包/数据目录变化即重新解析：旧实现要求"切换音效包时不能复用上一次
        的旧源"（window.py:3245），缓存会把旧音源与解析失败一起钉死。
        缓存键存 pack 的**浅拷贝快照**而非原对象：pack 是 config 里的原对象，
        键持同一引用时原地改 id/path 会让 ``==`` 拿对象和它自己比、判不出变化。
        浅拷贝足够——pack 是平面配置（``config._clean_click_sound_pack`` 只产
        kind/id/path 三个字符串字段，``click_sound.py:871-873`` 也只读这三个）；
        解析入口仍传原 pack。

        B7b：``cfg`` = 该 sprite 自己的配置面（音效包也可以逐只不同）。
        """
        source = self._config if cfg is None else cfg
        pack = source.get("click_sound_pack", None) or _DEFAULT_PACK
        data_dir = getattr(source, "dir", None)
        if data_dir is None:
            data_dir = getattr(self._config, "dir", None)
        candidates = self._candidates(gate, pack, data_dir)
        return click_sound.choose_sound(candidates) if candidates else None

    def _candidates(self, gate: str, pack, data_dir) -> list:
        """候选列表（按 (gate, pack, data_dir) 缓存）：解析失败 = 空表，静默降级。"""
        key = (gate, _pack_cache_key(pack), data_dir)
        cached = self._path_cache.get(key)
        if cached is not None:
            return cached
        self._source = key
        try:
            paths = list(click_sound.resolve_click_sound_candidates(pack, data_dir))
        except Exception:
            paths = []     # 解析失败 = 无音效，静默降级
        if len(self._path_cache) >= _PATH_CACHE_LIMIT:
            self._path_cache.clear()
        self._path_cache[key] = paths
        return paths

    def _play(self, volume: float, gate: str, cfg=None) -> None:
        if not self._enabled(gate, cfg):
            return
        now = self._clock()
        if now - self._last_play < _THROTTLE_S:
            return
        path = self._resolve_path(gate, cfg)
        if path is None:
            return
        self._last_play = now
        self._submit(path, volume, gate, cfg)

    def _submit(self, path: Path, volume: float, gate: str, cfg=None) -> None:
        """提交播放：把 ``play_sound`` 推迟到下一轮事件循环再调。

        ``play_sound`` 是同步阻塞（winmm 首播 ~157ms / 其后 ~62ms），在 GUI 链上
        直调会卡住这一拍。``QTimer.singleShot(0, ...)`` **只是把这次调用延后**到
        下一轮事件循环，并没有把它搬离 GUI 线程——它仍会在事件循环里同步阻塞，故
        这里**不保证任何延时上限、也不保证不卡**（要真不阻塞需要后台播放通道，本
        轮未改 backend）。无 QApplication（纯脚本/测试直调）退化为同步直放。"""
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is not None:
                QTimer.singleShot(0, lambda: self._safe_play(path, volume, gate, cfg))
                return
        except Exception:
            pass
        self._safe_play(path, volume, gate, cfg)

    def _safe_play(self, path: Path, volume: float, gate: str, cfg=None) -> None:
        if not self._enabled(gate, cfg):
            return  # 排队期间该路门被关掉 → 不发声（旧实现门判在 play_sound 之前）
        try:
            click_sound.play_sound(path, volume)
        except Exception:
            pass  # 无音频设备/后端失败：静默降级

    # ---------------------------------------------------------------- 事件入口
    def on_click(self, sprite=None) -> None:
        """单击音效：音量/门取**触发 sprite** 那份配置（旧 window.py:3510 每窗）。

        ``sprite=None`` 且播放器已接 ``config_for``（= 壳在做逐 sprite 路由）时
        **不发声**：overlay 的 ``click_feedback`` 回调不带 sprite 身份，真正的播放
        由壳在紧随其后的 ``_on_sprite_click(sprite)`` 里按被点的那只补上（同一个
        点击分支，两者之间没有 return，所以一次点击只会响一声）。裸播放器
        （无 ``config_for``：测试/脚本直调）行为不变。
        """
        if sprite is None and self._config_for is not None:
            return
        cfg = self._cfg_for(sprite)
        self._play(self._config_volume("click_sound_volume", cfg),
                   "click_sound_enabled", cfg)
