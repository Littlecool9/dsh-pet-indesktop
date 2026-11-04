# -*- coding: utf-8 -*-
"""「DeepSeek Harness」模块运行时：自启调度、生命周期收口与菜单动作。

- 自启：宿主壳就绪后 4s 调度一次，门 = ``enable_chat`` + ``harness_autostart`` +
  ``agent_link.dsh``（模块之间只共享配置契约，不 import 对方）。
- 收口：DSH 联动被关掉时**在后台线程**停掉本进程自拉起的 dsh web；退出时由
  ``ModuleRegistry.stop_all`` 调用 :meth:`stop` 做最后一次收口。
- 关机/注销路径（``_session_end_done``）不派生任何进程，与 issue #111 纪律一致。
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QCoreApplication, QTimer

from ..base import ModuleHost, ModuleManifest
from . import harness_launcher

logger = logging.getLogger(__name__)

MODULE_ID = "harness"
AUTOSTART_DELAY_MS = 4000


class HarnessModule:
    def __init__(self, manifest: ModuleManifest | None = None) -> None:
        self.manifest = manifest
        self._host: ModuleHost | None = None
        self._config = None
        self._seen_dsh_wanted: bool | None = None

    # ---- PetModule ----------------------------------------------------------
    def start(self, host: ModuleHost) -> None:
        self._host = host
        self._config = getattr(host, "config", None)
        # 与原先 AppShell.start 的 QTimer.singleShot(4000, ...) 同点位：模块在壳
        # 就绪后启动，因此这里调度一次即可。没有 QCoreApplication 的纯单元测试
        # 环境不调度（也不该有事件循环）。
        if QCoreApplication.instance() is not None:
            QTimer.singleShot(AUTOSTART_DELAY_MS, self._maybe_autostart)

    def apply_config(self, config) -> None:
        self._config = config
        wanted = self._dsh_tracker_wanted(config)
        first = self._seen_dsh_wanted is None
        self._seen_dsh_wanted = wanted
        if first:
            # 启动时只记录基线：DSH 本来就关着不是「刚刚被关掉」，不必收口。
            return
        if not wanted and not self._session_end_done():
            self._start_stop_thread()

    def stop(self) -> None:
        host = self._host
        if host is None:
            return
        # 先读宿主标记再清引用：清掉 _host 后就查不到 shell 的会话结束状态了。
        session_end = self._session_end_done()
        self._host = None
        self._config = None
        if session_end:
            # 关机/注销：不 taskkill、不起 powershell（issue #111）。
            return
        try:
            harness_launcher.stop_self_launched_harness()
        except Exception:
            logger.exception("停止自拉起的 dsh 服务失败")

    # ---- 自启 ---------------------------------------------------------------
    def _maybe_autostart(self) -> None:
        if not self._autostart_wanted():
            return

        def _run() -> None:
            try:
                # 慢探测期间联动/开关可能已被关掉，门必须在每个耗时步骤后重核。
                if self._quitting():
                    return
                if not self._autostart_wanted():
                    return
                config = self._config
                harness_launcher.launch_harness(
                    open_browser=False,
                    target=str(config.get("harness_launch_target", "auto")),
                    cancel_check=lambda: (
                        self._quitting()
                        or self._session_end_done()
                        or not self._autostart_wanted()
                    ),
                )
                if self._session_end_done():
                    return
                if not self._autostart_wanted() or self._quitting():
                    # 拉起刚完成就被关掉/进程在退出：立刻补偿收口。
                    harness_launcher.stop_self_launched_harness()
            except Exception:
                logger.exception("随桌宠自动拉起 dsh 服务失败")

        threading.Thread(
            target=_run, daemon=True, name="pet-harness-autostart"
        ).start()

    def _autostart_wanted(self) -> bool:
        shell = self._shell()
        if not bool(getattr(shell, "enable_chat", False)):
            return False
        config = self._config
        if config is None:
            return False
        if not bool(config.get("harness_autostart", False)):
            return False
        return self._dsh_tracker_wanted(config)

    # ---- 收口 ---------------------------------------------------------------
    def _start_stop_thread(self) -> None:
        threading.Thread(
            target=self._stop_harness_if_still_unwanted,
            daemon=True,
            name="pet-harness-stop",
        ).start()

    def _stop_harness_if_still_unwanted(self) -> None:
        """异步收口前的门复核：窗口期内联动又被打开则作废本次收口。"""
        if self._session_end_done():
            return
        if self._dsh_tracker_wanted(self._config):
            return
        try:
            harness_launcher.stop_self_launched_harness()
        except Exception:
            logger.exception("停止自拉起的 dsh 服务失败")

    # ---- 宿主状态 -----------------------------------------------------------
    def _shell(self):
        return getattr(self._host, "shell", None)

    def _quitting(self) -> bool:
        return bool(getattr(self._shell(), "_quitting", False))

    def _session_end_done(self) -> bool:
        return bool(getattr(self._shell(), "_session_end_done", False))

    def _dsh_tracker_wanted(self, config=None) -> bool:
        """DSH 联动门：与核心 ``AppShell._dsh_tracker_wanted`` 同口径。

        这里按配置键名 ``agent_link.dsh`` 自行读取，不 import 它的内部
        （模块与核心之间只共享配置契约）。
        """
        if config is None:
            config = self._config
        if config is None:
            return False
        try:
            agent_cfg = config.get("agent_link", {})
        except Exception:
            return False
        return bool(agent_cfg.get("dsh", False)) if isinstance(agent_cfg, dict) else False


def create(manifest: ModuleManifest) -> HarnessModule:
    return HarnessModule(manifest)


__all__ = ["HarnessModule", "create"]
