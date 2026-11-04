import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from pet.config import APP_DIR_NAME
from pet import pet_profiles as profiles

app = QApplication.instance() or QApplication([])


















def test_no_tray_recovery_button_is_visible_and_restores(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon, QPushButton
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    directory = tmp_path / APP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'config.json').write_text(json.dumps({"version": 4}), encoding='utf8')
    broken = profiles.slot_profile_path(directory, 0)
    broken.write_bytes(b'{broken')
    from pet.config import Config
    from pet.overlay_shell import OverlayShell
    from tests.test_overlay_window_capabilities import CapInstance, FakeScreen
    shell = OverlayShell(app, CapInstance(Config(base=tmp_path, instance_id='')),
        screen=FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040)))
    assert shell.sprite is None
    assert shell._recovery_window.isVisible()
    broken.write_text(json.dumps({"version": 4, "character": "nova"}), encoding='utf8')
    button = next(b for b in shell._recovery_window.findChildren(QPushButton) if '生成' in b.text())
    button.click()
    assert shell.sprite is not None
    shell._recovery_window.close()


def test_migration_statuses_separate_slot_only_from_global(tmp_path):
    """ops D2：迁移失败按**结果类型**处置——单槽损坏可降级，其它一律不许吞。

    "一份 slot0 档案坏了"与"全局配置读不出来 / 备份失败 / 锁超时"是两种事故：
    前者只牵连那一个槽（保留原文件、该槽空着，用户显式动作再恢复），后者涉及全局面
    或迁移基础设施，必须照旧硬失败。把两者都当"异常"一起吞掉，等于用不可信的全局配置
    继续跑。
    """
    slot_only = profiles.Slot0Migration(status="target-corrupt")
    assert slot_only.ok is False and slot_only.slot_only_problem is True
    for status in ("source-corrupt", "source-unreadable", "refused-slot-source",
                   "backup-invalid", "backup-failed", "write-failed", "lock-timeout"):
        migration = profiles.Slot0Migration(status=status)
        assert migration.ok is False
        assert migration.slot_only_problem is False, status


def test_corrupt_slot0_profile_is_reported_as_target_corrupt(tmp_path):
    """真生产者：坏 slot0 档案 → ``target-corrupt``（带路径），不覆盖、不清源。"""
    from pet.config import Config

    cfg = Config(base=tmp_path, instance_id='')
    cfg.dir.mkdir(parents=True, exist_ok=True)
    (cfg.dir / 'config.json').write_text(json.dumps({"version": 4, "scale": 0.8}), encoding='utf8')
    broken = cfg.dir / profiles.slot_profile_path(cfg.dir, 0).name
    broken.write_bytes(b'{ "scale": 0.8, broken')
    before = broken.read_bytes()

    migration = profiles.migrate_slot0_profile(cfg.dir)

    assert migration.status == 'target-corrupt'
    assert migration.slot_only_problem is True
    assert migration.profile_path == broken
    assert broken.read_bytes() == before


def test_corrupt_slot0_profile_does_not_break_the_overlay_shell(tmp_path):
    """ops D2（真壳）：坏 slot0 档案不许让整个 overlay 壳起不来。

    只降级这一个身份：主 sprite 不复活、原文件一个字节不动、活跃集合文件
    不被启动期读取或改写（多宠已删除，该文件只剩历史痕迹）。
    """
    from pet.config import Config
    from pet.overlay_shell import OverlayShell
    from tests.test_overlay_window_capabilities import CapInstance, FakeScreen

    directory = tmp_path / APP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'config.json').write_text(json.dumps({"version": 4}), encoding='utf8')
    broken = directory / profiles.slot_profile_path(directory, 0).name
    broken.write_bytes(b'{broken')
    before_broken = broken.read_bytes()
    active_path = directory / 'overlay-active-pets.json'
    active_path.write_text(json.dumps({'version': 2, 'slots': [0, 1]}), encoding='utf8')
    before_active = active_path.read_bytes()

    shell = OverlayShell(
        app, CapInstance(Config(base=tmp_path, instance_id='')),
        screen=FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040)))
    try:
        assert shell.sprite is None, '坏档案的那个槽先空着'
    finally:
        shell.stop()

    assert broken.read_bytes() == before_broken, '坏档案一个字节都不许动（不自动修复）'
    assert active_path.read_bytes() == before_active, '启动不读不写活跃集合文件'


