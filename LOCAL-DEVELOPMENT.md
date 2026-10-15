# Windows 本地运行与二次开发

适用范围：本地 Windows x64，2026-10-14 配置，源码基线 `b55f203`（上游 main / v4.3.0）。
项目功能及上游说明见 [README](README.md)，工程规则见 [AGENTS.md](AGENTS.md)，完整文档入口见 [docs/INDEX.md](docs/INDEX.md)。

## 启动

- 日常使用：双击根目录的 `start-local.bat`，无控制台窗口。
- 修改源码：运行根目录的 `dev.bat`，控制台保留诊断输出；修改后退出桌宠并重新运行。
- 退出：右键桌宠或系统托盘图标，选择应用退出。关闭控制台不是推荐的退出方式。

这两个入口都使用 `.venv\Scripts\python.exe` / `pythonw.exe`，不要求激活环境或配置系统 PATH。
上游原有 `run.bat` 依赖系统 `pythonw`，本机请使用上述本地入口。

## 环境与数据

| 路径 | 用途 |
|---|---|
| `.tools/python/` | 项目独立的 CPython 3.13.16；不要删除，否则虚拟环境失效。 |
| `.tools/uv/` | 环境安装工具 uv 0.13.1。 |
| `.venv/` | 项目运行与测试依赖。 |
| `.local/appdata/dsh-pet-standalone/` | 两个本地启动入口的设置、会话、用户角色及日志。 |
| `requirements.txt` | 上游运行与开发依赖约束。 |
| `requirements-local-windows.lock.txt` | 本次 Windows / Python 3.13.16 环境的精确依赖快照。 |

运行数据通过启动脚本中的进程级 `APPDATA` 设置保存在项目内；不会改变系统环境变量。
`.local/`、`.tools/`、`.venv/` 均已忽略，不要提交其中的数据或凭据。
需要备份设置和会话时，先退出桌宠，再备份 `.local/appdata/`。
不建议为开发目录开启开机自启，移动目录或重建环境会令自启路径失效。

## 重建或修复依赖

在项目根目录执行，首次需要访问 GitHub 和 PyPI：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-local.ps1
```

脚本在项目内准备 Python 和虚拟环境，优先安装锁定依赖，并检查依赖兼容性。
`ExecutionPolicy Bypass` 仅用于这次 PowerShell 进程，不修改系统执行策略。
日常启动不需要联网安装；AI 对话、在线语音等功能仍按各自功能要求联网。
AI 对话需在应用设置内填写自己的服务地址、模型与 API Key；桌宠动画无需 API Key。

移动项目目录后，虚拟环境中可能仍有旧的绝对路径：保留 `.tools/python/`，将 `.venv` 改名备份后重新执行安装脚本。
完整复制项目时可仅复制源码与锁文件，再运行安装脚本；不要把 `.venv` 当作可移动安装包。

## 开发入口

| 位置 | 修改内容 |
|---|---|
| `pet/__main__.py`、`pet/app.py` | 程序入口、应用生命周期与服务装配。 |
| `pet/overlay_shell.py`、`pet/pet_sprite.py` | 默认单合成窗口下的桌宠交互与渲染。 |
| `pet/config.py`、`pet/settings_*` | 配置与设置页；修改前先查工程规则及设置变更门。 |
| `pet/chat/` | AI 对话。 |
| `assets/characters/shenshen/` | 内置角色、动画与 manifest；也可按 README 使用外部角色目录。 |
| `tests/` | 回归测试。 |

已提供 `.vscode/settings.json` 和 `.vscode/launch.json`。用 VS Code 或兼容编辑器打开项目，
安装其 Python / Python Debugger 扩展后，选择 `Desktop Pet (local development)` 调试配置。
配置使用与两个批处理入口相同的解释器和运行数据目录。

本地分支为 `codex/local-setup`，`origin` 保留原 GitHub 仓库，当前配置文件尚未提交。
后续开发可先提交环境配置，再从本地分支切出功能分支。同步上游前先提交或暂存本地改动，
执行 `git fetch origin`，检查差异后合入 `origin/main`；避免直接用远程版本覆盖本地修改。

## 验证命令

在项目根目录运行，测试使用独立的 `.local/test-appdata`：

```powershell
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:APPDATA = Join-Path $PWD '.local/test-appdata'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check pet/ tests/
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_decode_fanout.py --ignore=tests/test_decode_fanout_integration.py
# 上一段通过后再运行：
.\.venv\Scripts\python.exe -m pytest -q tests/test_decode_fanout.py tests/test_decode_fanout_integration.py
```

分段顺序遵循 [ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md)。沙箱下若 pytest 临时目录报
`PermissionError`，应在普通本地终端运行，不要据此修改产品逻辑或关闭测试。
完成测试后关闭该终端，再通过 `dev.bat` 启动真实窗口，避免继承 `offscreen`。

有意调整依赖时，先按 `requirements.txt` 安装并验证，再更新 Windows 快照：

```powershell
.\.tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements.txt
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 requirements-local-windows.lock.txt
```

## 本机验证记录

- Python 3.13.16，PySide6 6.12.0；`pip check` 与 `ruff check pet/ tests/` 通过。
- 106 段内置动画已加载；OCR 三个模型及 PresentMon 文件均通过仓库提供的完整性校验脚本。
- 真实 `windows` Qt 平台启动并运行超过 13 秒，桌宠和灵动岛窗口可见，前后渲染画面发生变化，正常退出返回 0。
- 该次 2 个采样点 RSS 为 248.2 / 249.5 MiB，包含渲染抓图开销，仅为短时启动观测，不代表长时间内存或性能保证。
- 架构、运行依赖及设置/资源基础测试：41 passed。
- 本机多屏虚拟原点为 `(-1067, 0)`。上游 `tests/test_proactive.py` 的窗口裁剪用例只模拟画布、未模拟原点，单独复现为 `1 failed`；补齐测试原点输入后，该文件 `69 passed`（10.82 秒）。此处修改仅作用于测试夹具。
- 主套件完整初跑：`7468 passed / 15 skipped / 1 failed`，1356.60 秒；唯一失败为上述多屏测试。该进程在修正前已加载测试函数，保留了修正前结果，原始输出位于 `.local/full-tests.log`。
- 修正后主动识屏文件 `69 passed`；主套件结束后再次确认失败项为 `1 passed`（1.38 秒，`.local/capture-final.log`），随后共享解码两文件 `30 passed`（5.18 秒，`.local/decode-tests.log`）。本次只修改测试输入隔离，未再次整段重跑主套件；没有把初跑结果记为零失败。
- 尚未配置或验证个人 AI 服务、在线语音、音乐播放器联动及游戏帧率采集权限。
