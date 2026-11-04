# -*- coding: utf-8 -*-
"""D12 设置进程指令通道纯逻辑单测（零 Qt，offscreen 无关）。

覆盖 PHASE4_DESIGN §4 D12 的四条硬约束：
1. 原子写（tmp + os.replace，不留残留 tmp）；
2. 消费即删（读一次即摘除，重放不再执行；再次写入是"新指令"）；
3. 损坏/未知/缺字段/陈旧指令静默跳过（返回 None + 留日志），且同样摘除——
   否则坏文件会被 3s 轮询永远重放；
4. 指令身份：``target`` 为 slot 编号时只对齐该身份，裸指令 = 全局口径。
"""
from __future__ import annotations

import json
import logging

import pytest

from pet import overlay_settings_command as cmd


def _now() -> float:
    return 1_800_000_000.0


# ---------------------------------------------------------------- target 规范（G1b）
def test_target_zero_is_a_valid_slot_identity(tmp_path):
    """``target=0`` 是**合法**身份（slot0 的主宠档案），不是"非法值"。

    旧 ``_normalize_target`` 只认 ``>= 1``：主宠（slot0）的每宠 reset 写指令时被当成
    非法 target **直接拒写**（``write_command`` 返回 False），用户点了却没有任何动静；
    解析侧同样会把它当坏指令跳过。身份空间含 0 之后，这条上界必须跟着放开。
    """
    assert cmd.write_command(tmp_path, cmd.CMD_PROFILE_RESET, target=0, now=_now()) is True
    assert cmd.read_command(tmp_path, now=_now())["target"] == 0
    got = cmd.consume_command(tmp_path, now=_now())
    assert got is not None and got["target"] == 0
    assert not cmd.command_path(tmp_path).exists()


@pytest.mark.parametrize("bad", [-1, True, False, "0", 1.5, "slot-2"])
def test_invalid_targets_are_still_rejected(tmp_path, bad, caplog):
    """放开下界不等于放宽类型：负数/bool/字符串/浮点照旧拒写、拒解析。"""
    assert cmd.write_command(
        tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, target=bad, now=_now()) is False
    cmd.command_path(tmp_path).write_text(json.dumps(
        {"version": 1, "command": cmd.CMD_APPLY_SETTINGS_RESET,
         "issued_at": _now(), "target": bad}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()


def test_profile_reset_command_is_known_and_round_trips(tmp_path):
    """``profile_reset``（本宠 reset 的运行态同步）是一条已知指令，target 带 slot。"""
    assert cmd.CMD_PROFILE_RESET in cmd.KNOWN_COMMANDS
    assert cmd.write_command(tmp_path, cmd.CMD_PROFILE_RESET, target=2, now=_now()) is True

    got = cmd.consume_command(tmp_path, now=_now())

    assert got is not None and got["command"] == cmd.CMD_PROFILE_RESET
    assert got["target"] == 2


# ---------------------------------------------------------------- 写：原子
def test_write_command_is_atomic_and_leaves_no_temp(tmp_path):
    assert cmd.write_command(
        tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, now=_now(), issuer_pid=4242) is True
    path = cmd.command_path(tmp_path)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == cmd.COMMAND_VERSION
    assert data["command"] == cmd.CMD_APPLY_SETTINGS_RESET
    assert data["issued_at"] == _now()
    assert data["issuer_pid"] == 4242
    assert data["target"] is None
    assert list(tmp_path.glob("*.tmp")) == []          # tmp + replace，无残留


def test_write_command_creates_missing_dir(tmp_path):
    target_dir = tmp_path / "config"
    assert cmd.write_command(target_dir, cmd.CMD_APPLY_SETTINGS_RESET, now=_now()) is True
    assert cmd.command_path(target_dir).is_file()


def test_write_command_failure_returns_false(tmp_path):
    """目录位置被文件占住 = 环境错误：返回 False，不抛（调用方留日志）。"""
    blocked = tmp_path / "config"
    blocked.write_text("not a dir", encoding="utf-8")
    assert cmd.write_command(blocked, cmd.CMD_APPLY_SETTINGS_RESET, now=_now()) is False


# ---------------------------------------------------------------- 消费：即删 + 重放
def test_consume_returns_command_and_deletes_file(tmp_path):
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, now=_now())
    got = cmd.consume_command(tmp_path, now=_now())
    assert got is not None
    assert got["command"] == cmd.CMD_APPLY_SETTINGS_RESET
    assert got["target"] is None
    assert not cmd.command_path(tmp_path).exists()     # 消费即删
    assert cmd.consume_command(tmp_path, now=_now()) is None   # 不重放


def test_consume_target_slot_roundtrip(tmp_path):
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, target=2, now=_now())
    got = cmd.consume_command(tmp_path, now=_now())
    assert got["target"] == 2


def test_rewritten_command_after_consume_is_honored(tmp_path):
    """消费后再次写入 = 新指令（用户又点了一次按钮），不是被去重吞掉。"""
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, now=_now())
    assert cmd.consume_command(tmp_path, now=_now()) is not None
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, now=_now())
    assert cmd.consume_command(tmp_path, now=_now()) is not None


def test_read_command_is_non_destructive(tmp_path):
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, now=_now())
    assert cmd.read_command(tmp_path, now=_now()) is not None
    assert cmd.command_path(tmp_path).is_file()        # 诊断读不消费
    assert cmd.read_command(tmp_path, now=_now()) is not None


