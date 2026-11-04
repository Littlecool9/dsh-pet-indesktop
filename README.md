# dsh-pet（Windows 模块化桌面宠物）

基于 **Python + PySide6** 的 Windows 桌面宠物，是本仓库的个人硬分叉版本：只支持
Windows，只跑一只桌宠，核心（窗口 / 动画 / 交互 / 菜单 / 设置）与功能模块分离，
并通过本机 SurfCore 获得人格、记忆与陪伴对话能力。

> 本仓库不再跟随上游更新，也不再提供 macOS / Linux / Android 产物。工程约定见
> [AGENTS.md](AGENTS.md)，领域术语见 [CONTEXT.md](CONTEXT.md)，全部文档入口见
> [docs/INDEX.md](docs/INDEX.md)。

## 它是什么

- 透明、无边框、置顶、可拖动、可切换角色的桌面宠物，动画走 WebM / 帧序列。
- **单宠、单合成窗**：slot 0 是唯一桌宠；一张透明窗铺满整个虚拟桌面，跨屏开关
  （默认关）打开后宠可在同一张窗里自由跨屏。
- **模块化功能**：AI 对话窗、快速对话、灵动岛、专注模式、自言自语、待办、余额、
  网络信息、全局快捷键、快捷启动、Harness 启动器、SurfCore 连接等都通过
  `pet/modules/<id>/` 接入；删掉模块目录和清单里的一行就彻底移除该功能。
- **Windows 专用**：托盘、自启、Win32 边缘/全屏探测、本地 OCR 子进程都按 Windows
  实现；不存在其他平台的构建分支。

## 运行

要求：Windows 10/11 x64，Python 3.13（见 `.python-version`），依赖已安装。

```powershell
# 在仓库根目录
.\.venv\Scripts\python.exe -m pet
```

仓库自带几个入口：

| 入口 | 用途 |
|---|---|
| `start-local.bat` | 日常启动，无控制台；使用 `.venv` 与项目内 `.local/appdata`。 |
| `dev.bat` | 开发启动，保留控制台诊断输出；同样用 `.venv` 与项目内数据目录。 |
| `run.bat` | 使用系统 PATH 上的 `pythonw -m pet`（适合依赖已装进系统 Python 的机器）。 |

首次准备环境、重建依赖和本地数据目录见
[LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md)。设置页可用
`python -m pet --settings` 单独拉起；`--ocr-worker` 和 `--uninstall-cleanup` 是内部
子进程入口，不需要手动调用。

数据目录默认由 `Config` 决定（开发入口在 `.local/appdata/`）；每宠设置保存在
`config-slot-0.json`，全局设置在 `config.json`。备份或迁移时退出桌宠后整目录复制。

## 功能

- 桌宠窗口：点击动画、拖动、转向、边缘探头、跨屏（默认关）、点击音效、托盘、免打扰。
- 设置与菜单：独立设置进程、菜单布局编辑、模块菜单按运行时状态置灰并说明原因。
- **助手线**：完整 AI 对话窗、看看屏幕 / 截图提问 / 主动识屏；直连用户配置的
  API，人设取自 SurfCore 人格卡（离线用最后一次缓存）。
- **陪伴线**：快速气泡、灵动岛对话、主动搭话、自言自语；经 SurfCore 的本机
  pet-api，离线时如实说明并回退本地台词预设。
- 模块：专注模式（番茄钟）、待办提醒、DeepSeek 余额、网络信息、全局快捷键、
  快捷启动、DeepSeek Harness 启动器、SurfCore 连接。

## 设置与生效

设置窗**关闭即自动保存并立即生效**（直接点 X 也保存）。少数几项要重启或重新登录才生效：

- **三个例外**（照常保存，但当前进程不按新值跑）：`允许桌宠跨屏` 要**重启**后生效；`直播捕获兼容` 要**重启**后生效；`帧率采集权限` 要**注销或重新登录**后才生效。后两项所属功能已在本 fork 删除，保留这一行只为与历史设置文案对齐。

### DeepSeek Harness 与自启

- 右键菜单的 **DeepSeek Harness** 子菜单与托盘菜单提供「启动 dsh web 界面 / 启动桌面端界面 / 重启 / 停止」。启动器会探测 PATH 上的 `dsh`、Node 全局包，再回退 `npx @deepseek-ai/dsh`；已在本机运行的 dsh web 会被复用。
- 设置里的「随桌宠启动 dsh 服务」只在 DSH 联动同时开启时生效；联动关着时不会拉起 dsh web；关闭开关只停止后续自启，唯一例外是在桌宠拉起探测期间关掉开关，那一次刚拉起的实例会被立刻收掉。
- 「重启 / 停止服务」带确认框并核对 PID / 端口；退出桌宠只收掉自己拉起的 dsh，不会停掉用户自己启动的服务。

