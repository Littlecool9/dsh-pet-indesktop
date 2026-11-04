# -*- coding: utf-8 -*-
"""帧驱动位移（防打滑）回归：窗口平移速度锁到步态整圈，位置由解码帧号推进。

覆盖：
- quantize_move：位移量化为整圈步幅（四舍五入 / 最少 1 圈 / 越界递减 /
  单圈仍越界时夹到 room）；
- move_position_at_frame：帧进度线性插值、夹 [0,1]、第 0 帧即出发、
  末帧提交终点；
- curve_progress_at_time：墙钟折等效帧号的曲线进度；
- MovieLibrary.move_strides / move_curves：sidecar 加载与校验。

旧 PetWindow 的帧驱动位移 / 亚帧补点已随 pet/window.py 删除；sprite 版
（BehaviorController 移动计划与 PetSprite 曲线）由 tests/test_sprite_behavior.py
与 tests/test_sprite_physics.py 覆盖，本文件不再构造窗口。
"""
from __future__ import annotations

import json

import pytest

from pet import catalog
from pet.movement import (
    curve_progress_at_time,
    move_position_at_frame,
    quantize_move,
)

MOVE = catalog.MOVES[0]  # 螃蟹走路

# ============================================================================
# quantize_move（纯函数）
# ============================================================================


def test_quantize_rounds_to_whole_loops():
    loops, dist, dur = quantize_move(150, 100, 1000, 2.0)
    assert (loops, dist, dur) == (2, 200.0, 4.0)  # round(1.5) = 2 圈


def test_quantize_minimum_one_loop():
    loops, dist, dur = quantize_move(10, 100, 1000, 2.0)
    assert (loops, dist, dur) == (1, 100.0, 2.0)  # round(0.1) → 0 → 最少 1 圈


def test_quantize_decrements_when_exceeding_room():
    # round(240/100)=2 圈 = 200px > room 150 → 递减到 1 圈
    loops, dist, dur = quantize_move(240, 100, 150, 2.0)
    assert (loops, dist, dur) == (1, 100.0, 2.0)


def test_quantize_single_loop_clamped_to_room():
    # 1 圈 = 120px 仍超 room 90：不能再减（最少 1 圈），位移夹到 room
    loops, dist, dur = quantize_move(60, 120, 90, 2.0)
    assert loops == 1 and dist == 90.0 and dur == 2.0


# ============================================================================
# move_position_at_frame（纯函数）
# ============================================================================

PLAN = {'start_x': 0, 'target_x': 300, 'start_y': 100, 'target_y': 160,
        'total_frames': 30}


def test_position_linear_in_frames_no_freeze():
    assert move_position_at_frame(PLAN, 0) == (0, 100)  # 第 0 帧即从起点出发
    assert move_position_at_frame(PLAN, 15) == (150.0, 130.0)
    assert move_position_at_frame(PLAN, 30) == (300.0, 160.0)


def test_position_clamped_to_plan():
    assert move_position_at_frame(PLAN, -5) == (0, 100)
    assert move_position_at_frame(PLAN, 999) == (300.0, 160.0)


# 圈内逐帧位移曲线：curve[i] = 播到源帧 i 时圈内累计进度（0..1 单调不减）。
# 静帧段曲线走平 → 窗口不动；动帧段线性 → 匀速。无 curve 键时回退线性插值。
CURVE_PLAN = {'start_x': 0, 'target_x': 200, 'start_y': 100, 'target_y': 100,
              'loops': 1, 'frames_per_loop': 10, 'total_frames': 10,
              'curve': [0.0, 0.0, 0.25, 0.5, 0.5, 0.5, 0.75, 1.0, 1.0, 1.0]}


def test_position_curve_pauses_on_still_frames():
    # 帧 3→4→5 曲线走平（0.5）：窗口必须原地停住，不得继续滑
    assert move_position_at_frame(CURVE_PLAN, 3) == (100.0, 100)
    assert move_position_at_frame(CURVE_PLAN, 4) == (100.0, 100)
    assert move_position_at_frame(CURVE_PLAN, 5) == (100.0, 100)
    # 帧 0 静止起步、末帧到达终点
    assert move_position_at_frame(CURVE_PLAN, 0) == (0, 100)
    assert move_position_at_frame(CURVE_PLAN, 10) == (200.0, 100)