def test_corrupt_slot0_profile_degrades_the_app_shell_with_a_visible_path(tmp_path):
    """ops D2（真 AppShell）：以前这里直接 raise，现在降级并给出**含路径**的诊断。"""
    from pet.app import AppShell
    from pet.config import Config

    cfg = Config(base=tmp_path, instance_id='')
    directory = cfg.dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'config.json').write_text(json.dumps({
        "version": 4, "scale": 0.8, "character": "nova", "pet_opacity": 55,
    }), encoding='utf8')
    broken = directory / profiles.slot_profile_path(directory, 0).name
    broken.write_bytes(b'{broken')
    before_broken = broken.read_bytes()

    shell = AppShell(app, cfg, enable_chat=False)     # 旧行为：RuntimeError
    try:
        assert shell._slot0_profile_unusable is True
        assert shell.slot0_profile_diagnosis(), '降级必须有诊断'
        assert str(broken) in shell.slot0_profile_diagnosis(), '诊断必须点名文件路径'
    finally:
        shell._shared.stop_all()

    assert broken.read_bytes() == before_broken, '坏档案一个字节都不许动'


def _corrupt_slot0_app(tmp_path):
    """真 AppShell + 坏 slot0 档案（只断言诊断口径时用）。"""
    from pet.config import Config

    cfg = Config(base=tmp_path, instance_id='')
    directory = cfg.dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'config.json').write_text(json.dumps({"version": 4}), encoding='utf8')
    broken = profiles.slot_profile_path(directory, 0)
    broken.write_bytes(b'{broken')
    return cfg, broken


def test_overlay_diagnosis_points_at_in_place_restore(tmp_path, monkeypatch):
    """overlay：修好档案 → 点「生成 / 恢复 slot0」**免重启**恢复（实机已验证）。

    旧文案两个拓扑共用一句"修好该文件后重启即可恢复"，overlay 用户读日志会以为
    必须重启（实测发现，见 .scratch/product-close-approved-gui-20261011/REPORT.md
    §4.4）。这条把 overlay 的口径钉住。
    """
    from pet.app import AppShell

    cfg, broken = _corrupt_slot0_app(tmp_path)
    shell = AppShell(app, cfg, enable_chat=False)
    try:
        diagnosis = shell.slot0_profile_diagnosis()
        assert str(broken) in diagnosis
        assert '生成 / 恢复 slot0' in diagnosis, diagnosis
        assert '重启即可恢复' not in diagnosis, (
            'overlay 免重启即可原地恢复，不许只写"重启"：%s' % diagnosis)
    finally:
        shell._shared.stop_all()






# ---------------------------------------------------------------- ops D2-新（2026-10-10 终审复核）
def _broken_slot0_shell(base):
    """真 OverlayShell + 坏 ``config-slot-0.json``（原文件保留）。"""
    from pet.config import Config
    from pet.overlay_shell import OverlayShell
    from tests.test_overlay_window_capabilities import CapInstance, FakeScreen

    directory = base / APP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'config.json').write_text(json.dumps({"version": 4}), encoding='utf8')
    broken = profiles.slot_profile_path(directory, 0)
    broken.write_bytes(b'{broken')
    shell = OverlayShell(
        app, CapInstance(Config(base=base, instance_id='')),
        screen=FakeScreen((0, 0, 1920, 1080), (0, 0, 1920, 1040)))
    return shell, directory, broken




def test_spawn_failure_reaches_the_recovery_window_when_no_pet_is_visible(tmp_path):
    """无宠时冒不出泡：同一份带路径的说明必须落到**可见恢复窗**，并留修复入口。

    无宠期（刚关掉最后一只 / 全隐藏）气泡没有落点，反馈只剩日志就等于又回到静默。
    恢复窗此时是唯一的可见入口，故失败说明要写进它，并且「打开配置目录」这条
    "去修档案"的入口必须在（本批次不做自动修复，只给路）。
    """
    from PySide6.QtWidgets import QPushButton

    shell, directory, broken = _broken_slot0_shell(tmp_path)
    try:
        assert shell.sprite is None

        shell.restore_slot0()

        window = getattr(shell, '_recovery_window', None)
        assert window is not None, '无宠失败必须给出可见恢复窗'
        assert window.isVisible(), '恢复窗必须真的显示出来（不是建了不 show）'
        label = getattr(shell, '_recovery_diagnosis_label', None)
        assert label is not None and str(broken) in label.text(), '说明必须带档案路径'
        buttons = [b.text() for b in window.findChildren(QPushButton)]
        assert any('配置目录' in text for text in buttons), (
            '必须给出"去打开配置目录修档案"的入口：%s' % buttons)
        assert any('设置' in text for text in buttons), '保留该槽设置入口'
    finally:
        window = getattr(shell, '_recovery_window', None)
        if window is not None:
            window.close()
        shell.stop()