### 全局快捷键（设置 → 互动 → 快捷键，默认不绑）

三个动作各录一个系统级组合键，在别的程序前台时也生效：

- 三个动作：**AI 对话**、**看看屏幕**、**截图提问**（与右键菜单同一条入口）。
- **默认全空**，一个键都不绑；右键菜单照常可用。
- **必须带修饰键**（Ctrl / Alt / Shift / Win 之一）：单独一个键会抢走打字输入，录入时会被拒。
- **只有 Windows 注册**；被别的程序占用时那条不生效，设置页会在行内提前写明后果。
- 改完点「保存并退出」即生效，不用重启。

## AI 配置

「设置 → AI 与对话 → 模型与连接」里只需要填 **API Key**；默认地址 `https://api.deepseek.com`、模型 `deepseek-v4-flash` 通常不用改。填完点侧栏底部的 **「保存并退出」**（AI 页没有单独的存档按钮），再点「测试连接」。

托盘菜单的「AI 设置」打开的就是同一个「AI 与对话」页；右键菜单里没有这个入口。API Key 优先存系统钥匙串，钥匙串不可用时才回退到配置文件。视觉能力在同页「视觉能力」里配置，可复用聊天模型或单独填写。

## SurfCore 集成（简述）

`surfcore/` 是完整的 SurfCore Node/DSH 插件（QQ 桥接、记忆、人格、额度、控制台），
以子目录形式合入本仓库；它不是 Python 运行时，也不需要随桌宠打包。

桌宠是它的客户端：`pet/modules/surfcore/` 从
`~/.dsh/surfcore/pet/host.json` 发现本机实例，只访问回环地址并带 pet token，
长轮询事件、维护在线状态、同步专注状态。`pet/surfcore_link.py` 是核心侧接缝：
缓存人格卡、查额度、上报 token 用量、领取主动搭话额度；所有调用都走后台线程，
GUI 线程不直接发 HTTP。SurfCore 未安装 / 未启动时，桌宠照常运行，陪伴线显示
不可用原因，助手线继续直连 API 并使用缓存人格。

Agent 联动会忽略 SurfCore 的 QQ 会话（`qq-chat*` preset），只对真正的 agent
展示状态（D7）。

## 代码在哪里

| 位置 | 内容 |
|---|---|
| `pet/__main__.py`、`pet/app.py` | 入口、`AppShell`、进程级服务与模块注册表装配。 |
| `pet/overlay_shell.py`、`pet/screen_host.py`、`pet/pet_sprite.py`、`pet/tick_driver.py` | 合成窗、屏宿主、宠物精灵与唯一 tick 定时器。 |
| `pet/modules/__init__.py` | `MODULES` 清单：删模块就是删目录 + 删一行。 |
| `pet/modules/base.py`、`registry.py`、`host.py`、`pet/module_host.py` | 模块清单、字符串入口、依赖排序、宿主服务表 / 事件总线。 |
| `pet/modules/<id>/` | 一个功能一个包；`__init__.py` 只放 `MANIFEST`。 |
| `pet/context_menus/`、`pet/settings_*.py` | 菜单与设置框架；设置进程只读模块清单和入口，不启动模块运行时。 |
| `surfcore/` | SurfCore 本体（Node/DSH 插件）。 |
| `tests/` | 回归测试；模块边界与打包契约见 `test_module_architecture.py`、`test_module_packaging.py`。 |
| `scripts/build_onedir.ps1`、`packaging/` | Windows onedir / 安装包构建；模块由 `--collect-submodules pet.modules` 收集。 |

模块规则（由测试守住）：核心不 import `pet.modules.<id>`，模块之间不互相 import；
能力通过宿主服务表 / 事件总线传递；模块清单里的所有入口都是字符串
（`"pkg.mod:attr"`），由 `importlib` 惰性解析。

## 开发与验证

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m ruff check pet/ tests/ scripts/
.\.venv\Scripts\python.exe -m pytest -q -n 2
```

`n` 不要用 `auto`：本机全量并行会吃满内存。改动模块、打包或设置时先看
[AGENTS.md](AGENTS.md) 的 Context pointers；打包细节见
[docs/ONEDIR_PACKAGING.md](docs/ONEDIR_PACKAGING.md)。

## 许可证

代码与素材许可见 [LICENSE](LICENSE)；第三方组件、字体、动画素材与内置音效的授权见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