def test_position_curve_multi_loop():
    plan = dict(CURVE_PLAN, loops=2, total_frames=20)
    # 第二圈帧 2：progress = (1 + 0.25) / 2
    assert move_position_at_frame(plan, 12)[0] == pytest.approx(125.0)
    assert move_position_at_frame(plan, 20)[0] == pytest.approx(200.0)


def test_position_curve_monotonic():
    prev = -1.0
    for f in range(0, 11):
        x = move_position_at_frame(CURVE_PLAN, f)[0]
        assert x >= prev
        prev = x


# ============================================================================
# curve_progress_at_time（纯函数，F3：墙钟 → 曲线进度）
# ============================================================================


def test_curve_progress_holds_on_still_segment():
    """静帧段（曲线走平）墙钟推进但进度必须停在 0。"""
    # 4 帧静止起步 + 6 帧匀速推进，单圈 2.0s → 每帧 0.2s
    curve = [0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0]
    assert curve_progress_at_time(curve, 10, 1, 0.0, 2.0) == 0.0
    assert curve_progress_at_time(curve, 10, 1, 0.6, 2.0) == 0.0   # 帧 3：仍在静帧段
    assert curve_progress_at_time(curve, 10, 1, 1.2, 2.0) == pytest.approx(0.5)
    assert curve_progress_at_time(curve, 10, 1, 2.0, 2.0) == 1.0


def test_curve_progress_multi_loop_and_clamp():
    """多圈：进度 = (已完成圈数 + 圈内曲线值) / 总圈数；越界输入夹到 [0,1]。"""
    curve = [0.0, 0.25, 0.5, 1.0]
    assert curve_progress_at_time(curve, 4, 2, 0.5, 1.0) == pytest.approx(0.25)
    assert curve_progress_at_time(curve, 4, 2, 1.0, 1.0) == pytest.approx(0.5)
    assert curve_progress_at_time(curve, 4, 2, 2.0, 1.0) == 1.0    # 末圈末帧
    assert curve_progress_at_time(curve, 4, 2, 99.0, 1.0) == 1.0   # 超时夹 1
    assert curve_progress_at_time(curve, 4, 2, -1.0, 1.0) == 0.0   # 负时间夹 0


def test_curve_progress_matches_move_position_at_frame():
    """单一事实来源：进度必须与 move_position_at_frame 的曲线插值逐点一致。"""
    curve = [0.0, 0.0, 0.25, 0.5, 0.5, 0.5, 0.75, 1.0, 1.0, 1.0]
    plan = {'start_x': 0, 'target_x': 1, 'start_y': 0, 'target_y': 0,
            'loops': 1, 'frames_per_loop': 10, 'total_frames': 10, 'curve': curve}
    for frames in (0.0, 2.5, 3.0, 4.7, 7.0, 9.9, 10.0):
        expected = move_position_at_frame(plan, frames)[0]
        got = curve_progress_at_time(curve, 10, 1, frames * 0.2, 2.0)
        assert got == pytest.approx(expected)


def test_curve_progress_degrades_safely_on_empty_inputs():
    """防御：无曲线走线性；零圈长（meta 未就绪）返回收口值，绝不除零。"""
    assert curve_progress_at_time([], 10, 1, 1.0, 2.0) == pytest.approx(0.5)
    assert curve_progress_at_time([], 10, 2, 4.0, 2.0) == pytest.approx(1.0)
    assert curve_progress_at_time([0.0, 1.0], 2, 1, 1.0, 0.0) == 1.0


# ============================================================================
# MovieLibrary.move_strides sidecar
# ============================================================================


def _lib_on_dir(tmp_path):
    from pet.library import MovieLibrary

    lib = MovieLibrary.__new__(MovieLibrary)
    lib._asset_dir = tmp_path
    return lib


def test_move_strides_loaded_numeric_only(tmp_path):
    (tmp_path / 'move_strides.json').write_text(json.dumps(
        {'_comment': '备注字段必须被忽略', '螃蟹走路': 90, 'bad': 'x', 'flag': True},
        ensure_ascii=False), encoding='utf-8')
    assert _lib_on_dir(tmp_path)._load_move_strides() == {'螃蟹走路': 90.0}


