# -*- coding: utf-8 -*-
"""
应用入口 —— QApplication + 桌宠窗口 + 系统托盘。

支持运行时切换角色：
- 右键桌宠 →「切换角色」
- 托盘菜单 →「切换角色」
切换后会热加载对应形象的 webm，并保留位置/朝向等配置。

批5.1（纯重构）把原 PetApp 按「进程级 / 每窗」拆成两块，行为逐位不变；
批5.2 spike 扩成多窗集合（AppShell 持有 ``_instances`` 列表，``self.instance``
指主窗 = 列表头，兼容既有调用面）：
- ``AppShell``：进程级服务（托盘、灵动岛、余额、系统通知、
  broker、aboutToQuit 收口），持有 ``PetInstance`` 集合。
- ``PetInstance``：每窗容器（config/lib/win/聊天窗/设置窗/气泡），持 backref
  到 ``AppShell``，窗口级操作都从这里路由，``self.win`` 主窗单窗假设据此收敛。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import weakref
from logging.handlers import RotatingFileHandler
from pathlib import Path

import shiboken6
from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart as autostart_mod
from . import catalog
from . import overlay_instance_gate as overlay_gate_mod
from . import webm_clip as webm_clip_mod
from .config import APP_DIR_NAME, Config, _default_base
from .desktop_notify import DesktopNotification, position_stack
from .library import MovieLibrary
from .runtime_cleanup import cleanup_stale_runtime_dirs
from .session_watcher import install_session_watcher
from .persona_phrases import PhrasePicker


_persona_pickers = weakref.WeakKeyDictionary()

# 存活 AppShell 注册表（测试收口用，与 agent_link._LIVE_AGENT_LINK_MANAGERS
# 同一纪律）。多窗共享子系统与待办服务
# 持有无主 QTimer（`QTimer()` + timeout.connect），其连接从 Qt C++ 侧强引用
# 住整个 shell 对象图，Python 的 gc.collect() 回收不掉；解释器退出时的 GC
# 才最终化这些 Qt 对象 → 原生访问违规（Windows 0xC0000005，崩溃点落在
# "Garbage-collecting / <no Python frame>"）。WeakSet 只弱引用 shell 本身，
# 测试收口时逐对象停表并释放反向引用。
_LIVE_SHELLS: "weakref.WeakSet" = weakref.WeakSet()


def _persona_picker(win):
    """Return an application-owned picker without extending PetWindow state."""
    try:
        picker = _persona_pickers.get(win)
    except (TypeError, RuntimeError):
        picker = None
    if picker is None:
        picker = PhrasePicker()
        try:
            _persona_pickers[win] = picker
        except (TypeError, RuntimeError):
            pass
    return picker


def _persona_text(win, key: str, fallback: str, **values) -> str:
    """Render a configured persona phrase for application-level messages."""
    cfg = getattr(win, "cfg", None)
    if cfg is None:
        return fallback.format(**values)
    mode = str(cfg.get("dialogue_mode", "legacy") or "legacy")
    picker = _persona_picker(win)
    if mode == "custom":
        text = picker.custom(cfg.get("dialogue_phrases", {}), key, fallback, **values)
        # 与内置模式同语义：未命中自定义文案时回退并填充占位符（含 {text} 等）。
        # 此前直接 return 会把未格式化的 fallback 露出字面量 {…}。
        return fallback.format(**values) if text is fallback else text
    # legacy / whale_maid：命中内置 JSON 预设即渲染，未命中回退调用方原文案
    text = picker.get(mode, key, fallback, **values)
    return fallback.format(**values) if text is fallback else text


def _instance_config_identity(instance) -> str:
    """实例的配置身份（"" = 主身份，``slot-N`` = 子宠；slot_manager 同口径）。

    独立设置进程按这个身份选 ``config.json`` / ``config-slot-N.json``，进程内多窗
    下也是"这个设置页属于哪只宠"的判据（``_launch_settings_process`` 与设置页占用
    提示共用一处实现）。
    """
    return str(getattr(getattr(instance, "config", None), "instance_id", "") or "")


class _OverlayChatHost:
    """完整聊天窗的 pet 形宿主：overlay 拓扑没有 PetWindow，用壳拼出它真正读到的面。

    只做转发，不新增机制（``overlay_shell`` 的 ``visible_content_rect`` /
    ``icon_pixmap`` 已是 PetWindow 同契约的 sprite 等价物）：

    - 定位 ``visible_content_rect``（``position_near_pet`` 的正路）；
    - ``frameGeometry`` 兜底（身体框为空时才被读，拿合成窗几何顶替，避免
      AttributeError）；
    - 头像 ``icon_pixmap``（聊天窗标题栏取角色图）；
    - ``add/remove_position_listener``（``chat_follow_pet`` 勾选时聊天窗跟随桌宠，
      转发到合成窗的 sprite 位置监听）。
    """

    __slots__ = ("_shell",)

    def __init__(self, shell) -> None:
        self._shell = shell

    def visible_content_rect(self) -> QRect:
        fn = getattr(self._shell, "visible_content_rect", None)
        return fn() if callable(fn) else QRect()

    def frameGeometry(self) -> QRect:  # noqa: N802 (Qt 命名)
        overlay = getattr(self._shell, "overlay", None)
        return overlay.geometry() if overlay is not None else QRect()

    def icon_pixmap(self, size: int = 64):
        fn = getattr(self._shell, "icon_pixmap", None)
        return fn(size) if callable(fn) else None

    def add_position_listener(self, listener) -> None:
        overlay = getattr(self._shell, "overlay", None)
        sprite = getattr(self._shell, "sprite", None)
        if overlay is not None and sprite is not None and callable(listener):
            overlay.add_position_listener(sprite, listener)

    def remove_position_listener(self, listener) -> None:
        overlay = getattr(self._shell, "overlay", None)
        sprite = getattr(self._shell, "sprite", None)
        if overlay is not None and sprite is not None:
            overlay.remove_position_listener(sprite, listener)


class _EmptyPetHost:
    def __init__(self, shell):
        self.cfg = shell.config
        self.scale = 1.0
        self._speech_bubble = None
        self._bubble_suppressed = False
        self._alert_current = None
        self._sticky_bubble_active = False
        self._physics_mode = None
        self._dragging = False

    def isVisible(self):  # noqa: N802
        return False

    def visible_content_rect(self):
        return QRect()

    def show_bubble(self, *args, **kwargs):
        return False

    def show_alert(self, *args, **kwargs):
        return False

    def resolve_alert(self, *args, **kwargs):
        return None

    def hold_bubble(self, *args):
        return None

    def set_bubble_suppressed(self, suppressed):
        self._bubble_suppressed = bool(suppressed)


# 批5.2 §③.7：多窗日志用 [slot-N] 前缀区分。单进程多窗共享一份日志文件，
# 故用线程本地记录「当前执行的窗」由日志 Filter 加前缀；flag 关（单进程单窗）
# 时前缀为 None，日志格式与现状逐位一致。
_pet_log_slot = threading.local()


class _SlotLogFilter(logging.Filter):
    """按线程本地槽位给日志记录加 [slot-N] 前缀（flag 开/多窗时）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        slot = getattr(_pet_log_slot, "slot", None)
        if slot:
            record.msg = f"[{slot}] {record.msg}"
        return True


def _setup_logging(config: Config) -> None:
    config.dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        str(config.dir / f'pet-{os.getpid()}.log'),  # 多开实例日志按 PID 隔离，避免互相覆盖
        maxBytes=1_000_000, backupCount=2, encoding='utf-8',
    )  # 滚动日志：1MB×2，不再无限增长
    handler.addFilter(_SlotLogFilter())
    logging.basicConfig(
        handlers=[handler],
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        encoding='utf-8',
    )
    _cleanup_old_pet_logs(config.dir)


def _cleanup_old_pet_logs(log_dir, *, max_age_days: float = 7.0) -> int:
    """启动时清理过期的 pet-<pid>.log（含滚动备份 .log.1/.2）。

    每实例每次启动都产生新文件，不清理会无界累积（审查 GLM-M2）。
    只删本变体命名空间下超龄文件；失败静默（清理不影响启动）。
    """
    removed = 0
    try:
        cutoff = time.time() - max_age_days * 86400
        for path in Path(log_dir).glob('pet-*.log*'):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


def _show_startup_error(title: str, message: str) -> None:
    QMessageBox.critical(None, title, message)


