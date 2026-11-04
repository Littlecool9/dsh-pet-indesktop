# -*- coding: utf-8 -*-
"""开机自启模块测试（Windows 变体隔离）。"""

from pet import autostart as autostart_mod


class FakeWinreg:
    """极简 winreg 替身：用 dict 模拟 HKCU Run 值，验证变体互不影响。"""

    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    def OpenKey(self, root, subkey, reserved=0, access=0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def _force_win(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(autostart_mod, "winreg", fake)
    return fake


def test_windows_autostart_variants_do_not_affect_each_other(monkeypatch):
    fake = _force_win(monkeypatch)
    monkeypatch.setattr(autostart_mod, "VALUE_NAME", "dsh-pet-standalone-webm")

    assert autostart_mod.enable() is True
    assert "dsh-pet-standalone-webm" in fake.values
    assert autostart_mod.is_enabled() is True

    # 切到 Chat 变体再开启：不应清掉无 Chat 版的自启
    monkeypatch.setattr(autostart_mod, "VALUE_NAME", "dsh-pet-standalone-webm-chat")
    assert autostart_mod.enable() is True
    assert "dsh-pet-standalone-webm" in fake.values
    assert "dsh-pet-standalone-webm-chat" in fake.values

    # 关闭 Chat 版：无 Chat 版必须保留
    assert autostart_mod.disable() is True
    assert "dsh-pet-standalone-webm-chat" not in fake.values
    assert "dsh-pet-standalone-webm" in fake.values

    # is_enabled 只认当前变体自己的值
    assert autostart_mod.is_enabled() is False
    monkeypatch.setattr(autostart_mod, "VALUE_NAME", "dsh-pet-standalone-webm")
    assert autostart_mod.is_enabled() is True


def test_cleanup_stale_entries_removes_only_missing_paths(monkeypatch, tmp_path):
    fake = _force_win(monkeypatch)
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    existing_exe = existing_dir / "dsh-pet.exe"
    existing_exe.write_bytes(b"MZ")
    missing_dir = tmp_path / "deleted"
    missing_exe = missing_dir / "dsh-pet.exe"

    fake.values = {
        "dsh-pet-standalone-webm": (
            f'cmd /c start "" /D "{existing_dir}" "{existing_exe}"'
        ),
        "dsh-pet-standalone-webm-chat": (
            f'cmd /c start "" /D "{missing_dir}" "{missing_exe}"'
        ),
    }

    removed = autostart_mod.cleanup_stale_entries()

    assert removed == 1
    assert "dsh-pet-standalone-webm" in fake.values
    assert "dsh-pet-standalone-webm-chat" not in fake.values


# ---- start-local.bat 的本地数据目录（2026-11-04）---------------------------------
# start-local.bat 把 APPDATA 改到 <仓库>\.local\appdata，配置因此存在仓库里。开机自启若直接
# 跑 pythonw -m pet，会读到 %APPDATA% 下另一份配置——开机起来的桌宠和平时用的不是同一套设置。

def _fake_repo(tmp_path, monkeypatch, *, local_appdata: bool):
    root = tmp_path / "desktop pet"
    root.mkdir()
    (root / "start-local.bat").write_text("@echo off\r\n", encoding="utf-8")
    appdata = root / ".local" / "appdata"
    appdata.mkdir(parents=True)
    monkeypatch.setattr(autostart_mod, "_project_root", lambda: root)
    monkeypatch.setattr(autostart_mod.sys, "frozen", False, raising=False)
    monkeypatch.setenv("APPDATA", str(appdata if local_appdata else tmp_path / "roaming"))
    return root


def test_source_run_from_start_local_autostarts_through_start_local(monkeypatch, tmp_path):
    fake = _force_win(monkeypatch)
    root = _fake_repo(tmp_path, monkeypatch, local_appdata=True)

    assert autostart_mod.enable() is True
    command = fake.values[autostart_mod.VALUE_NAME]
    assert command == f'cmd /c "{root / "start-local.bat"}"'
    assert "-m pet" not in command, "不能绕过 start-local 的数据目录重定向"
    assert autostart_mod._win_command_target_exists(command) is True


def test_plain_source_run_keeps_the_pythonw_command(monkeypatch, tmp_path):
    fake = _force_win(monkeypatch)
    root = _fake_repo(tmp_path, monkeypatch, local_appdata=False)

    assert autostart_mod.enable() is True
    command = fake.values[autostart_mod.VALUE_NAME]
    assert command.startswith(f'cmd /c start "" /D "{root}"')
    assert command.endswith("-m pet")


def test_existing_pythonw_entry_is_upgraded_when_running_from_start_local(monkeypatch, tmp_path):
    fake = _force_win(monkeypatch)
    root = _fake_repo(tmp_path, monkeypatch, local_appdata=True)
    old = f'cmd /c start "" /D "{root}" "C:\py\pythonw.exe" -m pet'
    fake.values[autostart_mod.VALUE_NAME] = old

    assert autostart_mod.is_enabled() is True
    assert fake.values[autostart_mod.VALUE_NAME] == f'cmd /c "{root / "start-local.bat"}"'