def test_move_strides_missing_file_returns_empty(tmp_path):
    assert _lib_on_dir(tmp_path)._load_move_strides() == {}


def test_move_strides_unparseable_returns_empty(tmp_path):
    (tmp_path / 'move_strides.json').write_text('{oops', encoding='utf-8')
    assert _lib_on_dir(tmp_path)._load_move_strides() == {}


def test_move_strides_object_value_stride(tmp_path):
    """对象值 {'stride': N, 'curve': [...]} 的步幅同样进 move_strides。"""
    (tmp_path / 'move_strides.json').write_text(json.dumps(
        {'螃蟹走路': {'stride': 220, 'curve': [0.0, 0.5, 1.0]}, '漂浮踏步': 90},
        ensure_ascii=False), encoding='utf-8')
    assert _lib_on_dir(tmp_path)._load_move_strides() == {'螃蟹走路': 220.0, '漂浮踏步': 90.0}


# ============================================================================
# MovieLibrary.move_curves sidecar（圈内逐帧位移曲线）
# ============================================================================


def test_move_curves_loaded_from_object_values(tmp_path):
    (tmp_path / 'move_strides.json').write_text(json.dumps(
        {'螃蟹走路': {'stride': 220, 'curve': [0.0, 0.25, 0.5, 0.5, 1.0]},
         '漂浮踏步': 90,  # 纯数值项：无曲线
         '左转奔跑': {'stride': 240}},  # 无 curve 键：无曲线
        ensure_ascii=False), encoding='utf-8')
    lib = _lib_on_dir(tmp_path)
    assert lib._load_move_curves() == {'螃蟹走路': [0.0, 0.25, 0.5, 0.5, 1.0]}


@pytest.mark.parametrize('curve', [
    [0.5, 1.0],            # 不从 0 开始
    [0.0, 0.9],            # 不以 1 结束
    [0.0, 0.8, 0.5, 1.0],  # 非单调（回退）
    [1.0],                 # 太短
    [0.0, 'x', 1.0],       # 非数值
    'not-a-list',          # 不是列表
])
def test_move_curves_rejects_invalid(tmp_path, curve):
    (tmp_path / 'move_strides.json').write_text(json.dumps(
        {'螃蟹走路': {'stride': 220, 'curve': curve}},
        ensure_ascii=False), encoding='utf-8')
    assert _lib_on_dir(tmp_path)._load_move_curves() == {}


def test_move_curves_missing_file_returns_empty(tmp_path):
    assert _lib_on_dir(tmp_path)._load_move_curves() == {}


def test_shenshen_move_curves_cover_move_clips():
    """shenshen 角色包：每个移动动画都必须带逐帧位移曲线（动帧才动）。"""
    from pet.library import MovieLibrary

    lib = MovieLibrary(character_id='shenshen')
    for name in catalog.MOVES:
        lib.movie(name).warm_meta()  # 显式预热（生产由后台预热链完成；
        # GUI 隐式探测已禁止——见 tests/test_meta_no_gui_probe.py）
    for name in catalog.MOVES:
        curve = lib.move_curves.get(name)
        assert curve, f'{name} 缺位移曲线'
        assert curve[0] == 0.0 and curve[-1] == 1.0
        assert len(curve) == lib.frames(name), '曲线必须逐帧对齐素材'


def test_shenshen_move_strides_sidecar_covers_move_clips():
    from pet.library import MovieLibrary

    lib = MovieLibrary(character_id='shenshen')
    for name in catalog.MOVES:
        assert lib.move_strides.get(name, 0) > 0, f'{name} 缺步幅数据'
    assert '_comment' not in lib.move_strides


# ============================================================================
# 复审回归（REVIEW_GLM_BRANCH_2026-09-20）：末帧到位
# ============================================================================


def test_position_linear_reaches_target_on_last_frame():
    # 帧号 0-based：末拍 frames_elapsed == total_frames-1，到位必须提交终点
    # （无 curve 角色此前停在离目标 ~stride/frames 处）
    assert move_position_at_frame(PLAN, PLAN['total_frames'] - 1) == (300.0, 160.0)
