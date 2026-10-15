"""Local focus-mode GUI evidence and microbenchmarks (isolated application data)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import timeit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def benchmark():
    from pet.focus_mode import FocusSession, normalize_focus_config
    state = FocusSession()
    result = {}

    def movement_gate():
        from pet.focus_mode import shared_focus_session
        return shared_focus_session().focusing

    for name, fn in (("idle_tick", state.tick),
                     ("inactive_movement_gate", movement_gate),
                     ("normalize_preferences", lambda: normalize_focus_config({}))):
        values = timeit.repeat(fn, number=100000, repeat=5)
        result[name + "_us"] = statistics.median(values) * 10
    state.start()
    for name, fn in (("running_tick", state.tick), ("running_label", state.label)):
        result[name + "_us"] = statistics.median(timeit.repeat(fn, number=100000, repeat=5)) * 10
    import gc
    import tracemalloc
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    allocated = [FocusSession() for _ in range(1000)]
    result["session_python_bytes_including_list_reference"] = (tracemalloc.get_traced_memory()[0] - before) / len(allocated)
    del allocated
    gc.collect()
    cycling = FocusSession()
    before = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    for _ in range(10000):
        cycling.start()
        cycling.stop()
    current, peak = tracemalloc.get_traced_memory()
    result["ten_thousand_cycles_retained_python_bytes"] = current - before
    result["ten_thousand_cycles_peak_python_bytes"] = peak - before
    tracemalloc.stop()
    return result


def gui(output):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QPlainTextEdit, QScrollArea
    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.dynamic_island import DynamicIsland
    from pet.focus_mode import shared_focus_session
    from scripts.capture_settings_pages import _apply_dark_palette

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    original_palette = app.palette()
    # OS boundary only: never inspect or change the real Windows login item.
    settings_mod.autostart_mod.is_enabled = lambda: False
    cfg = Config(base=output / "gui-data")
    cfg.set("focus_mode", {"work_context": "开发 Python 桌面应用；阅读官方文档、查资料和看相关教程都属于工作。"})
    observations = {"platform": app.platformName(), "layouts": []}

    def settle():
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()

    for dark in (False, True):
        if dark:
            _apply_dark_palette(app)
        else:
            app.setPalette(original_palette)
        dialog = settings_mod.ModernSettingsDialog(cfg, include_ai=True)
        try:
            dialog.show()
            dialog.search_edit.setText("工作背景")
            for width in (720, 1100, 1200):
                dialog.resize(width, 760)
                settle()
                editor = dialog.findChild(QPlainTextEdit, "focusWorkContext")
                scroll = dialog.pages.currentWidget().findChild(QScrollArea, "settingsScroll")
                assert editor is not None and editor.isVisible()
                assert scroll.horizontalScrollBar().maximum() == 0
                assert editor.width() >= 180
                label = f"{'dark' if dark else 'light'}-{width}"
                dialog.grab().save(str(output / f"settings-{label}.png"))
                observations["layouts"].append({"variant": label, "editor_width": editor.width(),
                                                "horizontal_overflow": 0})
        finally:
            dialog.close()
            app.processEvents()
        island = DynamicIsland(cfg)
        state = shared_focus_session()
        try:
            island.show()
            island.expand_card()
            settle()
            island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-idle.png"))
            island.collapse_card(animate=False)
            state.start(cfg.get("focus_mode"))
            settle()
            island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-running.png"))
            island.expand_card()
            settle()
            assert island._focus_controls.toggle.isVisible()
            assert island._focus_controls.end.isVisible()
            island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-card.png"))
            state.observation = "专注 AI 暂不可用：模型未配置或网络连接失败；番茄钟继续运行。"
            island.refresh_focus()
            settle()
            island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-error.png"))
            state.pause()
            settle()
            island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-paused.png"))
            samples = timeit.repeat(island.refresh_focus, number=100, repeat=5)
            observations[f"island_refresh_{'dark' if dark else 'light'}_ms"] = statistics.median(samples) * 10
            state.resume()
            original_clock = state.clock
            try:
                overdue = original_clock() + 7200
                state.clock = lambda: overdue
                assert state.tick(cfg.get("focus_mode"))
                assert state.phase == "short_break"
                island.refresh_focus()
                settle()
                island.grab().save(str(output / f"island-{'dark' if dark else 'light'}-break.png"))
            finally:
                state.clock = original_clock
        finally:
            state.stop()
            island.close()
            app.processEvents()
    return observations


def application(output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import psutil
    from pet.app import AppShell
    from pet.config import Config
    from pet.focus_mode import shared_focus_session
    from pet import click_sound

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    cfg = Config(base=output / "application-data")
    cfg.set("focus_mode", {"work_minutes": 1, "short_break_minutes": 1,
                           "screen_enabled": False, "check_minutes": 30})
    cfg.set("harness_autostart", False)
    cfg.set("voice_chime_enabled", False)
    cfg.set("festival_reminder_enabled", False)
    cfg.save()
    shell = AppShell(app, cfg, enable_chat=True)
    state = shared_focus_session()
    samples = []
    sounds = []
    process = psutil.Process()
    actual_play = click_sound.play_sound
    def record_play(path, volume=1.0):
        import time
        started = time.perf_counter()
        accepted = actual_play(path, volume=volume)
        if Path(path).name in ("start.wav", "done.wav"):
            record = {"file": Path(path).name, "accepted": accepted,
                      "milliseconds": (time.perf_counter() - started) * 1000,
                      "phase": state.phase, "status": state.status,
                      "rss_mib": process.memory_info().rss / 1048576}
            sounds.append(record)
            print("Native sound: " + json.dumps(record), flush=True)
        return accepted
    click_sound.play_sound = record_play
    shell.start()
    timer = QTimer()
    ticks = [0]
    started = [None]
    break_started = [None]

    def sample():
        import time
        ticks[0] += 1
        cpu = process.cpu_times()
        samples.append({"second": ticks[0], "rss_mib": process.memory_info().rss / 1048576,
                        "cpu_seconds": cpu.user + cpu.system, "phase": state.phase,
                        "status": state.status, "label": state.label(),
                        "focus_workers": sum(t.name == "focus-observation" for t in __import__('threading').enumerate())})
        if ticks[0] == 6:
            shell.island._focus_controls.toggle.click()
            started[0] = time.monotonic()
            assert state.focusing
            print("Native application: island button started a 60-second focus", flush=True)
        if ticks[0] == 12:
            shell.island.grab().save(str(output / "application-running.png"))
        if state.phase == "short_break" and break_started[0] is None:
            elapsed = time.monotonic() - started[0]
            assert state.completed == 1 and state.status == "running"
            break_started[0] = time.monotonic()
            shell.island.grab().save(str(output / "application-break.png"))
            count = len(sounds)
            shell.island._focus_controls.toggle.click()
            assert state.status == "paused"
            shell.island._focus_controls.toggle.click()
            assert state.status == "running"
            assert len(sounds) == count
            print(f"Native application: automatic break after {elapsed:.3f}s; pause/resume stayed silent", flush=True)
        elif state.focusing and break_started[0] is not None:
            elapsed = time.monotonic() - break_started[0]
            assert state.completed == 1
            shell.island._focus_controls.end.click()
            assert not state.engaged
            assert [event["file"] for event in sounds] == ["start.wav", "done.wav", "start.wav", "done.wav"]
            assert all(event["accepted"] for event in sounds)
            print(f"Native application: automatic focus after {elapsed:.3f}s; start / both boundaries / stop sounds accepted", flush=True)
            timer.stop()
            app.exit(0)
        if ticks[0] > 160:
            app.exit(2)

    timer.timeout.connect(sample)
    timer.start(1000)
    try:
        code = app.exec()
    finally:
        click_sound.play_sound = actual_play
    assert code == 0
    return {"samples": samples, "sample_count": len(samples), "sounds": sounds, "platform": app.platformName()}


def live_ai(output, profile_base):
    from urllib.parse import urlparse
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from pet import vision
    from pet.config import Config
    from pet.focus_mode import FocusSession
    from pet.focus_service import FocusController
    from pet.settings_slot_config import route_settings_config

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    real = route_settings_config(Config(base=profile_base, instance_id="slot-0"))
    provider = real.chat_settings().active_config
    if not real.resolve_api_key(provider):
        return {"verified": False, "reason": "No configured API credential"}

    class TestWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.messages = []
            self.setWindowTitle("Focus Mode Verification - Controlled Test Window")
            self.resize(850, 500)
            layout = QVBoxLayout(self)
            self.body = QLabel(self)
            self.body.setWordWrap(True)
            self.body.setStyleSheet("font-size: 28px; color: #111; background: white; padding: 24px;")
            layout.addWidget(self.body)

        def has_presentation_target(self):
            return self.isVisible()

        def show_bubble(self, text, duration_ms=0):
            self.messages.append(text)

    window = TestWindow()
    window.show()
    window.activateWindow()
    test_hwnd = int(window.winId())
    actual_foreground = vision.foreground_window_info

    def controlled_foreground():
        info = actual_foreground()
        if info is None or int(info["hwnd"]) != test_hwnd:
            raise RuntimeError("Controlled test window lost foreground; capture cancelled")
        return info

    vision.foreground_window_info = controlled_foreground
    results = []
    try:
        for index, text in enumerate((
            "PySide6 官方文档学习笔记\n\nQTimer 用法：\n创建 QTimer 对象；连接 timeout 信号；调用 start(1000)。\n\n本轮目标：学习 Python / Qt 的定时器。",
            "娱乐视频推荐\n\n搞笑猫咪合集：猫猫把纸箱撞翻了\n美食探店：这家炸鸡也太好吃了\n游戏直播：主播今天又输了\n\n随便刷刷，暂时不学习编程。",
        )):
            window.body.setText(text)
            window.activateWindow()
            loop = QEventLoop()
            QTimer.singleShot(500, loop.quit)
            loop.exec()
            controlled_foreground()  # Never upload a window belonging to another app.
            cfg = Config(base=output / f"live-ai-{index}")
            cfg.set_chat_settings(real.chat_settings())
            cfg.set("focus_mode", {"work_context": "学习 Python / PySide6 的 QTimer 定时器。相关技术文档和教程属于工作。"})
            window.cfg = cfg
            state = FocusSession()
            controller = FocusController(cfg, window, identity_config=lambda: real, session=state, parent=app)
            try:
                state.start()
                controller.request_observation()
                poll = QTimer()
                poll.setInterval(20)
                poll.timeout.connect(lambda: loop.quit() if not controller._busy else None)
                poll.start()
                QTimer.singleShot(200000, loop.quit)
                loop.exec()
                poll.stop()
                record = {"case": "related_document" if index == 0 else "unrelated_entertainment",
                          "observation": state.observation, "spoken": window.messages[-1:]}
                results.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)
            finally:
                controller.stop()
    finally:
        vision.foreground_window_info = actual_foreground
        window.close()
    return {"api_host": urlparse(provider.base_url).hostname,
            "vision_model": vision.resolve_vision_model(provider), "controlled_window_only": True,
            "results": results}


def stress_tests(output):
    import subprocess
    import time
    import psutil
    workers = []
    results = []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        for _ in range(os.cpu_count() or 1):
            workers.append(subprocess.Popen([sys.executable, "-c", "while True: pass"],
                                            creationflags=flags, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL))
        load = psutil.cpu_percent(interval=1)
        for run in range(1, 4):
            started = time.perf_counter()
            log = output / f"stress-{run}.log"
            with log.open("w", encoding="utf-8") as stream:
                process = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "-o", "cache_dir=.local/pytest-cache",
                     "tests/test_focus_mode.py", "tests/test_focus_service.py", "tests/test_single_process_shared.py"],
                    stdout=stream, stderr=subprocess.STDOUT, timeout=300,
                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, creationflags=flags)
            result = {"run": run, "exit_code": process.returncode,
                      "seconds": time.perf_counter() - started, "cpu_load_percent": load,
                      "summary": log.read_text(encoding="utf-8").splitlines()[-1]}
            results.append(result)
            print(json.dumps(result), flush=True)
            if process.returncode:
                raise RuntimeError(f"Stress run {run} failed; inspect {log}")
            load = psutil.cpu_percent(interval=1)
    finally:
        for worker in workers:
            worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)
    return {"worker_count": len(workers), "runs": results}


def suite_tests(output, part="all"):
    """Run every collected case once, isolating accumulated native Qt state."""
    import re
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1"}
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                               env=env, capture_output=True, text=True, encoding="utf-8",
                               creationflags=flags, timeout=120)
    (output / "collection.log").write_text(collected.stdout + collected.stderr, encoding="utf-8")
    ids = [line for line in collected.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    count = re.search(r"(\d+) tests? collected", collected.stdout)
    assert collected.returncode == 0 and count and len(ids) == int(count[1]), "Incomplete collection"
    assert len(ids) == len(set(ids)), "Duplicate collected cases"
    decode = {"tests/test_decode_fanout.py", "tests/test_decode_fanout_integration.py"}
    files = sorted({node.split("::", 1)[0] for node in ids})
    groups = {Path(f).stem: [f] for f in files if f not in decode and Path(f).name < "test_q"}
    groups.update({"q-onward": [f for f in files if f not in decode and Path(f).name >= "test_q"],
                   "decode": sorted(decode)})
    assigned = [f for group in groups.values() for f in group]
    assert set(assigned) == set(files) and len(assigned) == len(set(assigned)), "Coverage gap"
    (output / "inventory.json").write_text(json.dumps({"cases": len(ids), "groups": groups,
        "case_counts": {name: sum(node.split("::", 1)[0] in group for node in ids)
                        for name, group in groups.items()}}, indent=2), encoding="utf-8")

    def run(name):
        import time
        started = time.perf_counter()
        directory = output / name
        directory.mkdir(exist_ok=True)
        run_env = {**env, "APPDATA": str(directory / "appdata"), "DSPET_TEST_DIAG_DIR": str(directory)}
        command = [sys.executable, "-m", "pytest", "-q", "-o", f"cache_dir={directory / 'cache'}",
                   f"--junitxml={directory / 'results.xml'}", *groups[name]]
        with (directory / "pytest.log").open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, env=run_env, stdout=stream, stderr=subprocess.STDOUT,
                                     creationflags=flags, timeout=2400)
        record = {"group": name, "exit_code": process.returncode,
                  "seconds": time.perf_counter() - started,
                  "tail": (directory / "pytest.log").read_text(encoding="utf-8").splitlines()[-6:]}
        (directory / "summary.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record), flush=True)
        return record

    selected = ([name for name in groups if name not in ("q-onward", "decode")]
                if part == "before-q" else [part] if part != "all"
                else ["q-onward"] + [name for name in groups if name not in ("q-onward", "decode")])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, selected))
    assert all(item["exit_code"] == 0 for item in results), "Partitions failed; inspect logs"
    if part == "all":
        results.append(run("decode"))
        assert results[-1]["exit_code"] == 0, "Decode partition failed"
    return {"collected_cases": len(ids), "part": part,
            "selected_cases": sum(node.split("::", 1)[0] in groups[name]
                                  for name in selected for node in ids)
                              + (sum(node.split("::", 1)[0] in decode for node in ids)
                                 if part == "all" else 0), "runs": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".scratch/focus-mode/evidence"))
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--application", action="store_true")
    parser.add_argument("--live-ai", action="store_true")
    parser.add_argument("--profile-base", type=Path, default=Path(".local/appdata"))
    parser.add_argument("--stress-tests", action="store_true")
    parser.add_argument("--suite-tests", action="store_true")
    parser.add_argument("--suite-part", choices=("all", "before-q", "q-onward", "decode"), default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(output / "appdata")
    result = {"python": sys.version.split()[0]}
    if args.suite_tests:
        result.update(suite_tests(output, args.suite_part))
        filename = "suite.json"
    elif args.stress_tests:
        result.update(stress_tests(output))
        filename = "stress.json"
    elif args.live_ai:
        result.update(live_ai(output, args.profile_base))
        filename = "live-ai.json"
    elif args.application:
        result.update(application(output))
        filename = "application.json"
    elif args.gui:
        result.update(gui(output))
        filename = "gui.json"
    else:
        result.update(benchmark())
        filename = "benchmark.json"
    (output / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