def _cleanup_stale_runtime_dirs() -> None:
    """清理 PyInstaller onefile 遗留的 ``_MEI*`` 临时目录。

    只扫描系统临时目录中超过 24 小时的目录，并始终跳过当前进程的
    ``sys._MEIPASS``。删除失败只记录日志，不接管 ACL，也不影响启动。
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    current = Path(meipass).resolve(strict=False)
    result = cleanup_stale_runtime_dirs(current_dir=current)
    for directory in result.removed:
        logging.info("已清理遗留 PyInstaller 缓存目录: %s", directory)
    for directory, error in result.failed.items():
        logging.warning("清理 PyInstaller 缓存目录失败: %s (%s)", directory, error)


class PetInstance:
    """每窗容器 —— config/lib/win/聊天窗/设置窗/气泡与全部窗口级操作。

    批5.1（纯重构）拆自原 PetApp 的「每窗」半边，行为逐位不变，运行时仍
    一进程一窗。持 backref 到所属 ``AppShell``；窗口级逻辑集中于本类后，
    ``self.win`` 单窗假设只有一个归属点，便于批5.2 扩成多窗集合。
    """

    def __init__(self, shell: "AppShell", config: Config,
                 enable_chat: bool = True) -> None:
        self.shell: AppShell = shell
        self.config = config
        self.slot_id = 0
        self.win = None
        self.chat_window = None
        self.legacy_chat_window = None
        self.modern_chat_window = None
        self.chat_settings_dialog = None
        self.modern_settings_dialog = None
        self.quick_chat = None
        self._pending_dialog_opens: set[str] = set()
        # E2（REVIEW_batch51）：enable_chat 单源在 AppShell（进程级），本类只读转发。
        self.enable_chat = bool(enable_chat)

    @property
    def enable_chat(self) -> bool:
        """单源：转发到 AppShell（进程级），批5.2 消除双源漂移（REVIEW_batch51 E2）。

        无 shell（__new__ 测试桩/最小替代）时回退到本地 _enable_chat 兜底。
        """
        shell = getattr(self, "shell", None)
        if shell is not None:
            return shell.enable_chat
        return bool(getattr(self, "_enable_chat", True))

    @enable_chat.setter
    def enable_chat(self, value):
        # P2-4：setter 仅缓存构造值作无 shell 兜底，**从不改写进程级 shell**
        #（只读转发——读取走 getter 的 shell.enable_chat 权威源）。
        self._enable_chat = bool(value)

    # ------------------------------------------------------------ 窗口构建
    def _create_library(self, character_id: str) -> MovieLibrary:
        # 预热策略：默认 balanced（瞬时交互核 pinned 预热首帧，随机动作池
        # 按需解码）。media_prewarm 键保留给高级用户。
        prewarm = str(self.config.get("media_prewarm", "balanced") or "balanced")
        # 首帧缓存全局预算（高级用户可在 config.json 调小，低配机用）；
        # 进程级设置，幂等，切角色重复调用无害。
        webm_clip_mod.set_first_frame_budget(
            int(self.config.get("first_frame_cache_max_mb", 8)) * 1024 * 1024
        )
        lib = MovieLibrary(
            character_id=character_id,
            prewarm_policy=prewarm,
        )
        # UI 就绪后统一调度预热：高优先级立即后台跑（带 0~0.05s 错峰），
        # 随机动作池延迟 2s 补全，避免多开启动时 ffmpeg 进程洪峰。
        lib.schedule_high_priority_warm()
        lib.schedule_low_priority_warm()
        # 首跑帧序列自动供给（B 档）：延迟 5s 后台低优转热集，静默 no-op 兜底
        getattr(lib, 'maybe_provision_frameseq', lambda: None)()
        logging.info('素材加载完成：%s %d 段动画', character_id, len(lib.names()))
        return lib

    # ------------------------------------------------------------ 角色切换
    def sync_chat_character(self, character_id: str) -> None:
        """把新角色同步到**助手线**聊天窗（overlay 主宠切角色后由 sprite 壳调用）。

        完整聊天窗按角色持有会话/头像/系统提示，只换素材库不会更新它——切完角色
        再开口仍是旧角色的上下文。陪伴线（快速气泡 / 岛对话）不在此列：它的角色
        与人设由 SurfCore 持有，不随素材角色切换。

        **先刷新 slot0 读视图，再同步已建面**（F01）：本实例的 ``config`` 是那条
        slot0 路由视图（``SlotRoutedConfig(..., 0)``），它读一次就把档案快照缓存住
        ——而"完整聊天窗构造"读的就是它（``ChatWindow(self.config, self.config.get(
        'character'))``）。刷新只作废只读快照，表单草稿与钉住的编辑代次都不受影响
        （见 ``SlotRoutedConfig.refresh_profile_view``）。
        """
        if not self.enable_chat:
            return
        refresh = getattr(self.config, "refresh_profile_view", None)
        if callable(refresh):
            refresh()
        for chat_window in (self.legacy_chat_window, self.modern_chat_window):
            if chat_window is not None:
                chat_window.switch_character(character_id)
        # 岛对话气泡的角色/历史由 SurfCore 持有，不再随素材角色同步。

    # ------------------------------------------------------------ 聊天窗
    def _chat_host(self):
        """完整聊天窗的宿主：主窗优先；overlay 拓扑退回 sprite 壳的 pet 形适配。

        overlay 拓扑 ``self.win`` 恒为 None（不建 PetWindow），不退回宿主则
        ``open_chat*`` 直接 return → 菜单「AI 对话」与快速气泡「全文见聊天窗」都
        点了没反应（完整聊天窗完全不可达）。
        """
        if self.win is not None:
            return self.win
        shell = getattr(self.shell, "_overlay_shell", None)
        if shell is None:
            return None
        return _OverlayChatHost(shell)

    def open_chat(self) -> None:
        """Open the configured chat UI; menus only need this stable dispatcher."""
        if str(self.config.get("chat_ui_style", "modern")) == "classic":
            self.open_legacy_chat()
        else:
            self.open_modern_chat()

    def open_quick_chat(self) -> None:
        """打开快速对话气泡；与完整聊天窗共用会话历史。"""
        if not self.enable_chat:
            return
        # 桌宠全部隐藏：气泡锚不到桌宠，改弹到灵动岛上（岛是对话代理）。
        # singleShot：Cocoa 菜单跟踪期间延迟到菜单关闭再弹。
        shell = getattr(self, "shell", None)
        if shell is not None and not shell._aggregate_pet_visible()                 and shell._island_chat_available():
            QTimer.singleShot(0, lambda: shell._show_island_chat(activate=True))
            return
        # 气泡锚在 sprite 上——改走 overlay 壳的 sprite 锚定路径（与 sprite
        # 右键菜单同一条），否则岛卡片「聊天」/托盘「快速对话（气泡）」点了没反应。
        overlay = getattr(shell, "_overlay_shell", None) if shell is not None else None
        if overlay is not None:
            QTimer.singleShot(0, overlay.open_quick_chat)

    def open_legacy_chat(self) -> None:
        host = self._chat_host()
        if not self.enable_chat or host is None:
            return
        if self._defer_while_popup_active("legacy-chat", self.open_chat):
            return
        from .chat.legacy_widgets import ChatWindow
        if self.legacy_chat_window is None:
            self.legacy_chat_window = ChatWindow(
                self.config,
                str(self.config.get('character', catalog.DEFAULT_CHARACTER)),
                pet_window=host,
                notifier=self.shell.system_notify,
                auth_callback=self.open_chat_settings,
            )
        else:
            self.legacy_chat_window.set_pet_window(host)
        self.chat_window = self.legacy_chat_window
        self._present_dialog(self.legacy_chat_window, lambda: self.legacy_chat_window.position_near_pet(host))

    def open_modern_chat(self) -> None:
        host = self._chat_host()
        if not self.enable_chat or host is None:
            return
        if self._defer_while_popup_active("modern-chat", self.open_modern_chat):
            return
        from .chat.widgets import ChatWindow
        if self.modern_chat_window is None:
            self.modern_chat_window = ChatWindow(
                self.config,
                str(self.config.get('character', catalog.DEFAULT_CHARACTER)),
                pet_window=host,
                notifier=self.shell.system_notify,
                auth_callback=self.open_chat_settings,
            )
        else:
            self.modern_chat_window.set_pet_window(host)
        self.chat_window = self.modern_chat_window
        self._present_dialog(self.modern_chat_window, lambda: self.modern_chat_window.position_near_pet(host))

    def _defer_while_popup_active(self, key: str, callback) -> bool:
        """Avoid constructing a heavy dialog inside QMenu.exec()."""
        if QApplication.activePopupWidget() is None:
            self._pending_dialog_opens.discard(key)
            return False
        if key in self._pending_dialog_opens:
            return True
        self._pending_dialog_opens.add(key)

        def retry() -> None:
            if QApplication.activePopupWidget() is not None:
                QTimer.singleShot(50, retry)
                return
            self._pending_dialog_opens.discard(key)
            callback()

        QTimer.singleShot(50, retry)
        return True

    def _present_dialog(self, dialog, before_present=None, attempt: int = 0) -> None:
        """延迟呈现非模态窗口，直到任何弹出菜单关闭。

        右键/托盘菜单在原生弹出期间（menu.exec 阻塞期间），
        菜单项动作触发时会话尚未结束，此时新建窗口的 show/raise/activate
        会被系统原生菜单会话抑制——表现为首次点击「AI 设置 / 桌宠设置」无反应，
        需要再点一次（此时窗口实例已存在，直接 show 成功）。
        延迟到菜单关闭后再呈现即可稳定弹出；Qt 自绘菜单（Windows）同样
        覆盖：弹窗仍显示时重试等待。重试 60 次（约 3.6 秒）后放弃，
        防止弹窗长期不消失时无限空转。
        """
        if attempt > 60:
            return
        if QApplication.activePopupWidget() is not None:
            QTimer.singleShot(60, lambda: self._present_dialog(dialog, before_present, attempt + 1))
            return
        if before_present is not None:
            before_present()
        if dialog.isMinimized():
            dialog.showNormal()
        else:
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ------------------------------------------------------------ 设置
    def open_chat_settings(self) -> None:
        """Open settings without blocking the desktop pet window.

        QDialog.exec() makes the dialog application-modal, which prevents the
        user from dragging or interacting with the pet while editing settings.
        Keep one modeless dialog alive instead, and refresh the chat window
        after the dialog reports an accepted save.
        """
        if not self.enable_chat:
            return
        from .chat.settings_dialog import ChatSettingsDialog
        if self.chat_settings_dialog is None:
            dialog = ChatSettingsDialog(self.config, self.chat_window)
            dialog.setModal(False)
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.finished.connect(self._chat_settings_finished)
            self.chat_settings_dialog = dialog
        self._update_bubble_suppression_for_settings()
        self._present_dialog(self.chat_settings_dialog)

    def _chat_settings_finished(self, result: int) -> None:
        dialog = self.chat_settings_dialog
        self.chat_settings_dialog = None
        self._update_bubble_suppression_for_settings()
        if result:
            self._refresh_chat_windows()

    def _refresh_chat_windows(self) -> None:
        """Refresh both independently styled chat windows after shared settings change."""
        for chat_window in (self.legacy_chat_window, self.modern_chat_window):
            if chat_window is not None:
                chat_window.refresh_settings()

    def _update_bubble_suppression_for_settings(self) -> None:
        """任一设置窗口打开/独立设置进程存活时暂停桌宠气泡，避免气泡盖住设置界面。"""
        if getattr(self, "win", None) is None:
            return
        shell = getattr(self, "shell", None)
        # 独立设置进程在跑时主进程没有对话框对象，只能看 shell 上的存活标记：
        # 锁文件存在期由 AppShell 维护（watcher 立即 + 3s 轮询兜底清除）。
        external_settings = bool(getattr(shell, "_settings_child_active", False)) if shell is not None else False
        any_open = (
            getattr(self, "modern_settings_dialog", None) is not None
            or getattr(self, "chat_settings_dialog", None) is not None
            or external_settings
        )
        self.win.set_bubble_suppressed(any_open)

    def open_modern_settings(self, initial_page: str | None = None) -> None:
        # 默认路径：设置页拉到独立进程（关窗即进程退出，OS 回收首开留下的
        # 字体/样式/模块高水位）。只有开关关闭或 startDetached 失败时才回退
        # 下面的进程内路径——功能绝不丢。
        if self._try_open_settings_process(initial_page):
            return
        from .modern_settings_dialog import ModernSettingsDialog
        if self.modern_settings_dialog is None:
            dialog = ModernSettingsDialog(
                self.config,
                self.win,
                include_ai=self.enable_chat,
                initial_page=initial_page,
            )
            dialog.finished.connect(self._modern_settings_finished)
            self.modern_settings_dialog = dialog
        elif initial_page:
            selector = getattr(self.modern_settings_dialog, "select_page", None)
            if callable(selector):
                selector(initial_page)
        self._update_bubble_suppression_for_settings()
        # 在 show 之前定位，避免 Windows 上窗口先显示默认位置再跳走（闪现小窗）
        self._present_dialog(
            self.modern_settings_dialog,
            before_present=self.modern_settings_dialog.move_away_from_pet,
        )

    def _try_open_settings_process(self, initial_page: str | None = None) -> bool:
        """尝试走独立设置进程；True = 已交给独立进程（不要再开进程内对话框）。"""
        shell = getattr(self, "shell", None)
        opener = getattr(shell, "open_settings_process", None)
        if not callable(opener):
            return False
        try:
            try:
                return bool(opener(self, page=initial_page))
            except TypeError:
                # 兼容旧测试桩/宿主：老 opener 只接受 instance。
                return bool(opener(self))
        except Exception:
            logging.exception("独立设置进程链路异常，回退进程内设置页")
            return False

    def _modern_settings_finished(self, result: int) -> None:
        self.modern_settings_dialog = None
        self._update_bubble_suppression_for_settings()
        # 新版设置在关闭时一律落盘（closeEvent 自动保存，「保存并退出」同样走
        # _write_config），因此无论 Accepted/Rejected 都把改动应用到桌宠。
        # 此前只有 Accepted 才刷新：直接 X 关闭时保存生效但桌宠不更新。
        #
        # 表单用独立编辑视图（SlotRoutedConfig.new_form_view），但它每次**成功落盘**都会
        # 作废运行期这份视图的只读快照（SlotRoutedConfig._refresh_runtime_view），所以
        # 这里不必再补一次刷新。
        #
        # 应用链与 watcher 路径共用 AppShell._apply_external_config_change；但
        # 旧测试桩（AppShell.__new__ + 只打桩原内联 seam，没有 _instances）仍走
        # 原内联序列，保证进程内路径的既有测试/时序逐位不变。
        shell = self.shell
        apply_change = getattr(shell, "_apply_external_config_change", None)
        if callable(apply_change) and getattr(shell, "_instances", None) is not None:
            apply_change()
        else:
            if self.win is not None:
                self.win.refresh_pet_settings()
            shell._sync_dynamic_island()
            # 模块运行时配置（余额定时器 / 待办服务 / 菜单开关等）在同一处收敛。
            apply_modules = getattr(shell, "_apply_module_config", None)
            if callable(apply_modules):
                apply_modules()
            self._refresh_chat_windows()

    # ------------------------------------------------------------ 其它窗口级
    def sync_look_to_chat(self, user_text: str, reply: str) -> None:
        """把「看看屏幕/主动识屏」的问答同步进 AI 对话记录（issue #24）。

        聊天窗口已创建 → 走窗口内同步（含界面即时刷新）；
        聊天窗口从未打开 → 直接写入当前角色最新会话（无则新建），之后再打开
        聊天窗口即可在历史里回看全文——气泡里被省略/分页的内容不再无处可查。
        """
        if not self.enable_chat or not str(reply or "").strip():
            return
        if self.chat_window is not None and hasattr(self.chat_window, "append_look_sync"):
            self.chat_window.append_look_sync(user_text, reply)
            return
        try:
            from .chat.models import ChatMessage
            from .chat.session_store import SessionStore

            store = SessionStore(self.config.dir, getattr(self.config, "instance_id", ""))
            # ``character`` 是每宠键：会话按角色隔离，读主配置会稳定拿到出厂默认
            # 角色，slot≠0 的宠聊天就串到默认角色的会话里（同族缺陷：进程级服务
            # 读每宠键）。身份统一经 ``_identity_config()`` 取当前呈现身份。
            character_id = str(self._identity_config().get(
                "character", catalog.DEFAULT_CHARACTER))
            sessions = store.list(character_id)
            if sessions:
                session = sessions[0]
            else:
                settings = self.config.chat_settings()
                session = store.create(
                    character_id,
                    settings.active_provider,
                    settings.default_system_prompt,
                )
            msgs = [ChatMessage("user", str(user_text)), ChatMessage("assistant", str(reply))]
            synced, _absorbed = store.append_messages(session, msgs)
            if synced is None:
                # 会话已被并发删除等边界：本地兜底（保持旧行为）
                session.messages.extend(msgs)
                store.save(session)
        except Exception:
            logging.exception("同步识屏问答到会话记录失败")

    def _set_autostart(self, enabled: bool, win=None) -> bool:
        ok = autostart_mod.set_enabled(bool(enabled))
        self.config.set("autostart_wanted", bool(enabled))
        self.config.save()
        target = win or self.win
        if target is not None and not ok:
            target.show_bubble("开机自启写入失败，请检查系统登录项或安全软件设置。", duration_ms=6000)
        return ok

    def _check_autostart_wanted(self) -> None:
        if self.config.get("autostart_wanted", False) and not autostart_mod.is_enabled() and self.win is not None:
            self.win.show_bubble("检测到开机自启已被系统或安全软件关闭，可在设置中重新启用。", duration_ms=7000)



    def _notify_pet_hidden(self) -> None:
        """用户主动隐藏桌宠后弹托盘提示，指明恢复入口。

        灵动岛按聚合可见态同步；托盘挂在 overlay 壳上（``AppShell.tray`` 转发）。
        """
        if getattr(self.shell, "island", None) is not None:
            self.shell.island.set_pet_visible(self.shell._aggregate_pet_visible())
        if self.shell.tray is None:
            return
        self.shell.tray.showMessage(
            "桌宠已隐藏",
            "点击托盘图标即可恢复。",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

class AppShell:
    """进程级外壳 —— 托盘、灵动岛、余额、系统通知、broker。

    批5.1（纯重构）拆自原 PetApp 的「进程级」半边，行为逐位不变；批5.2
    spike 扩成多窗集合（``self.instances``），``self.instance`` 仍是主窗
    （列表头）。aboutToQuit 收口在 ``_on_about_to_quit``，含窗级/进程级
    资源的分段释放（窗级字段与进程级 broker/permanent writer 分开，
    见 §2.2-E2 / R5）。
    """

    def __init__(self, app: QApplication, config: Config, enable_chat: bool = True,
                 overlay_gate=None) -> None:
        self.app = app
        self.config = config
        self._enable_chat = bool(enable_chat)
        # 托盘本体（属性访问器在下方：overlay 拓扑回退到壳持有的托盘）
        self._tray: QSystemTrayIcon | None = None
        # 托盘上下文菜单所有权（F5）：每次构建的 QMenu 必须由进程侧
        # 强引用保活——PySide6 下仅靠 tray.setContextMenu 持有 C++ 指针时，Python
        # wrapper 一旦被回收，之后的 act.menu()/contextMenu() 会命中 shiboken 缓存里
        # 已失效的 wrapper（RuntimeError: Internal C++ object already deleted）。
        # 除菜单本体外还必须保活其 QAction wrapper：子菜单的 menuAction 挂在父菜单的
        # actions 列表里，这些 QAction wrapper 被回收会让仍存活且被强引用的 QMenu
        # wrapper 连带失效（_install_tray_menu 会一并快照保活）。
        # 新菜单接管后旧菜单经 _install_tray_menu 显式 deleteLater 释放，不累积泄漏。
        self._tray_menu: QMenu | None = None
        self._tray_submenus: list[QMenu] = []
        self._tray_actions: list = []
        self._notification_click_callback = None
        self._toast_windows: list[DesktopNotification] = []
        self.island = None
        self.island_chat = None  # 岛对话气泡：桌宠隐藏时的交互面（island_chat.py）
        self._on_about_to_quit_connected = False
        # 唯一渲染拓扑的产品壳（4.1a）：start() 时构造。
        self._overlay_shell = None
        # D4：桌宠单实例进程门（由 main() 抢到后传入；两个拓扑都有，只有直接
        # 构造 AppShell 的测试路径才会拿到 None）。释放挂在会话结束路径
        # （_on_session_end）与 main() 的 finally。
        self._overlay_gate = overlay_gate
        # 功能模块：start() 里按 MODULES 建表并启动；运行期配置收敛与退出收口
        # 都经同一个注册表（模块失败只影响自己，原因可查）。
        self._module_registry = None
        self._module_host = None
        # 4.4b：`experimental_single_process_spawn` 键删除——进程内多窗从
        # "实验开关"升格为**唯一**多宠形态（多进程多宠退役层已删除），
        # 原先依赖该 flag 快照的窗级逻辑（runtime 标记版本化、日志前缀、
        # 退出分派、共享子系统）一律常开/按活窗数派生。
        # 4.4b（T6「multi_window_shared 不删，常开化」）：进程级共享子系统
        # （agent_link / proactive / 全屏 watcher）**恒建**，各窗经 PetWindow
        # 构造参数引用同一份，崩溃/换角色不重建。sprite 拓扑里共享子系统缺位
        # 即静默缺失（agent_link/主动识屏/全屏 watcher 无人承载）。
        #（位置在 _instances 就绪之后，共享 manager 构造期即遍历窗集合）。
        self._shared = None
        # 每窗容器：批5.1 单进程单窗仅一个；批5.2 spike 扩成多窗集合
        #（self.instance 指主窗 = instances[0]，兼容既有调用面）。
        self._instances: list[PetInstance] = []
        # 设置进程隔离：独立设置进程存活标记 + config 目录 watcher/定时器
        #（懒安装，见 _install_config_watcher）。默认关的键下完全不用它们。
        self._settings_child_active = False
        self._settings_launch_at = 0.0
        # 本进程最近一次拉起的设置页归属实例身份（"" = 主身份 / "slot-N"）：
        # 设置页已开着时据此说清"是哪只宠的设置"，None = 归属未知（外部拉起）。
        self._settings_owner_instance_id = None
        self._config_watcher = None
        self._config_reload_timer = None
        self._settings_watch_timer = None
        self._last_config_signature = None
        from . import pet_profiles
        from .settings_slot_config import SlotRoutedConfig
        from types import SimpleNamespace

        migration = pet_profiles.migrate_slot0_profile(config.dir)
        # slot0 档案不可用（``target-corrupt``）只牵连这一份档案 → **降级该槽**，
        # 不拖死整个应用；其余非 ok 状态涉及全局面/迁移基础设施，照旧硬失败并说清楚
        # （'一份坏档案'与'全局配置坏了'是两种事故，处置也不同：前者保留原文件、
        # 把槽空着等用户显式动作，后者必须停下）。2026-10-10 ops D2。
        self._slot0_profile_unusable = False
        self._slot0_profile_diagnosis = ""
        if not migration.ok:
            if not migration.slot_only_problem:
                raise RuntimeError(str(migration))
            self._mark_slot0_profile_unusable(migration)
        identity = SimpleNamespace(dir=config.dir, path=config.dir / "config-slot-0.json",
                                   instance_id="slot-0", data={})
        self.instance = PetInstance(
            self, SlotRoutedConfig(identity, config, 0), enable_chat=self.enable_chat,
        )
        self._instances.append(self.instance)
        from .multi_window_shared import SharedSubsystems

        self._shared = SharedSubsystems(self)  # 4.4b：常开化（T6）
        # 订阅 DSH 统一状态（单读方合并后由共享 Agent 联动管理器转发；收敛逻辑
        # 是 pet/dsh_state.py 的纯函数，读方是 DshMonitor 自己）：
        # thinking/attention 注入与 offline 交互收口在管理器内部完成，这里只
        # 驱动灵动岛的 agent 活跃指示。
        self._shared.agent_link.dsh_state_changed.connect(self._on_dsh_state_changed)
        _LIVE_SHELLS.add(self)

    def _mark_slot0_profile_unusable(self, migration) -> None:
        """slot0 档案不可用（单槽损坏）：**降级该槽**，不拖死整个应用（ops D2）。

        一份 ``config-slot-0.json`` 手改坏/断电半写，此前的处置是
        ``raise RuntimeError`` → 启动失败对话框 → 全局配置、其它槽、提醒、托盘全不可用，
        而对话框里连文件路径都没有。同一类事故在活跃集合上走的是"降级为空继续跑"，
        两条真值策略不一致。

        这里的口径（与规范"不覆盖、不自动修复"并存）：

        - **原文件一个字节不动**：损坏内容可能是用户手改的一手数据，任何"自动修复"都是猜；
        - 该槽在**内存**里退出活跃集合（不落盘），恢复正常后照常复活；
        - 其余槽、全局配置、托盘/恢复入口全部照常；
        - 诊断（**含文件路径**）进日志并留给可见提示，用户不必翻日志才知道出了什么事；
        - **恢复方式按当前拓扑如实说**（见下），不许两种拓扑共用一句"重启"。
        """
        self._slot0_profile_unusable = True
        path = getattr(migration, "profile_path", None)
        # overlay 壳的「生成 / 恢复 slot0」会把该槽档案**重新读一遍**，修好文件后
        # 免重启即可原地恢复（实机验证：.scratch/product-close-approved-gui-
        # 20261011/REPORT.md §4.4；同链路的失败气泡早就写着"再试一次"）。
        recovery = "修好后点托盘 / 恢复窗的「生成 / 恢复 slot0」即可恢复（重启同样有效）。"
        self._slot0_profile_diagnosis = (
            f"slot0 档案不可信（{migration.status}），已跳过这只桌宠；"
            f"原文件保留未改：{path}。" + recovery)
        logging.error("启动：%s（%s）", self._slot0_profile_diagnosis, migration.reason)

    def slot0_profile_diagnosis(self) -> str:
        """slot0 降级诊断（空串 = 正常）。可见恢复入口/托盘提示用。"""
        return str(getattr(self, "_slot0_profile_diagnosis", "") or "")

    def _notify_slot0_profile_unusable(self, action: str) -> bool:
        """slot0 档案不可用时"恢复/生成"被拒的可见反馈（含路径）。返回是否上了屏。

        通道按"谁能真上屏"降级：overlay 壳 / 本窗气泡 → 右下角自绘通知（沿用「系统通知」
        总开关，与 ``_notify_settings_process_busy`` 同口径）。全程只有日志 = 用户点了
        没反应，正是本轮要消灭的那类失败；系统通知被关掉时如实记一条 warning，不假称
        已经提示过。
        """
        text = f"{action} 失败：{self.slot0_profile_diagnosis()}"
        for target in (getattr(self, "_overlay_shell", None),
                       getattr(getattr(self, "instance", None), "win", None)):
            shower = getattr(target, "show_bubble", None)
            if callable(shower):
                try:
                    if shower(text, 9000):
                        return True
                except Exception:
                    logging.exception("提示 slot0 档案不可用时冒泡失败")
        if not bool(self.config.get("system_notifications_enabled", True)):
            logging.warning("slot0 档案不可用，且系统通知已关闭，无法可见提示：%s", text)
            return False
        notify = getattr(self, "system_notify", None)
        if callable(notify):
            try:
                notify("无法恢复桌宠", text)
                return True
            except Exception:
                logging.exception("提示 slot0 档案不可用时发通知失败")
        logging.warning("slot0 档案不可用：%s", text)
        return False

    @property
    def enable_chat(self) -> bool:
        """进程级单源（E2/REVIEW_batch51）：窗口经 PetInstance.enable_chat 转发。"""
        return self._enable_chat

    @enable_chat.setter
    def enable_chat(self, value):
        self._enable_chat = bool(value)

    @property
    def slot_id(self) -> int:
        """唯一桌宠的身份恒为 slot 0。"""
        return 0

    @property
    def instances(self) -> list[PetInstance]:
        return self._instances

    # --- 进程级功能（todo 提醒等）的鸭式访问器：转发到主窗实例 ---
    @property
    def win(self):
        """主窗呈现宿主：sprite 壳（PetWindow 形的呈现面）。

        进程级提醒服务（TodoReminderService）经 ``app.win`` 取气泡锚点，只读
        ``show_bubble`` / ``isVisible`` / ``cfg`` / ``_speech_bubble`` /
        ``visible_content_rect`` / ``scale``——OverlayShell 逐条提供同契约
        （见 overlay_shell「PetWindow 形宿主面」段）；不退回则提醒全部落到系统通知。
        """
        inst = getattr(self, 'instance', None)
        win = inst.win if inst is not None else None
        if win is not None:
            return win
        overlay = getattr(self, '_overlay_shell', None)
        if overlay is not None:
            return overlay
        if not hasattr(self, '_empty_pet_host'):
            self._empty_pet_host = _EmptyPetHost(self)
        return self._empty_pet_host

    @win.setter
    def win(self, value) -> None:
        """Legacy compatibility setter routed to the primary instance."""
        inst = getattr(self, 'instance', None)
        if inst is not None:
            inst.win = value

    @property
    def tray(self):
        """托盘对象：legacy = 本进程建的 QSystemTrayIcon；overlay = 壳的托盘。

        overlay 拓扑进程级托盘由 OverlayShell 持有（``self.tray`` 恒 None），
        不看向壳则「隐藏桌宠 → 点托盘恢复」提示读不到托盘。
        """
        tray = getattr(self, '_tray', None)
        if tray is not None:
            return tray
        return getattr(getattr(self, '_overlay_shell', None), 'tray', None)

    @tray.setter
    def tray(self, value) -> None:
        self._tray = value

    @property
    def modern_settings_dialog(self):
        """转发主窗实例的设置对话框引用（TodoReminderService 气泡抑制判定用）。"""
        inst = getattr(self, 'instance', None)
        return getattr(inst, 'modern_settings_dialog', None) if inst is not None else None

    @property
    def chat_settings_dialog(self):
        """转发主窗实例的对话设置引用（TodoReminderService 气泡抑制判定用）。"""
        inst = getattr(self, 'instance', None)
        return getattr(inst, 'chat_settings_dialog', None) if inst is not None else None

    # ------------------------------------------------------------ DSH 联动门
    def _dsh_tracker_wanted(self) -> bool:
        """DSH 联动的功能门：``agent_link.dsh``（默认关）。

        联动开启时桥接插件才安装（``DshMonitor.install_bridge``，关联动即卸载）、
        DshMonitor（桥目录唯一读方：信号分派 + dsh_state 收敛器共用一份解析）
        才由 ``AgentLinkManager.apply_config`` 拉起；联动没开时它 3s 探端口、
        1.5s 读桥目录全是空转。本方法是核心侧的单一口径；harness 模块按同一
        配置键名（``agent_link.dsh``）自行判定自启/收口（agent_link 本阶段未迁移）。
        """
        agent_cfg = self.config.get("agent_link", {})
        return bool(agent_cfg.get("dsh", False)) if isinstance(agent_cfg, dict) else False

    # ------------------------------------------------------------ 设置进程隔离
    def _apply_external_config_change(self) -> None:
        """把「配置已在别处落盘」同步到运行期（独立设置进程 / watcher 路径）。

        全局快捷键也在这里重注册：关掉进程隔离时设置页就在本进程里保存、**没有**
        watcher，改键要立刻生效就只能挂在这条共用入口上（watcher 路径同样走这里）。

        与进程内对话框 finished 的应用链同源（PetInstance._modern_settings_finished
        在真实壳上委托到这里）；多实例时扇出到每个 PetInstance 的窗口，而不是
        只看主窗——外部改配置的那个实例不一定是主窗。
        """
        for inst in getattr(self, "_instances", []):
            win = getattr(inst, "win", None)
            if win is not None:
                win.refresh_pet_settings()
        overlay_shell = getattr(self, "_overlay_shell", None)
        if overlay_shell is not None:
            refresh = getattr(overlay_shell, "refresh_settings", None)
            if callable(refresh):
                refresh()  # overlay 拓扑的窗口能力重应用（4.1b）
            # 进程级共享子系统（联动读方 / 主动识屏）必须在这里补一次应用：
            # sprite 世界没有 PetWindow，上面的逐窗 refresh_pet_settings 链
            # （终点 sync_optional_services → manager.apply_config）一次都不会
            # 执行，而 OverlayShell.refresh_settings 不含 agent_link/proactive。
            # 不补的话外部改 agent_link.dsh 只落磁盘、读方照旧运行（overlay 下
            # 设置页/独立设置进程保存也不生效）。legacy 走窗链，这里不执行。
            self._sync_shared_optional_services()
        self._sync_dynamic_island()
        # 模块运行时配置（余额定时器 / 待办服务 / 菜单开关等）与进程内服务同一处收敛；harness 模块
        # 在自己的 apply_config 里按 agent_link.dsh 收口自拉起的 dsh web（后台线程）。
        self._apply_module_config()
        for inst in getattr(self, "_instances", []):
            refresh = getattr(inst, "_refresh_chat_windows", None)
            if callable(refresh):
                refresh()

    def _sync_shared_optional_services(self) -> None:
        """按配置重应用进程级共享子系统（联动读方 / 主动识屏）。

        内容与 legacy 窗内 ``sync_optional_services``（window_optional_services.py
        :353）逐条对齐——同一份共享实例、同一套门判定，只是调用点从窗挪到应用级：
        overlay 拓扑下 ``instances[].win`` 恒为 None，那条链没有执行者。

        只在 overlay 分支调用一次；legacy 由窗链负责，绝不重复（apply_config
        本身幂等，重复调用不会重启监视器，但共享管理器按「窗口/壳」扇出，
        这里仍以"一次"为准）。
        """
        shared = getattr(self, "_shared", None)
        if shared is None:
            return
        shared.proactive.apply_config()
        shared.agent_link.apply_config()

    def open_settings_process(self, instance=None, page: str | None = None) -> bool:
        """拉起独立设置进程；True = 已交给独立进程（不得再开进程内对话框）。

        False = 开关关闭或 startDetached 失败，由调用方回退进程内设置页。
        """
        if not bool(self.config.get("settings_process_isolation", True)):
            return False
        self._install_config_watcher()
        if self._settings_process_running():
            # 单实例：已有设置进程在跑（可能不是本主进程拉起的）→ 不再拉起，
            # 但仍按"设置开着"抑制气泡并盯住它的锁文件。
            logging.info("独立设置进程已在运行，不重复拉起")
            self._mark_settings_child(True)
            if not self._settings_launch_pending():
                # 拉起窗口之外 = 用户再次点了「桌宠设置」（可能是另一只宠的）：
                # 静默 return True 会让这次点击表现为"什么都没发生"。
                self._notify_settings_already_open(instance)
            return True
        if self._settings_launch_pending():
            # 刚拉起、子进程还没来得及建锁：连点场景视为已在启动，避免双开。
            self._mark_settings_child(True)
            return True
        if not self._launch_settings_process(instance, page=page):
            return False
        self._settings_launch_at = time.monotonic()
        self._settings_owner_instance_id = _instance_config_identity(instance)
        self._mark_settings_child(True)
        return True

    def _notify_settings_already_open(self, instance) -> None:
        """设置页已开着时的可见反馈（此前是静默 no-op，右击另一只宠像没反应）。

        独立设置进程是**单实例**：进程内多窗共用同一份 Config，所有宠的设置页
        走的都是那一个设置进程，无法再开第二扇窗，也无法从主进程把它前置——
        能做的只有说清现状。文案按归属分三种：同一只（"已经打开"）、另一只
        （"先关闭"）、归属未知（外部拉起的设置进程）。

        走 self-drawn 右下角通知而不是桌宠气泡：设置页开着时气泡本来就被抑制
        （_update_bubble_suppression_for_settings），冒泡必被丢弃；通知沿用
        「系统通知」总开关（与待办提醒的 notify 分支同口径）。
        """
        if not bool(self.config.get("system_notifications_enabled", True)):
            return
        owner = getattr(self, "_settings_owner_instance_id", None)
        requested = _instance_config_identity(instance)
        if owner is not None and owner == requested:
            message = "桌宠设置已经打开（独立设置窗口不会重复打开）：请切换到已打开的窗口。"
        elif owner is not None:
            message = "已有一只桌宠的设置窗口开着：请先关闭它，再打开这只的设置。"
        else:
            message = "桌宠设置已经打开：请先关闭已打开的设置窗口再试。"
        logging.info("设置页已在运行，提示用户：%s", message)
        notify = getattr(self, "system_notify", None)
        if callable(notify):
            try:
                notify("桌宠设置", message)
            except Exception:
                logging.exception("设置页占用提示失败")

    def _settings_process_running(self) -> bool:
        """settings.lock 是否被活着的设置进程持有。

        QLockFile 会把「pid 已死」的残留锁判为陈旧并接管，因此设置进程崩溃
        残留的锁文件不会永久堵住设置入口。
        """
        from PySide6.QtCore import QLockFile

        lock_path = self.config.dir / "settings.lock"
        lock = QLockFile(str(lock_path))
        lock.setStaleLockTime(30000)
        try:
            if lock.tryLock(0):
                lock.unlock()
                return False
        except Exception:
            logging.exception("探测设置进程锁失败")
            return True  # 探测异常按"已在运行"保守处理，宁可不开第二份
        if not lock_path.exists():
            # 拿不到锁但锁文件并不存在 = 目录不可写之类的环境错误，不是"已有设置
            # 进程"；否则用户会彻底打不开设置页。
            logging.warning("设置进程锁探测失败且锁文件不存在：%s", lock_path)
            return False
        return True

    def _settings_launch_pending(self) -> bool:
        """刚拉起独立设置进程的启动窗口（子进程建锁前的连点保护）。"""
        started = float(getattr(self, "_settings_launch_at", 0.0) or 0.0)
        return bool(started) and (time.monotonic() - started) <= 5.0

    @staticmethod
    def _spawn_settings_process(program, arguments, working_dir, environment) -> bool:
        """startDetached 独立设置进程，带着**只给子进程**的那份环境。

        单独一层是为了让"注入的环境到底有没有交给子进程"能被点到（Qt 的实例方法
        在测试侧替换不掉，真起一个设置窗又不合适），实现本身是 Qt 的标准 detach
        路径：实例 ``QProcess`` + ``startDetached()``，与静态重载同语义（子进程与
        父进程生命周期解耦；父进程的环境一个字节都不改）。
        """
        from PySide6.QtCore import QProcess

        process = QProcess()
        process.setProgram(program)
        process.setArguments(list(arguments))
        process.setWorkingDirectory(working_dir)
        process.setProcessEnvironment(environment)
        return bool(process.startDetached())

    def _launch_settings_process(self, instance=None, *, page: str | None = None) -> bool:
        """startDetached 独立设置进程；冻结包与源码运行分流。

        源码运行要走 `-m pet`（工作目录取仓库根），冻结包直接复用 exe 的参数
        分流入口（--settings）——与 --uninstall-cleanup 同一范式。
        """
        from PySide6.QtCore import QProcessEnvironment

        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = ["--settings"]
            workdir = str(Path(sys.executable).parent)
        else:
            program = sys.executable
            arguments = ["-m", "pet", "--settings"]
            workdir = str(Path(__file__).resolve().parent.parent)
        if not program:
            logging.warning("sys.executable 为空，无法拉起独立设置进程")
            return False
        if page:
            arguments += ["--settings-page", str(page)]
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("DSH_PET_INSTANCE", "")
        try:
            started = self._spawn_settings_process(program, arguments, workdir,
                                                  environment)
        except Exception:
            logging.exception("拉起独立设置进程异常")
            return False
        if not started:
            logging.warning("startDetached 未启动独立设置进程，回退进程内设置页")
        return bool(started)

    def _mark_settings_child(self, active: bool) -> None:
        """记录独立设置进程存活态，并同步各窗气泡抑制与存活轮询。"""
        self._settings_child_active = bool(active)
        timer = getattr(self, "_settings_watch_timer", None)
        if timer is not None:
            if active:
                if not timer.isActive():
                    timer.start()
            else:
                self._settings_launch_at = 0.0
                # 设置页已关闭：归属身份作废（下次占用提示按"外部拉起"口径说）
                self._settings_owner_instance_id = None
                timer.stop()
        for inst in getattr(self, "_instances", []):
            update = getattr(inst, "_update_bubble_suppression_for_settings", None)
            if not callable(update):
                continue
            try:
                update()
            except Exception:
                logging.exception("同步设置期气泡抑制状态失败")

    def _poll_settings_process(self) -> None:
        """设置进程存活轮询：崩溃/漏事件时兜底解除气泡抑制；顺带消费指令。"""
        if not bool(getattr(self, "_settings_child_active", False)):
            return
        if self._settings_process_running():
            # 子进程已建锁 = 启动窗口结束：此后锁一消失就可立即解除抑制。
            self._settings_launch_at = 0.0
            return
        if self._settings_launch_pending():
            return
        self._mark_settings_child(False)

    def apply_settings_reset(self, instance=None) -> None:
        """刷新全局reset结果；宠物档案、位置与active不属于此动作。"""
        self.config.reload()
        self._apply_external_config_change()

    def _install_config_watcher(self) -> None:
        """盯 config.json 所在目录 + 文件，把外部写盘合并进运行期（幂等）。

        盯目录而不是只盯文件：config.save() 用 os.replace 落盘会换 inode，
        QFileSystemWatcher 对消失的路径会停止监视，只盯文件必丢后续事件。
        目录信号不带文件名，故 basename 过滤交给 fileChanged（带路径），
        目录信号负责换 inode 后重新 addPath、以及 settings.lock 出现/消失。
        300ms 去抖：一次保存可能伴随目录多次变动。进程内保存同样触发——
        去抖窗口内合并即可；finished 路径不改成走 watcher，保持原时序语义。
        """
        if getattr(self, "_config_watcher", None) is not None:
            return
        if not bool(self.config.get("settings_process_isolation", True)):
            return
        from PySide6.QtCore import QFileSystemWatcher, QTimer

        try:
            self.config.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logging.warning("配置目录不可创建，跳过 config 变更监视：%s", self.config.dir)
            return
        watcher = QFileSystemWatcher()
        watcher.directoryChanged.connect(self._on_config_dir_changed)
        watcher.fileChanged.connect(self._on_config_file_changed)
        if not watcher.addPath(str(self.config.dir)):
            logging.warning("无法监视配置目录：%s", self.config.dir)
            return
        self._config_watcher = watcher
        self._last_config_signature = self._config_signature()
        self._config_reload_timer = QTimer()
        self._config_reload_timer.setSingleShot(True)
        self._config_reload_timer.setInterval(300)
        self._config_reload_timer.timeout.connect(self._on_config_change_debounced)
        self._settings_watch_timer = QTimer()
        self._settings_watch_timer.setInterval(3000)
        self._settings_watch_timer.timeout.connect(self._poll_settings_process)
        self._watch_config_file()

    def _watch_config_file(self) -> None:
        """确保 config.json 在监视列表里（os.replace 换 inode 后被 Qt 自动移除）。"""
        watcher = getattr(self, "_config_watcher", None)
        if watcher is None:
            return
        try:
            path = str(self.config.path)
            if self.config.path.exists() and path not in watcher.files():
                watcher.addPath(path)
        except OSError:
            pass

    def _config_signature(self):
        """(st_ino, mtime_ns, size) 签名：判断 config 是否真的变了（目录信号不带文件名）。

        ``st_ino`` 让原子 ``os.replace`` 落盘换到的新 inode 与上一份区分开——同字节
        数、同时间戳刻度（FAT/exFAT 2s）的改动不再被判重。**非绝对保证**：原位改写、
        inode 号复用、或取不到 inode（部分网络/FUSE 挂载返回 0）时退化为
        ``(mtime_ns, size)``（与改造前同口径，不会更严），故去重门只许偏保守
        （宁可多应用一次，见 ``_on_config_change_debounced``）。
        """
        try:
            stat = self.config.path.stat()
        except OSError:
            return None
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _arm_config_reload(self) -> None:
        """重启去抖窗口：窗口内的多次变动合并成一次 reload+应用。"""
        timer = getattr(self, "_config_reload_timer", None)
        if timer is not None:
            timer.start()

    def _on_config_file_changed(self, path: str) -> None:
        if Path(path).name != self.config.path.name:
            return  # 只认本配置文件的 basename（同目录还有 settings.lock 等）
        self._watch_config_file()
        # 盘上内容没变就不重启去抖窗口：同一次 os.replace 的重复通知可能迟到于
        # 首轮应用之后（mac 实测一次保存两次应用链），无门就会再应用一次。
        # 签名口径与目录侧（_on_config_dir_changed）同源；新内容照常进窗口。
        if self._config_signature() != getattr(self, "_last_config_signature", None):
            self._arm_config_reload()

    def _on_config_dir_changed(self, path: str) -> None:
        self._watch_config_file()
        if self._config_signature() != getattr(self, "_last_config_signature", None):
            self._arm_config_reload()
        # 锁文件出现 = 设置进程已起来（启动窗口结束）；锁文件消失 = 设置进程
        # 退出（QLockFile 解锁即删文件）→ 立即解除气泡抑制。
        lock_path = self.config.dir / "settings.lock"
        if lock_path.exists():
            self._settings_launch_at = 0.0
        elif (bool(getattr(self, "_settings_child_active", False))
                and not self._settings_launch_pending()):
            self._mark_settings_child(False)

    def _on_config_change_debounced(self) -> None:
        # 先采样再 reload，finally 记**采样值**：应用期间外部落盘的第二次保存不能
        # 被算成"已应用"（那会让它随后的通知全被去重门吞掉）。采样只会偏旧 →
        # 失效方向只可能是多应用一次，不可能是漏。
        sampled = self._config_signature()
        self.config.reload()
        try:
            self._apply_external_config_change()
        except Exception:
            logging.exception("应用外部配置变更失败")
        finally:
            self._last_config_signature = sampled

    def _teardown_config_watcher(self) -> None:
        """释放 watcher 与两个定时器（退出/测试收口共用）。"""
        watcher = getattr(self, "_config_watcher", None)
        if watcher is not None:
            for signal, slot in (
                (watcher.directoryChanged, self._on_config_dir_changed),
                (watcher.fileChanged, self._on_config_file_changed),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self._config_watcher = None
        for name in ("_config_reload_timer", "_settings_watch_timer"):
            timer = getattr(self, name, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except RuntimeError:
                pass

    # ------------------------------------------------------------ 功能模块
    def _start_modules(self) -> None:
        """按 ``MODULES`` 建表并启动（幂等；坏包只记为 failed，不拖垮启动）。"""
        if getattr(self, "_module_registry", None) is not None:
            return
        from .module_host import AppModuleHost
        from .modules import MODULES
        from .modules.registry import ModuleRegistry

        host = AppModuleHost(self)
        registry = ModuleRegistry.from_packages(MODULES, tolerant=True)
        self._module_host = host
        self._module_registry = registry
        registry.start_all(host, self.config)
        # 直连模型的核心接缝：模块启动后把 surfcore 服务接进来（模块缺失也安装，
        # 以便离线时继续用磁盘上的人格卡缓存）。核心代码只经这里读服务。
        try:
            from . import surfcore_link

            surfcore_link.bind(self, cache_dir=getattr(self.config, "dir", None))
        except Exception:
            logging.debug("SurfCore 直连接缝安装失败", exc_info=True)

    def _apply_module_config(self) -> None:
        registry = getattr(self, "_module_registry", None)
        if registry is not None:
            registry.apply_config(self.config)

    def _stop_modules(self) -> None:
        registry = getattr(self, "_module_registry", None)
        if registry is not None:
            registry.stop_all()
        try:
            from . import surfcore_link

            surfcore_link.reset()
        except Exception:
            logging.debug("SurfCore 直连接缝清理失败", exc_info=True)

    def running_module(self, module_id: str):
        """运行中的模块实例；没启动/失败/被依赖挡住时返回 None。"""
        registry = getattr(self, "_module_registry", None)
        return registry.get(module_id) if registry is not None else None

    def module_unavailable_reason(self, module_id: str) -> str:
        """菜单 / 设置页置灰时显示的模块原因（运行中为空串）。"""
        registry = getattr(self, "_module_registry", None)
        if registry is None:
            return "模块未启动"
        return registry.unavailable_reason(module_id)

    # ------------------------------------------------------------ 启动
    def start(self) -> None:
        # aboutToQuit 只在控制器层绑定一次：角色热切换会重建窗口，逐个
        # connect win.save_position 会在旧窗口延迟销毁后残留失效引用。
        # 统一走 _on_about_to_quit，在信号触发时读取当前有效窗口。
        if not self._on_about_to_quit_connected:
            self.app.aboutToQuit.connect(self._on_about_to_quit)
            self._on_about_to_quit_connected = True
        character_id = str(self.config.get('character', catalog.DEFAULT_CHARACTER))
        logging.info('当前形象: %s', character_id)
        # 唯一渲染拓扑：单合成窗产品壳接管渲染。
        logging.info('渲染拓扑: overlay(单合成窗)')
        from .overlay_shell import OverlayShell
        # 4.3 后半：把进程级共享子系统（agent_link / proactive）注入 sprite
        # 世界的壳——instances[].win 恒为 None，扇出目标就是这个壳（见
        # multi_window_shared.presentation_targets）。_shared 常建；拿不到时
        # 传 None，壳内呈现面静默空转（绝不因注入缺失阻断启动）。
        shared = getattr(self, "_shared", None)
        self._overlay_shell = OverlayShell(
            self.app, self.instance,
            agent_link_manager=getattr(shared, "agent_link", None),
            proactive_watcher=getattr(shared, "proactive", None))
        self._overlay_shell.start()
        # 批5.2a：进程级共享全屏 watcher 在主窗就绪后启动（自省任一窗是否需要，
        # 无需窗——环则空转）；flag 关时 _shared 为 None，no-op。
        if self._shared is not None:
            self._shared.start()
        # 功能模块在壳与灵动岛就绪后启动：菜单入口/弹窗父窗/岛卡片订阅都依赖它们。
        self._sync_dynamic_island()
        self._start_modules()
        # 设置页进程隔离：启动即装 config 目录 watcher，独立设置进程落盘后由它
        # 合并进运行期（开关关闭时不装，完全走旧路径）。
        self._install_config_watcher()
        QTimer.singleShot(3500, self.instance._check_autostart_wanted)
        # issue #111：会话结束（Windows 关机/注销）探测器。必须在窗口就绪后安装
        # ——它要在关机窗口期到来**之前**就位，才能抢在会话拆除前关掉 ffmpeg
        # 派生（否则系统会弹 0xc0000142 阻塞关机）。
        self._install_session_watcher()
        self._announce_slot0_profile_problem()

    def _announce_slot0_profile_problem(self) -> None:
        """slot0 档案降级后的**可见**告知（含文件路径与恢复动作）。

        静默降级比硬失败更危险：用户看到的是"我的主桌宠不见了"，只会以为坏了或丢了设置。
        这里在窗口/托盘就绪之后把诊断说出来，并点名"生成 / 恢复 slot0"这条显式入口
        （托盘与无托盘恢复窗都有）——恢复动作仍然只由用户自己做，程序不代劳、不覆盖。
        """
        diagnosis = self.slot0_profile_diagnosis()
        if not diagnosis:
            return
        overlay = getattr(self, "_overlay_shell", None)
        if overlay is not None:
            teller = getattr(overlay, "announce_slot0_profile_problem", None)
        else:
            teller = None
        if callable(teller):
            try:
                if teller(diagnosis):
                    return
            except Exception:
                logging.exception("提示 slot0 档案降级失败（overlay）")
        win = getattr(getattr(self, "instance", None), "win", None)
        shower = getattr(win, "show_bubble", None)
        if callable(shower):
            try:
                shower(f"{diagnosis}\n可用托盘/恢复窗的「生成 / 恢复 slot0」再试。",
                       9000)
                return
            except Exception:
                logging.exception("提示 slot0 档案降级失败（窗口）")
        logging.warning("slot0 档案降级提示无法上屏（无可见桌宠/托盘）：%s", diagnosis)

    def _install_session_watcher(self) -> None:
        """安装会话结束探测器（幂等；实例属性强引用保活，不跨实例共享）。"""
        if getattr(self, "_session_watcher", None) is not None:
            return
        try:
            self._session_watcher = install_session_watcher(
                app=self.app, on_session_end=self._on_session_end,
            )
        except Exception:
            logging.exception("安装会话结束探测器失败")

    def _on_session_end(self) -> None:
        """会话结束（关机/注销）：冻结各窗并停止全部 ffmpeg reader（issue #111）。

        幂等：重复的会话结束信号（WM_QUERYENDSESSION 之后又有 WM_ENDSESSION、
        Qt 的 commitDataRequest/aboutToQuit）只收口一次。

        只做正常退出路径（``_on_about_to_quit``）不做、且关机场景必需的三件事：
        关 ffmpeg spawn 闸门、冻结窗口动画（``match_shutdown``）、把各窗素材库
        里**已建的全部 clip** 一起停掉（不只是各窗当前在播的那个：圈末软停驻留
        的 clip 仍持有一个存活但空闲的 ffmpeg 进程，关机时一并收口）、留一行日志。

        刻意**不**做会话保存/写盘/槽位解锁：关机时登录会话已在拆除，那些收尾
        既非必需（多开文件锁由操作系统在进程退出时释放）又会拉长清理窗口，
        与「静默、快速、不再派生任何进程」的目标相反。
        """
        if getattr(self, "_session_end_done", False):
            return
        # 「真会话结束」才置位（ops5.5 终审 C2）：SessionWatcher 把 aboutToQuit 也
        # 汇进同一条 arm 回调——那只是正常退出的兜底，不是关机/注销。靠
        # ``_on_about_to_quit`` 先行置下的标记区分（Qt 按连接序调槽，主退出先到）。
        # 不区分的话，:2137/:2185/:2369 三处会把「正常退出」误当「会话结束」跳过。
        if not getattr(self, "_plain_about_to_quit", False):
            self._session_end_done = True
        self._mark_session_ending()
        # D4：会话结束（关机/注销）路径释放桌宠单实例进程门。与下面的
        # 「不做会话保存/写盘/槽位解锁」不冲突——本模块的释放是一次 unlink +
        # 关句柄，O(1)、不派生进程、不写盘；不显式释放则只剩"进程被拆掉后由
        # OS 回收句柄 + 下次启动按 QLockFile pid 陈旧判定接管"这条兜底链。
        self._release_overlay_gate()
        stopped = 0
        for inst in self._instances:
            win = getattr(inst, "win", None)
            match_shutdown = getattr(win, "match_shutdown", None)
            if callable(match_shutdown):
                try:
                    match_shutdown()
                except Exception:
                    logging.exception("会话结束时冻结窗口失败")
            lib = getattr(win, "lib", None)
            stop_all = getattr(lib, "stop_all_clips", None)
            if callable(stop_all):
                try:
                    stop_all()
                    stopped += 1
                except Exception:
                    logging.exception("会话结束时停止素材库 clip 失败")
        logging.info(
            "会话结束：已停止全部 ffmpeg reader（%d 个素材库收口），进入静默退出", stopped,
        )

    def _release_overlay_gate(self) -> None:
        """释放桌宠单实例进程门（D4；幂等，未注入门时 no-op）。"""
        gate = getattr(self, "_overlay_gate", None)
        if gate is None:
            return
        try:
            gate.release()
        except Exception:
            logging.exception("释放桌宠单实例进程门失败")

    def _mark_session_ending(self) -> None:
        """置位进程级 ffmpeg spawn 闸门（webm_clip.set_session_ending）。

        覆盖「已进入退出流程、但原生 WM_QUERYENDSESSION 未被观测到」的路径
        （如托盘退出、Qt aboutToQuit、测试直接调收口）。
        """
        # 退出标记与闸门同源（R3-gemini P1）：只走 aboutToQuit 置位会漏掉
        # 会话结束观察路径（:2042），在途 autostart worker 会无视退出继续拉起。
        self._quitting = True
        try:
            webm_clip_mod.set_session_ending(True)
        except Exception:
            logging.exception("置位会话结束闸门失败")


    def _on_dsh_state_changed(self, from_state: str, to_state: str) -> None:
        """订阅 DSH 统一状态变化（共享 Agent 联动管理器转发；收敛器是纯逻辑，
        读方是 DshMonitor 自身）。AppShell 侧只剩灵动岛的状态点——
        thinking/attention 注入联动管线与 offline 收口常驻气泡都在管理器内部完成。

        转发的是**收敛态原文**（八态），不再压成活跃布尔：状态点五态体系（空闲/
        工作/待确认/完成/错误）与优先级判定在岛内解析（``set_dsh_state``），
        这里不做第二套映射。
        """
        island = getattr(self, "island", None)
        if island is not None and shiboken6.isValid(island):
            island.set_dsh_state(to_state)

    # ------------------------------------------------------------ 退出收口
    def _on_about_to_quit(self) -> None:
        """退出前保存各窗位置并释放资源（全进程「全部退出」语义，R5 切分）。

        aboutToQuit 只绑定一次自本控制器；切换角色会重建桌宠窗口，信号
        触发时读取当前窗口（经 ``self.instance.win``），避免调用已延迟销毁
        的旧窗口。

        R5 切分：**窗级**项（位置/预热/Agent/各窗会话保存/slot 锁）逐窗收口；
        批5.3 起共享解码 hub 为进程级（shutdown 为 no-op），
        **进程级**收口仅剩 hub ``stop_all()`` 与 ``close_all_writers(permanent=True)``
        各停一次——多窗下任一窗退出不许停进程级资源，只有「全部退出」才收口
        （这也是「退出这只」与「全部退出」的核心差异）。
        """
        # 纯桌宠版（打包排除 ``pet.chat``）里这个模块根本不存在：模块级无条件 import
        # 会让正常退出在**第一步**就 ModuleNotFoundError，而它发生在 ``_mark_session_ending``
        # / ``_quitting`` 等收口之前——位置回写、共享子系统停表、ffmpeg reader 收尾全部
        # 被跳过（2026-10-10 终审「no-chat 变体 normal quit 提前异常」）。改成能力守卫内
        # 的按需 import：没有 chat 就没有会话写盘 worker 要收，跳过是正确答案。
        # issue #111：先关 ffmpeg spawn 闸门，再走正常退出收口——正常退出路径
        # （托盘退出/最后窗口关闭）同样落在关机前后，绝不能在里面再派生 reader。
        # 「正常退出兜底」标记（ops5.5 终审 C2）：本槽先于 SessionWatcher 的
        # aboutToQuit→arm 执行（Qt 按连接序调槽），``_on_session_end`` 凭它区分
        # 「真会话结束」与「正常退出兜底」，只有前者才置 ``_session_end_done``。
        self._plain_about_to_quit = True
        self._mark_session_ending()
        # 退出标记（R2 第五缺口）：在途自动拉起 worker 凭它中止或补偿收口——
        # 否则「退出时登记表为空 → worker 随后 spawn 登记」会留下永远无人收的进程。
        self._quitting = True
        # 功能模块先停（弹窗/轮询线程/服务），再收窗口与进程级资源。
        self._stop_modules()
        # 窗级收口：逐窗保存位置、停本窗预热与 Agent、提交本窗会话
        for inst in self._instances:
            win = inst.win
            if win is not None:
                try:
                    win.save_position()
                except Exception:
                    logging.exception("退出时保存位置失败")
                try:
                    if getattr(win, 'lib', None) is not None:
                        win.lib.pause_warm()
                except Exception:
                    logging.exception("退出时暂停预热失败")
                # issue #111：供给线程不是预热线程——``pause_warm`` 管不到它，而它
                # 自己派生转换 ffmpeg。退出同样是"再派生进程"的坏时机（与 overlay 的
                # ``_on_about_to_quit`` 同一收口位置），库随窗口销毁时活线程还会被
                # 一起析构（Qt fatal）。库侧自带幂等 + 有界等待 + 超时孤儿兜底。
                try:
                    if getattr(win, 'lib', None) is not None:
                        win.lib.cancel_frameseq_provision()
                except Exception:
                    logging.exception("退出时取消帧序列供给线程失败")
                if getattr(win, 'agent_link_manager', None) is not None:
                    try:
                        win.agent_link_manager.shutdown()
                    except Exception:
                        logging.exception("退出时关闭 Agent 失败")
                # 各聊天窗当前会话提交保存（写盘 worker 将在下方永久关闭）
                for _w in (inst.legacy_chat_window, inst.modern_chat_window, inst.quick_chat):
                    _session = getattr(_w, 'session', None)
                    _store = getattr(_w, 'store', None)
                    if _session is not None and _store is not None:
                        try:
                            _store.save(_session)
                        except Exception:
                            logging.exception("退出前保存会话失败")
        # 进程级全局订阅注销：类级 list 长期持有本 shell 强引用，不注销会
        # 阻碍 GC（no-chat 变体无 ChatService，导入守卫与注册处同口径）
        try:
            from .chat.service import ChatService as _ChatService
        except ImportError:
            _ChatService = None
        if _ChatService is not None:
            try:
                _ChatService.unregister_global_finished(self._on_global_chat_finished)
            except Exception:
                logging.exception("退出时注销全局聊天订阅失败")
        # 岛对话气泡（进程级）：**不再**在退出时保存会话（H1）——
        # 完整聊天窗与岛聊天共享同一会话对象，岛聊天的内存快照可能是旧的；
        # 退出时整份覆盖会丢掉已在完整窗口里落盘的新消息。
        # 岛聊天的流式回复在 _finished 回调里通过 append_message 即时落盘
        # （quick_chat.py:424），退出时无需、也不应再覆盖保存。
        # 代价：退出时正在流式输出的岛回复会丢失。
        bubble = getattr(self, "island_chat", None)
        if bubble is not None:
            try:
                bubble.close()
            except Exception:
                logging.exception("退出时关闭灵动岛对话气泡失败")
            self.island_chat = None
        # 会话异步写盘（B8）：全部会话已保存，再永久关闭写盘 worker
        #（关掉后迟到的 queued 回调提交会被明确拒绝）。
        # 待办服务、harness 自拉起进程与全局热键的收口都由各自模块的 stop() 负责
        # （_stop_modules 在本槽前段已执行）；这里不再保留逐功能接线。
        try:
            from .chat import session_store as _session_store

            if not _session_store.close_all_writers(permanent=True):
                logging.warning("退出时会话写盘 worker 未干净关闭")
        except ImportError:
            logging.info("退出收口：本构建没有 chat 模块，跳过会话写盘收口")
        except Exception:
            logging.exception("退出时关闭会话写盘 worker 失败")
        # 批5.2a：进程级共享子系统收口（agent_link / proactive / 全屏 watcher）。
        # 单窗关闭（退出这只）不触发——只有「全部退出」才停共享子系统。
        if self._shared is not None:
            try:
                self._shared.stop_all()
            except Exception:
                logging.exception("退出时关闭共享子系统失败")
        # 设置页进程隔离：释放 config 目录 watcher 与两个定时器（无主 QTimer 的
        # timeout 连接会从 Qt C++ 侧强引用住本对象图，不停则阻碍回收）。
        self._teardown_config_watcher()

    @classmethod
    def _shutdown_live_for_tests(cls) -> None:
        """收口测试直接创建、未走 aboutToQuit 的 AppShell（对齐 agent_link 同族防线）。

        只做 Qt 生命周期释放，不改业务状态：
        - 停待办提醒服务定时器（其 ``_app`` 反向强引用 shell，且无主 QTimer 的
          timeout 连接从 Qt C++ 侧强引用住整个对象图，Python gc 回收不掉）；
        - 共享子系统经 ``SharedSubsystems._shutdown_live_for_tests`` 收口；
        - 断开 shell → app 的 aboutToQuit 连接并释放反向引用；
        - 注销全局聊天订阅（同生产收口口径）；

        不做 ``_on_about_to_quit`` 的退出语义（保存位置/永久关闭写盘 worker）：
        那是「全部退出」，测试收口不得触发。
        """
        for shell in tuple(_LIVE_SHELLS):
            try:
                stop_modules = getattr(shell, "_stop_modules", None)
                if callable(stop_modules):
                    try:
                        stop_modules()
                    except Exception:
                        logging.debug("测试收口模块失败", exc_info=True)
                if getattr(shell, "_shared", None) is not None:
                    shell._shared.stop_all()
                if getattr(shell, "instance", None) is not None:
                    win = getattr(shell.instance, "win", None)
                    lib = getattr(win, "lib", None)
                    if lib is not None:
                        lib.pause_warm()
                if getattr(shell, "_on_about_to_quit_connected", False):
                    try:
                        shell.app.aboutToQuit.disconnect(shell._on_about_to_quit)
                    except (RuntimeError, TypeError):
                        pass
                    shell._on_about_to_quit_connected = False
                # 设置页进程隔离：watcher/定时器同属"无主 Qt 对象"一族，收口
                #（不停会让后续测试凭空多一条 3s 轮询，并阻碍对象图回收）。
                teardown_watcher = getattr(shell, "_teardown_config_watcher", None)
                if callable(teardown_watcher):
                    try:
                        teardown_watcher()
                    except Exception:
                        logging.debug("测试收口 config watcher 失败", exc_info=True)
                shell._settings_child_active = False
                try:
                    from .chat.service import ChatService as _ChatService
                    _ChatService.unregister_global_finished(shell._on_global_chat_finished)
                except Exception:
                    pass
                shell._instances = []
            except Exception:
                logging.debug("测试收口 AppShell 失败", exc_info=True)

    def _on_shared_fullscreen(self, hit: bool) -> None:
        """批5.2a：共享全屏 watcher 广播 → 扇出到各窗的 _on_fullscreen_changed。

        逐窗动态遍历（读 _instances 而非绑定某窗），任一窗退出/重建后自动忽略它。
        经窗的公开信号全屏状态回传（避开 window 私有面冻结，见 test_architecture 红线2）。
        """
        if getattr(self, "_shared", None) is None:
            return
        # 免打扰（issue #208）：全屏 = 等效免打扰的唯一来源（不另起探测）。
        # **入场先立闸、退场后结算**，两个落点都不能挪：
        # - 入场（hit=True）在隐藏各窗之前立闸，隐藏动作自身带出的呈现不会漏过门控；
        # - 退场（hit=False）必须等各窗**恢复显示之后**再结算——结束汇报经
        #   ``MultiWindowProxy`` 只投向可见窗，窗口还没回来就结算等于把攒下的
        #   提醒汇报给空气（交付确认兜底会让它下一拍重试，但正序才是常态路径）。
        # 也刻意不走下面那个按 auto_hide_fullscreen 的逐窗过滤：那是自动隐藏的
        # 开关，与 quiet_also_on_fullscreen 是两个独立偏好。
        from . import quiet_mode

        if hit:
            quiet_mode.note_fullscreen(True)
        for inst in self._instances:
            win = inst.win
            if win is None or not shiboken6.isValid(win):
                continue
            # 复审 P1-2：全屏广播按每窗配置过滤——关掉「全屏自动隐藏」的窗
            # 不得被无关广播隐藏/恢复（光标路径的每窗 gate 在窗内已有，
            # 该窗的 _on_cursor_visibility_changed 首行自过滤，无需重复）。
            if not getattr(win, "auto_hide_fullscreen", False):
                continue
            try:
                win.fullscreen_changed.emit(hit)
            except (AttributeError, RuntimeError):
                logging.exception("扇出全屏状态到窗口失败")
        if not hit:
            quiet_mode.note_fullscreen(False)

    def _on_shared_cursor(self, visibility: str) -> None:
        """批5.2a：共享光标可见性广播 → 扇出到各窗的 _on_cursor_visibility_changed。"""
        if getattr(self, "_shared", None) is None:
            return
        for inst in self._instances:
            win = inst.win
            if win is None or not shiboken6.isValid(win):
                continue
            try:
                win.cursor_visibility_changed.emit(visibility)
            except (AttributeError, RuntimeError):
                logging.exception("扇出光标状态到窗口失败")

    def _wire_shared_subsystems(self) -> None:
        """批5.2a：把新窗接入进程级共享子系统（agent_link 联动动作链分发）。

        共享 manager 在 AppShell.__init__ 已创建（此刻尚无窗，set_link_next_provider
        落入空集），新窗出现后经 proxy 重新分发；proactive 经构造参数引用同一份；
        全屏 watcher 经 _on_shared_fullscreen/_on_shared_cursor 动态遍历，无需单独连。
        """
        shared = self._shared
        if shared is None:
            return
        try:
            shared.proxy.set_link_next_provider(shared.agent_link._next_busy_anim)
        except (AttributeError, RuntimeError):
            logging.exception("把窗口接入共享 Agent 联动链失败")

    def _sync_dynamic_island(self) -> None:
        """按配置创建/隐藏灵动岛；桌宠隐藏后灵动岛仍可常驻。"""
        island_cfg = self.config.get("dynamic_island", {})
        enabled = bool(island_cfg.get("enabled", True)) if isinstance(island_cfg, dict) else False
        if not enabled:
            if getattr(self, "island", None) is not None:
                self.island.hide()
            return
        if getattr(self, "island", None) is None:
            from .dynamic_island import DynamicIsland
            from .module_host import module_service

            self.island = DynamicIsland(
                self.config, focus=module_service(self, "focus"))
            # 纯桌宠版（无聊天模块）：hidden_chat 的岛单击路由回退为展开卡片，
            # 防"桌宠隐藏 → 岛点了没反应 → 无法恢复"的死锁。getattr 兼容
            # __new__ 测试桩（property 内 AttributeError 时取默认 True）
            self.island.set_chat_available(bool(getattr(self, "enable_chat", True)))
            # 岛图标默认取鱼本体头像（图片路径不碰 emoji 字体栈，见 dynamic_island
            # 的 _icon_pixmap 注释）；帧未就绪时岛侧只画底圈并稍后重试
            self.island.set_icon_provider(self._island_icon_pixmap)
            # 岛名是**当前身份**的名字：角色身份走每宠视图，不是进程级配置
            # （换完角色岛名还停在默认那只，见 _identity_config）
            self.island.set_identity_provider(self._identity_config)
            self.island.clicked.connect(self._toggle_pet_from_island)
            self.island.toggle_pet_requested.connect(self._toggle_pet_from_island)
            self.island.open_chat_requested.connect(self._open_chat_from_island)
            self.island.open_settings_requested.connect(self._open_settings_from_island)
            # 桌宠隐藏时单击岛：弹/收锚定岛的对话气泡（hidden_chat 开启时）
            self.island.chat_requested.connect(self._chat_from_island)
            # 卡片展开 → 余额模块在启动时自行挂接（静默刷新，不冒泡/不播动画）。
            # 进程级聊天完成订阅：AI 回复到达 → 岛播事件动效并记录最近消息。
            # 无聊天功能的打包变体会排除 pet.chat（参照 config.py 的同款守卫），
            # 那里跳过订阅即可，灵动岛本体照常可用。
            try:
                from .chat.service import ChatService
            except ImportError as exc:
                if str(getattr(exc, "name", "") or "").startswith("pet.chat"):
                    ChatService = None  # 无聊天打包变体：跳过订阅，岛本体照常
                else:
                    raise
            if ChatService is not None:
                ChatService.register_global_finished(self._on_global_chat_finished)
        self.island.refresh_from_config()
        # 批5.2a：灵动岛按**聚合**可见态同步（任一窗可见 = 可见），替代只看主窗。
        self.island.set_pet_visible(self._aggregate_pet_visible())
        self.island.show()

    def _open_chat_from_island(self) -> None:
        if not getattr(self, "enable_chat", True):
            # no-chat 打包变体：给可见反馈（岛弹跳），不静默 no-op
            island = getattr(self, "island", None)
            if island is not None and shiboken6.isValid(island):
                island.bump(1.5, 0.0, -1.0)
            return
        # 桌宠全部隐藏：快速气泡锚不到桌宠，改弹到岛上（岛是对话代理）
        if not self._aggregate_pet_visible() and self._island_chat_available():
            self._show_island_chat(activate=True)
            return
        inst = self.instance
        if inst is not None and callable(getattr(inst, "open_quick_chat", None)):
            inst.open_quick_chat()

    # -------------------------------------------------------- 岛对话气泡
    def _island_hidden_chat_enabled(self) -> bool:
        island_cfg = self.config.get("dynamic_island", {})
        if not isinstance(island_cfg, dict):
            return False
        return bool(island_cfg.get("hidden_chat", True))

    def _island_interactive(self) -> bool:
        """岛当前是不是**启用且可见**的交互面。

        ``_sync_dynamic_island`` 关岛走的是 ``hide()`` + 摘桥，**不销毁对象**——
        「对象保留 ≠ 交互面可用」。判据读宿主这一侧的运行态（本进程内存里的岛
        启用真值 + 岛窗自己的显隐），不读磁盘：岛开关可能是运行中改的（托盘菜单 /
        设置子进程落盘后由 config watcher 收口），磁盘上那份随时可能滞后一拍。
        """
        island = getattr(self, "island", None)
        if island is None or not shiboken6.isValid(island):
            return False
        island_cfg = self.config.get("dynamic_island", {})
        if isinstance(island_cfg, dict) and not bool(island_cfg.get("enabled", True)):
            return False
        try:
            return bool(island.isVisible())
        except (AttributeError, RuntimeError):
            # 测试替身/已销毁的原生窗口：宁可判成不可用（不弹孤窗），也不赌
            return False

    def _island_chat_available(self) -> bool:
        """岛对话气泡可用：聊天功能在 + 岛是启用可见的交互面 + hidden_chat 开。

        关岛之后（运行中改的也算）这里的三个"岛还在"的门都必须同时成立，否则隐藏
        桌宠时的反馈改道/后台回复会锚着岛旧位置弹气泡——一个用户关掉的岛还在屏幕
        上冒泡（2026-10-09 审查 R07）。
        """
        if not getattr(self, "enable_chat", True):
            return False
        if not self._island_interactive():
            return False
        return self._island_hidden_chat_enabled()

    def _chat_identity_config(self):
        """岛对话气泡的**呈现配置视图**（slot0 档案，规范 §二）。

        角色/人设/历史由 SurfCore 持有；气泡仍用 slot0 的每宠配置读气泡样式等
        呈现键。`AppShell.instance` 的配置面就是那条路由视图
        （``SlotRoutedConfig(..., 0)``）：每宠键从 `config-slot-0.json` 读、缺键
        取同源默认，全局键仍取主配置。这样同一进程里所有宠物面看到的是同一份
        slot0 呈现设置，而不是全局面上出厂默认的残留。

        拿不到实例（精简装配 / 测试替身）时回退全局面。
        """
        config = getattr(getattr(self, "instance", None), "config", None)
        return config if config is not None else self.config

    def _identity_config(self):
        """进程级服务的**角色身份**取源：当前呈现身份的每宠视图。

        ``character`` 属 ``PER_PET_KEYS``，真值在 ``config-slot-N.json``；全局面那个
        ``character`` 是出厂默认的残留（slot0 迁移与 ``Config.save`` 都会把每宠键从
        ``config.json`` 清掉）。所以灵动岛名、托盘「切换角色」勾选、主动识屏的
        ``pet_name`` 三条进程级读点一律经这里取当前身份——不是「没有值」，是**稳定
        读到错的默认值**（2026-10-19 用户反馈：换完角色，灵动岛名还是默认那只）。

        两条拓扑各自的"该宠此刻真正在用的那份视图"，不另造读取口径：

        - overlay：主宠是 sprite，取壳的 ``_sprite_config(主 sprite)``（配置同步边界
          会作废它的快照，换角色后立刻是新值）；
        - legacy：``PetInstance.config`` 那条 slot0 路由视图。

        overlay 壳还没有主 sprite（启动期、slot0 档案被降级、退出收口后）时退回同一条
        slot0 视图：两者读的都是 slot0 档案，不会给出第二个真值。
        """
        overlay = getattr(self, "_overlay_shell", None)
        sprite = getattr(overlay, "sprite", None)
        sprite_config = getattr(overlay, "_sprite_config", None)
        if sprite is not None and callable(sprite_config):
            return sprite_config(sprite)
        return self._chat_identity_config()

    def _surfcore_companion(self):
        """陪伴线的 SurfCore 桥（核心只经模块服务表拿；拿不到 = 离线）。"""
        from .module_host import module_service

        service = module_service(self, "surfcore")
        return getattr(service, "companion", None)

    def _show_island_chat(self, *, activate: bool = True,
                          reply_text: str | None = None) -> None:
        """弹出锚定灵动岛的对话气泡（activate=False 为不抢焦点的预览弹出）。"""
        if not self._island_chat_available():
            return
        from .island_chat import IslandChatBubble

        chat_config = self._chat_identity_config()
        companion = self._surfcore_companion()
        if getattr(self, "island_chat", None) is None:
            self.island_chat = IslandChatBubble(chat_config, companion=companion)
            self.island_chat.show_pet_requested.connect(self._show_pets_from_island_chat)
        bubble = self.island_chat
        bubble.set_companion(companion)
        bubble.open_chat_callback = self._open_full_chat_from_island_chat
        bubble.show_for_island(self.island, activate=activate, reply_text=reply_text)

    def _chat_from_island(self) -> None:
        """桌宠隐藏时单击岛：气泡已开则收起，否则弹出（交互式）。

        **没有对话能力的变体（纯桌宠版，打包时排除 `pet.chat`）**走不到气泡：
        岛是桌宠隐藏后唯一的常驻交互面，此时单击直接**把桌宠叫回来**。
        旧行为是发完 `chat_requested` 后被 `_show_island_chat` 的可用性闸门
        静默挡掉，用户点了完全没反应（2026-09-23 修复）。
        """
        if not self._island_chat_available():
            self._show_pets_from_island_chat()
            return
        bubble = getattr(self, "island_chat", None)
        if bubble is not None and shiboken6.isValid(bubble) and bubble.isVisible():
            bubble.close()
            return
        self._show_island_chat(activate=True)

    def _open_full_chat_from_island_chat(self) -> None:
        inst = getattr(self, "instance", None)
        if inst is not None and callable(getattr(inst, "open_chat", None)):
            inst.open_chat()

    def _island_feedback_available(self) -> bool:
        """桌宠隐藏期间灵动岛反馈面是否可用（window 的联动暂停决策探针）。

        可用时隐藏不暂停联动监视器：DSH 事件继续驱动岛反馈气泡；
        不可用（无聊天模块 / 岛未启用 / hidden_chat 关）时照旧暂停联动。"""
        return self._island_chat_available()

    def _island_feedback_bubble(self, text: str, subtitle: str = "",
                                duration_ms: int = 3200) -> bool:
        """桌宠隐藏时的反馈气泡改道面（window_alerts.redirect_hidden_bubble 注入调用）。

        DSH 联动状态/提醒等非交互气泡在桌宠隐藏期间改弹到岛对话气泡
        （预览式，不抢焦点，超时自动收回，后到覆盖）。岛对话不可用
        （无聊天模块 / 岛未启用 / hidden_chat 关 / 桌宠其实可见）时返回
        False，调用方维持原丢弃行为。

        岛聊天**有在途请求**时同样返回 False（丢弃本轮反馈）：气泡是同一个，
        预览式改写会把在途请求的 request_id 清掉，真实回答随后被完成回调按
        request_id 静默丢掉（既不显示也不落库）——聊天明显比一条状态气泡重要。
        不排队：这类反馈是"正在想办法/开始干活"的瞬时状态，压到回答之后才送
        等于送达一条过期消息（与 :meth:`_on_global_chat_finished` 的"气泡在场
        则跳过"同一取舍）。"""
        if self._aggregate_pet_visible() or not self._island_chat_available():
            return False
        island = getattr(self, "island", None)
        if island is None or not shiboken6.isValid(island):
            return False
        from .island_chat import IslandChatBubble

        companion = self._surfcore_companion()
        if getattr(self, "island_chat", None) is None:
            self.island_chat = IslandChatBubble(
                self._chat_identity_config(), companion=companion)
            self.island_chat.show_pet_requested.connect(self._show_pets_from_island_chat)
        bubble = self.island_chat
        bubble.set_companion(companion)
        asker = getattr(bubble, "request_in_flight", None)
        if callable(asker) and asker():
            return False
        bubble.open_chat_callback = self._open_full_chat_from_island_chat
        bubble.show_feedback(island, text, subtitle=subtitle, duration_ms=duration_ms)
        return True

    def _show_pets_from_island_chat(self) -> None:
        """岛对话气泡里的「显示桌宠」：恢复全部窗并同步岛状态。

        overlay 拓扑下 ``instances[].win`` 恒为 None（PetWindow 不构造），旧的全窗
        ``show()`` 循环一只都命不中——宠物实际没恢复，岛却被直接标成可见。恢复面是
        唯一合成窗，那里走壳自己的 ``set_pet_visible(True)``（``overlay.show()`` +
        共享子系统 resume + 岛状态同步，与岛单击 toggle 同一条路，见
        ``overlay_shell.py`` 的 ``set_pet_visible``）。

        整窗恢复之后还要补一手**逐只恢复**（见 :meth:`_restore_overlay_sprites`）：
        壳的逐只隐藏是用户显式决定（托盘「显示这只」），``set_pet_visible(True)``
        按设计保留它——只走整窗恢复的话，逐只全藏过的桌宠"窗在、宠不在"，岛却被
        标成可见。
        """
        overlay = getattr(self, "_overlay_shell", None)
        if overlay is not None:
            overlay.set_pet_visible(True)
            self._restore_overlay_sprites(overlay)
        else:
            for inst in getattr(self, "_instances", []):
                win = getattr(inst, "win", None)
                if win is not None:
                    win.show()
        island = getattr(self, "island", None)
        if island is not None and shiboken6.isValid(island):
            island.set_pet_visible(True)
        bubble = getattr(self, "island_chat", None)
        if bubble is not None and shiboken6.isValid(bubble):
            bubble.close()

    def _restore_overlay_sprites(self, shell) -> None:
        """整窗恢复后仍无可见 sprite 时，把逐只被藏的 sprite 全部恢复可见。

        ``OverlayShell.set_pet_visible`` 的语义是「整窗显隐保留逐只选择」（壳的
        ``_set_all_clips_paused`` 恢复侧显式跳过 ``visible`` 为假的 sprite，托盘
        「显示这只」的隐藏不会被整窗显示悄悄解除）——那条语义是对的，问题在于岛
        气泡「显示桌宠」是**唯一**能把隐藏的桌宠叫回来的手柄（桌宠不可见时用户够
        不着托盘逐只菜单），它不能只恢复窗。

        只在**一只可见的都没有**时才补这一步：有可见 sprite 就一根逐只标志都不碰，
        用户的逐只选择原样保留；没有 sprite 清单的精简装配/测试替身按「窗口可见即
        可见」处理（与 :meth:`_overlay_sprite_visible` 同一口径），什么都不做。

        遍历**全部宿主**：混合缩放下每块屏一张窗，只恢复主窗的话副屏那几只藏着的
        宠永远叫不回来（用户点了「显示桌宠」却仍有屏是空的）。
        """
        if self._overlay_sprite_visible(shell):
            return
        setter = getattr(shell, "set_sprite_visible", None)
        if not callable(setter):
            return
        for host in self._overlay_hosts(shell):
            sprites = getattr(getattr(host, "overlay", None), "sprites", None)
            if sprites is None:
                continue  # 该宿主没有 sprite 清单接口（精简装配）
            for sprite in list(sprites):
                setter(sprite, True)

    def _open_settings_from_island(self) -> None:
        inst = self.instance
        if inst is not None and callable(getattr(inst, "open_modern_settings", None)):
            inst.open_modern_settings()

    def _on_global_chat_finished(self, text: str) -> None:
        """ChatService 全局完成回调（GUI 线程）：驱动灵动岛事件动效。"""
        island = getattr(self, "island", None)
        if island is None or not shiboken6.isValid(island):
            return
        island.set_last_message(text)
        island.notify_event("reply")
        # 桌宠隐藏时岛是唯一常驻交互面：回复到达在岛上弹预览气泡（不抢焦点，
        # 超时自动收回）。岛气泡在场时跳过——多半是气泡自己刚回完话，别再弹。
        if not self._aggregate_pet_visible() and self._island_chat_available():
            bubble = getattr(self, "island_chat", None)
            if bubble is not None and shiboken6.isValid(bubble) and bubble.isVisible():
                return
            # 完整聊天窗已打开：回复已有去处，不再弹岛预览
            for inst in getattr(self, "_instances", []):
                for _attr in ("legacy_chat_window", "modern_chat_window"):
                    _w = getattr(inst, _attr, None)
                    if _w is not None and shiboken6.isValid(_w) and _w.isVisible():
                        return
            self._show_island_chat(activate=False, reply_text=text)

    def _aggregate_pet_visible(self) -> bool:
        """是否有任一窗可见（聚合可见态——灵动岛按它同步 set_pet_visible）。"""
        overlay = getattr(self, "_overlay_shell", None)
        if overlay is not None:
            # overlay 拓扑：instances[].win 恒为 None（PetWindow 不构造），
            # 聚合可见态由合成窗承担。但合成窗是**常驻**透明全屏窗——逐只显隐
            # （OverlayShell.set_sprite_visible）只翻 sprite.visible、不关它，故
            # 窗口可见只是必要条件：还要至少剩一只可见 sprite（见下）。混合缩放
            # 下一块屏一张窗（多宿主）：任一张窗可见 + 任一宿主上有一只可见即成立，
            # 只看主窗会把"主窗空着、副屏还有宠"判成隐藏。
            windows = [getattr(host, "overlay", None)
                       for host in self._overlay_hosts(overlay)]
            if not any(self._window_visible(window)
                       for window in windows if window is not None):
                return False
            return self._overlay_sprite_visible(overlay)
        return any(
            inst.win is not None and getattr(inst.win, "isVisible", lambda: True)()
            for inst in self._instances
        )

    @staticmethod
    def _overlay_hosts(shell) -> list:
        """壳的全部宿主（混合缩放下每块屏一个）；没有 ``hosts()`` 的精简装配按单宿主算。"""
        getter = getattr(shell, "hosts", None)
        return list(getter()) if callable(getter) else [shell]

    @staticmethod
    def _window_visible(window) -> bool:
        """该窗口是否在屏上；原生窗口已销毁（RuntimeError）算不可见。"""
        try:
            return bool(window.isVisible())
        except RuntimeError:
            return False

    @staticmethod
    def _overlay_sprite_visible(shell) -> bool:
        """是否至少有一只可见 sprite（主宠与子宠、**每块屏的窗**同等计入）。

        逐只藏光全部 sprite 后窗口仍 ``isVisible()``，此时桌宠在屏幕上其实一只
        都没有——聚合若判可见，岛会把快速对话锚到不可见的 sprite，隐藏期该弹的
        岛气泡也不再弹。可见性读壳自己的 ``_sprite_visible``（同一判据，含鸭式
        sprite 的兜底）。

        遍历全部宿主：混合缩放下每块屏一张窗，只看主窗（``shell.overlay``）会把
        "全迁到副屏"判成一只都没有、把"主窗藏光但副屏有宠"判成隐藏。两种兜底要
        分开：**没有** sprite 清单这个接口（精简装配/测试替身）→ 按「窗口可见即
        可见」；清单**存在**但一只都没有 → 真的没有可见宠。
        """
        probe = getattr(shell, "_sprite_visible", None)
        has_list = False
        for host in AppShell._overlay_hosts(shell):
            sprites = getattr(getattr(host, "overlay", None), "sprites", None)
            if sprites is None:
                continue  # 这个宿主没有 sprite 清单接口
            has_list = True
            for sprite in list(sprites):
                visible = (probe(sprite) if callable(probe)
                           else getattr(sprite, "visible", True))
                if visible:
                    return True
        return not has_list

    def _toggle_pet_from_island(self) -> None:
        # overlay 拓扑：inst.win 全为 None，旧循环拿不到任何窗——路由到
        # OverlayShell（其 set_pet_visible 自带岛状态同步与共享子系统
        # pause/resume，语义 = 下方 legacy 全窗 toggle 的单窗形态）。
        overlay = getattr(self, "_overlay_shell", None)
        if overlay is not None:
            overlay._toggle_pet_visible()
            return
        # 批5.2a §③.4：灵动岛单击 toggle **全部**窗（任一可见 → 全部隐藏；否则全部显示），
        # 并按聚合可见态同步 set_pet_visible（替代 spike 只 toggle 主窗的 P2-5 缺口）。
        wins = [inst.win for inst in self._instances if inst.win is not None]
        if not wins:
            return
        any_visible = any(getattr(w, "isVisible", lambda: True)() for w in wins)
        if any_visible:
            for w in wins:
                w.hide(notify=False)
        else:
            for w in wins:
                w.show()
        if getattr(self, "island", None) is not None:
            self.island.set_pet_visible(not any_visible)

    def _island_icon_pixmap(self):
        """灵动岛"鱼本体头像"：取首个桌宠窗的当前帧图标；无窗/无帧返回 None（岛侧会重试）。

        4.4a overlay 拓扑：``instances[].win`` 恒为 None（单合成窗，桌宠在
        OverlayShell 里），图标改从壳的主 sprite 当前帧取（``OverlayShell.icon_pixmap``
        与旧 ``PetWindow.icon_pixmap`` 同款裁剪/缩放）；两处都取不到才返回 None，
        岛侧按 provider 契约（dynamic_island._icon_pixmap 不缓存 None）稍后重试。
        """
        for inst in getattr(self, "_instances", []):
            win = getattr(inst, "win", None)
            if win is not None:
                pm = win.icon_pixmap(64)
                if pm is not None and not pm.isNull():
                    return pm
        overlay_shell = getattr(self, "_overlay_shell", None)
        if overlay_shell is not None:
            pm = overlay_shell.icon_pixmap(64)
            if pm is not None and not pm.isNull():
                return pm
        return None

    def _settings_window_releasable(self, instance: PetInstance) -> bool:
        """不可逆收口**之前**：把这张窗的进程内设置页过一遍关闭闸门。

        True = 可以继续收口（没有设置页，或它已经关掉）；False = 用户在失败框里选了
        「继续编辑」，调用方必须**整次取消**这次关闭请求，一个资源都不许动。

        为什么必须在收口之前做（ops P3-c）：设置页的关闭闸门在保存失败时会弹框，用户选
        「继续编辑」时 ``close()`` 被 ignore。等收口流程走到 ``_close_instance_subwindows``
        才发现就晚了——那时位置已存、预热已停、Agent 已关、会话写盘 worker 已关，父窗随即
        销毁，草稿窗成孤儿跟着消失（那里也**没法**在中途安全退出：留下的是半死的宠物）。

        只认 ``modern_settings_dialog``（有保存闸门的那一个）；ChatSettingsDialog 的
        closeEvent 没有闸门，仍由 ``_close_instance_subwindows`` 收。
        """
        dialog = getattr(instance, "modern_settings_dialog", None)
        if dialog is None:
            return True
        try:
            closed = dialog.close()
        except Exception:
            # C++ 对象已经没了（WA_DeleteOnClose 之后又被回收）：没有草稿可保护。
            logging.exception("退出前关闭进程内设置页失败")
            return True
        if isinstance(closed, bool):
            return closed
        # 老替身/桩：close() 没有返回值，退回可见性判据（隐藏的窗口不可能有用户草稿）。
        visible = getattr(dialog, "isVisible", None)
        return not (callable(visible) and bool(visible()))

    def _release_settings_windows(self) -> bool:
        """所有窗的进程内设置页过一遍关闭闸门；False = 调用方必须取消这次退出。"""
        for instance in list(getattr(self, "_instances", None) or ()):
            if not self._settings_window_releasable(instance):
                return False
        return True

    def request_app_quit(self) -> None:
        """托盘/恢复窗的「退出应用」：进程内设置页先过关闭闸门，用户要留在设置里就取消整次退出。

        只接**用户显式**的退出入口（托盘「退出」/「退出应用」、恢复窗按钮）。OS 强制会话
        结束与程序内其它 ``app.quit()`` 不走这里：``aboutToQuit`` → ``_on_session_end`` 那条
        路径保持既有语义——**不弹任何阻塞对话框**、照旧收口（见 docs/ISSUE-111-*）。
        """
        if not self._release_settings_windows():
            logging.info("退出应用：用户留在设置页里继续改，本次退出取消")
            return
        self.app.quit()



    def system_notify(self, title: str, message: str, *, on_click=None, duration_ms: int = 5000) -> None:
        """Show a bottom-right desktop notification (self-drawn, tray-independent)."""
        self._prune_toasts()
        toast = DesktopNotification(
            str(title),
            str(message),
            on_click=on_click,
            duration_ms=int(duration_ms),
        )
        self._toast_windows.append(toast)
        toast.destroyed.connect(lambda _obj=None: self._prune_toasts())
        toast.show()
        position_stack(self._toast_windows)

    def _prune_toasts(self) -> None:
        self._toast_windows = [
            w for w in self._toast_windows
            if not (hasattr(w, "is_closed") and w.is_closed())
        ]
        position_stack(self._toast_windows)