# ---------------------------------------------------------------- 消费：损坏/未知/陈旧
def test_missing_file_is_silent(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert caplog.records == []                        # 轮询常态：不刷日志


def test_corrupt_command_is_skipped_consumed_and_logged(tmp_path, caplog):
    cmd.command_path(tmp_path).write_text("{ broken", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()     # 坏文件也要摘除（否则轮询重放）
    assert any("损坏" in r.getMessage() for r in caplog.records)


def test_unknown_command_is_skipped_consumed_and_logged(tmp_path, caplog):
    cmd.command_path(tmp_path).write_text(json.dumps(
        {"version": 1, "command": "format_c_drive", "issued_at": _now()}),
        encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()
    assert any("未知" in r.getMessage() for r in caplog.records)


def test_non_object_payload_is_skipped(tmp_path, caplog):
    cmd.command_path(tmp_path).write_text("[1, 2, 3]", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()


def test_version_mismatch_is_skipped(tmp_path, caplog):
    cmd.command_path(tmp_path).write_text(json.dumps(
        {"version": 99, "command": cmd.CMD_APPLY_SETTINGS_RESET, "issued_at": _now()}),
        encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()


def test_stale_command_is_dropped(tmp_path, caplog):
    """桌宠没在跑时写下的指令不允许在下次启动时突然生效。"""
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET,
                      now=_now() - cmd.DEFAULT_MAX_AGE_S - 1.0)
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()
    assert any("陈旧" in r.getMessage() for r in caplog.records)


def test_fresh_command_within_window_is_accepted(tmp_path):
    cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET,
                      now=_now() - cmd.DEFAULT_MAX_AGE_S + 1.0)
    assert cmd.consume_command(tmp_path, now=_now()) is not None


def test_invalid_issued_at_is_skipped(tmp_path, caplog):
    for bad in ({"version": 1, "command": cmd.CMD_APPLY_SETTINGS_RESET},
                {"version": 1, "command": cmd.CMD_APPLY_SETTINGS_RESET,
                 "issued_at": "yesterday"},
                {"version": 1, "command": cmd.CMD_APPLY_SETTINGS_RESET,
                 "issued_at": float("nan")}):
        cmd.command_path(tmp_path).write_text(json.dumps(bad), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert cmd.consume_command(tmp_path, now=_now()) is None
        assert not cmd.command_path(tmp_path).exists()


def test_invalid_target_is_skipped(tmp_path, caplog):
    cmd.command_path(tmp_path).write_text(json.dumps(
        {"version": 1, "command": cmd.CMD_APPLY_SETTINGS_RESET,
         "issued_at": _now(), "target": "slot-2"}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert not cmd.command_path(tmp_path).exists()


def test_unreadable_file_leaves_command_for_retry(tmp_path, monkeypatch, caplog):
    """读失败（权限/锁）时不摘除也不执行：下一轮轮询重试，绝不吞掉用户的点击。"""
    path = cmd.command_path(tmp_path)
    path.write_text("{}", encoding="utf-8")
    real_read = type(path).read_text

    def boom(self, *args, **kwargs):
        if self == path:
            raise OSError("被占用")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", boom)
    with caplog.at_level(logging.WARNING):
        assert cmd.consume_command(tmp_path, now=_now()) is None
    assert path.is_file()


def test_claim_lease_recovers_without_removing_other_pending(tmp_path):
    now = _now()
    assert cmd.write_command(tmp_path, cmd.CMD_PROFILE_RESET, target=1, now=now)
    first = cmd.claim_command(tmp_path, now=now)
    assert cmd.claim_command(tmp_path, now=now + 1) is None
    recovered = cmd.claim_command(tmp_path, now=now + cmd.CLAIM_LEASE_S)
    assert recovered["id"] == first["id"] and recovered["claim"] != first["claim"]


def test_same_slot_reset_does_not_replace_other_command(tmp_path):
    for name in (cmd.CMD_PROFILE_RESET, cmd.CMD_APPLY_SETTINGS_RESET, cmd.CMD_PROFILE_RESET):
        assert cmd.write_command(tmp_path, name, target=1, now=_now())
    assert [cmd.consume_command(tmp_path, now=_now())["command"] for _ in range(3)] == [
        cmd.CMD_PROFILE_RESET, cmd.CMD_APPLY_SETTINGS_RESET, cmd.CMD_PROFILE_RESET]


@pytest.mark.parametrize("raw", [b"\xff", b'{"version":1,"command":[],"issued_at":1}'])
def test_corrupt_encoding_or_command_type_does_not_block_next_write(tmp_path, raw):
    cmd.command_path(tmp_path).write_bytes(raw)
    assert cmd.write_command(tmp_path, cmd.CMD_APPLY_SETTINGS_RESET, target=2, now=_now())
    assert cmd.consume_command(tmp_path, now=_now())["target"] == 2


def test_slot_from_instance_id():
    assert cmd.slot_from_instance_id("slot-3") == 3
    assert cmd.slot_from_instance_id("slot-0") == 0
    assert cmd.slot_from_instance_id("") is None
    assert cmd.slot_from_instance_id(None) is None
    assert cmd.slot_from_instance_id("slot-x") is None
    assert cmd.slot_from_instance_id("3") is None