# Historical public name retained for integrations and older tests.
PetApp = AppShell


def main(argv: list[str] | None = None, enable_chat: bool = True) -> int:
    argv = list(argv if argv is not None else sys.argv)

    app = QApplication(argv)
    app.setApplicationName(APP_DIR_NAME)
    app.setQuitOnLastWindowClosed(False)
    # 图片解码上限（像素级别的一处设定）：Qt 默认 256 MB/张（本机 Qt 6.11.2 实测），
    # 用户给的超大图会**直接读不出来**而不是慢一点——聊天附件预览、设置页头像、
    # 趣味图片弹窗都吃这条上限。踩点放在这里而不是各调用点：它是静态设置，
    # 一处设定覆盖全进程（与本文件里其它 Qt 全局设定同一位置纪律）。
    from .qt_image_limits import apply_image_allocation_limit
    apply_image_allocation_limit()

    # 确定配置根目录
    config_dir = _default_base() / APP_DIR_NAME

    # D4（PHASE4_DESIGN §4）桌宠单实例进程门：**先于** slot 竞争。两个拓扑都抢
    # （T4 Phase A）：overlay 双开 = 两个进程各自恢复全部 sprite、位置回写互踩；
    # 捕获模式的 legacy 单窗拓扑同样是完整实例（建窗、存位置、落盘配置），双开
    # 与「重启时多只桌宠先收拢为主宠物」的单窗口径冲突。第二实例必须在产生任何
    # 配置目录副作用（抢 slot-1、落种 config-slot-N.json）之前退场。
    overlay_gate = overlay_gate_mod.acquire_overlay_instance_gate(config_dir)
    if not overlay_gate.acquired:
        # 双击桌面宠物场景：不弹窗、不阻塞，只留痕 + 退出。退出码对齐
        # pet/__main__.py 的 settings.lock 惯例（「已有实例，本次退出」= 0），
        # 免得外壳把"第二实例"当启动失败报错。
        logging.warning(
            "已有实例在运行（门 %s，持有者 pid=%s）：本次启动退出",
            overlay_gate.path, overlay_gate.holder_pid(),
        )
        return overlay_gate_mod.DUPLICATE_EXIT_CODE

    try:
        instance_id = ""
        os.environ["DSH_PET_INSTANCE"] = ""
        config = Config(instance_id="")
        _setup_logging(config)

        logging.info("dsh-pet-standalone 启动 (slot: 0, instance: %s)", instance_id)
        _cleanup_stale_runtime_dirs()
        stale_removed = autostart_mod.cleanup_stale_entries()
        if stale_removed:
            logging.info("已清理 %d 个指向不存在路径的开机自启项", stale_removed)

        controller = AppShell(app, config, enable_chat=enable_chat,
                              overlay_gate=overlay_gate)
        try:
            controller.start()
        except Exception as exc:
            logging.exception("启动失败")
            _show_startup_error("dsh-pet-standalone", str(exc))
            return 1

        logging.info("进入事件循环")
        return app.exec()
    finally:
        # D4：正常退出（app.exec() 返回前 aboutToQuit 已跑完，各窗位置已落盘）
        # 才释放进程门——比 _on_about_to_quit 内更晚，避免"本地还在收尾、第二
        # 实例已能起来"的位置回写竞态。会话结束路径另见 _on_session_end。
        if overlay_gate is not None:
            try:
                overlay_gate.release()
            except Exception:
                logging.exception("释放桌宠单实例进程门失败")


if __name__ == '__main__':
    sys.exit(main())
