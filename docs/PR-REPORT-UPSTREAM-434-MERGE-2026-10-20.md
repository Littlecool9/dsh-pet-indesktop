# 上游 v4.3.4 合并到本地专注模式分支

日期：2026-10-20（America/Los_Angeles）。本地父提交 `57ee8d7`，上游父提交
`147170f`，共同基线 `b55f203`，分支 `codex/focus-mode`。本报告记录这一次本地合并，
不是新发布或跨平台验收。用户授权保留专注模式并同步上游，重点为歌词、截图和多屏；
未授权推送或发布。

相关入口：[文档索引](INDEX.md)、[专注模式原报告](PR-REPORT-FOCUS-MODE-2026-10-15.md)、
[上游 v4.3.4 发布说明](RELEASE-v4.3.4.md)、[合并纪律](PR-MERGE-LESSONS-2026-09-12.md)、
[本机开发环境](../LOCAL-DEVELOPMENT.md)。

## 一、核心特性与合并边界

- 引入上游 44 个提交（v4.3.0 → v4.3.4），保留本地 4 个提交：运行环境、角色人设、
  专注模式、自动循环/阶段音效、手动结束鼓励及最近十次文字工作记录。
- 歌词与截图主体文件采用上游实现；`overlay_shell.py` 相对上游仅保留原有两处
  专注期自言自语门禁（每处 3 行），多屏宿主、跨屏投影、持久化等沿用上游。
- 两处用户未提交修改先备份并 stash，验收完成后按原内容恢复为未提交修改，不混入本次提交。
  回退分支：`codex/backup-before-upstream-434-20261019`。
- 配置没有另造一份真值；`focus_mode` 保持全局，原有每宠配置继续走上游档案路由。
  不更改用户的歌词或跨屏偏好；跨屏仍由「常规 → 窗口与系统 → 允许桌宠跨屏」控制，
  保存后重启生效。
- 文件保真核对：25 个文件有双方改动；除两处纯空行清理，327 个仅上游修改的文件
  与 `origin/main` 完全一致。本地独有文件相对原父提交也无意外差异（只给本地开发文档
  增加当前整合说明）。核对结果：`fidelity.json` 两组 unexpected 均为空。

## 二、修改文件说明

这次没有为已有功能另写实现。上游 354 个文件的行为与证据见仓库内各版本发布说明和
对应 PR 报告。本表列出人工解决的冲突与合并卫生改动；不是用整文件 ours/theirs 覆盖。
增删基线在表内明确区分，避免把专注模式的既有实现计成新功能。

| 文件 | 相对上游增删 | 解决方式与原因 |
|---|---:|---|
| `README.md` | +15 / -1 | 保留上游用户主页；补回本机开发入口、专注模式说明和本地官方视觉型号映射说明。 |
| `docs/INDEX.md` | +7 / -1 | 同时保留上游新报告、本地环境/人设/专注报告；登记本报告。 |
| `docs/SETTINGS-CHANGE-GATES.md` | +31 / -0 | 上游新增设置记录与专注模式全局契约全部保留。 |
| `pet/config.py` | +5 / -0 | 同时保留 `music_players` 与专注配置归一化导入；reload 白名单同时接纳 `focus_mode` 与 `todo_reminder_speak`。 |
| `pet/settings_page_guide.py` | +1 / -0 | 同时保留「专注模式」和上游「作者账号」说明，不丢分区描述。 |
| `tests/test_architecture.py` | +3 / -1 | 保留上游完整预算历史；设置对话框实测 2603 行 = 上游 2600 + 专注装配 3 行，按实测校准。 |
| `tests/test_proactive.py` | +0 / -0 | 采用上游更完整的 Win32 虚拟原点隔离；与本地旧修正同一目的，不改产品裁剪。 |
| `docs/PR-REPORT-ANDROID-PET-MODULES-PERF-2026-10-15.md` | +0 / -1 | 删除上游文件末尾多余空行，使合并差异通过 whitespace 检查。 |
| `tests/test_overlay_seam_passage.py` | +0 / -1 | 仅删除末尾多余空行；测试逻辑及断言未改。 |
| `LOCAL-DEVELOPMENT.md` | 相对本地父提交 +5 / -0 | 补当前上游同步基线与本报告入口，旧环境验证数字明确作为历史记录。 |
| 本报告 | 新增 +179 / -0 | 保存本地整合、实测、限制与恢复证据。 |

用户原始两文件已经逐字节恢复：manifest 的 SHA256 为
`cef43f7d48ef4082f7d3dde764edb2e47f03719ba4506e3be5652a1baee1beaf`，
人设报告为 `818d5a955ce2a953f4af4dfe1683f1357ad81d4f34e6c921a6eed36bd9477a98`。
二者均不在暂存区；备份文件与本次 stash 保留。最终 numstat 见文末。

## 三、性能分析

环境：Windows x64、项目独立 CPython 3.13.16、PySide6 6.12.0；两块活动屏，DPR 均为 1.5。
下面是这次运行的数字，不把旧版报告或上游作者机器上的数据作为本机实测。

命令（均使用 `.venv/Scripts/python.exe`）：

```powershell
python scripts/verify_focus_mode.py --output .scratch/upstream-434-merge/benchmark
python scripts/verify_focus_mode.py --gui --output .scratch/upstream-434-merge/gui
python .scratch/upstream-434-merge/native_smoke.py
python .scratch/upstream-434-merge/io_probe.py
```

| 路径 | 样本量 | 本次实测 |
|---|---:|---:|
| 空闲专注 tick | 100000 × 5，中位 | 0.053143 µs/次 |
| 非专注期走动门禁 | 100000 × 5，中位 | 0.290740 µs/次 |
| 运行中专注 tick | 100000 × 5，中位 | 0.157411 µs/次 |
| 专注标签格式化 | 100000 × 5，中位 | 1.459228 µs/次 |
| 岛专注刷新，明/暗 | 各 100 × 5，中位 | 5.020730 / 5.059641 ms/次 |
| 一万次专注 start/stop | 10000 次，tracemalloc | 保留 +452 B，峰值 +532 B |
| 跨屏落位命令 | 两块真实屏，各 1 次 | 0.3717 / 4.7259 ms |
| 受控截图本地 OCR | 1095×330，1 次冷运行 | 3.903129 s |
| 实际歌词请求 | 两首，各 1 次，不读缓存 | 1.230391 / 1.297826 s |

稳态：本次冲突解决没有引入新的循环、timer、网络请求、磁盘路径或线程；专注的既有
服务与门禁保留。相对旧 v4.3.0 的整套性能差异没有做配对对照，不能声称加速。
上游新增路径包括按需 OCR 子进程、歌词直连失败后的有界代理回退、TTS 后端及多屏宿主；
本次未另加重试或扩展请求预算。

真实 AppShell 运行 14.998 s、15 个一秒采样点，RSS 首点 239.191 MiB、末点 48.316 MiB，
最小 22.652 MiB、最大 261.625 MiB。区间 CPU 平均占用约 94.42% 的单核，包含启动、动画、
两次跨屏、抓图和内存回收，且与回归进程并行；不是功能净增量或稳态基准。
这段短运行不能证明长期无泄漏，tracemalloc 也不覆盖 Qt/native 堆。

## 四、实机运行记录

全部使用 `.scratch/upstream-434-merge/` 下隔离的 APPDATA；未停止用户已有桌宠，
未访问真实模型凭据，未发送付费模型请求，未更改日常设置。

### Windows 双屏与专注模式

实际 Qt 屏幕枚举：

```text
GP3201: DPR=1.5, available=(0, 0, 2560, 1400)
\\.\DISPLAY1: DPR=1.5, available=(-1600, 558, 1067, 1667)
hosts=2, sprites=1
focus_commands=start/pause/resume/stop passed
status=passed, exit=0
```

经 `move_sprite_to_screen` 的产品入口依次在两块屏落位，确认实际宿主与 `home_screen`
一致，副屏的渲染截图可见宠物；退出后隔离 `config-slot-0.json` 的 `screen_name`
确实为 `\\.\DISPLAY1`。这验证真实屏幕与窗口链路，不冒充人工鼠标拖拽验收。
跨屏拖拽/投影的真实 Qt 事件回归由聚焦测试覆盖。

明/暗 × 720/1100/1200 宽设置页共 6 组，横向溢出均为 0；工作背景编辑器宽
420 / 766 / 766 px。已查看窄窗暗色、专注卡片和运行态截图，专注文案及按钮完整。
截图保存在 `gui/`、`native/`；第一次同步瞬间抓到旧时间与新标签重叠，事件落定后的
`gui/island-dark-card.png`、`island-dark-running.png` 正常，未据瞬态截图改动布局。

### 截图与歌词

从仅含测试文字的真实 QLabel 窗口抓图，不采集用户其它窗口。OCR 原样输出：

```text
Working on two of these
Desktop pet screenshot test
```

完整句子未被拆成逐词换行。实际公开端点返回：

```text
晴天 / 周杰伦: found=true, lines=44, seconds=1.2303915
Yellow / Coldplay: found=true, lines=49, seconds=1.2978259
```

未在本轮让用户播放器点播、未发起真实翻译/截图问答 API；所以不把「公开歌词端点可用」
说成用户播放器时间轴端到端验证，也不把 OCR 成功说成翻译模型成功。
当前重点功能的控制器/设置/结果展示由聚焦和全量测试另行覆盖。

## 五、回归验证与限制

- `python -m ruff check pet/ tests/`：通过。
- `python -m pip check`：`No broken requirements found.`
- 19 文件聚焦回归：**838 passed / 0 failed / 0 skipped**，144.917 s 墙钟。
- CPU 满载三轮：16 个负载进程，三轮各 **41 passed / exit 0**，墙钟
  44.224 / 58.145 / 59.792 s，三轮前 CPU 采样均 100%。使用仓库已有
  `verify_focus_mode.py --stress-tests`，测试专注状态/服务与进程共享装配；
  每轮 warning 详见 `stress/stress-*.log`，负载进程由脚本 `finally` 全部清理。
- 首次单进程组合在设置用例处长时间停滞，保留 `focused.log` 后终止该测试进程；
  同一用例独立运行 **1 passed / 2.89 s**。按
  [验收文档](ACCEPTANCE_TESTS.md) 的既有 Qt 隔离约定改为逐文件独立进程，
  不删用例、不放宽断言，不宣称已找到停滞根因。
- 全量最终覆盖：**8431 passed / 17 skipped / 0 failed / 0 errors**，
  **8448 cases / 396 files**，每文件独立 Qt 进程、最多两并发；末尾两个共享解码文件
  独立通过 29 + 1 项。主运行墙钟 1475.126 s，GPU 完整文件复验另用 5.892 s。
  每文件日志、JUnit、退出码与完整 node ID 清单均保留。
- 初次清单为 8446 项；写入本报告让自动报告守卫增加两例，实际逐文件运行已执行这
  两例。因此初次 runner 的汇总同时记录了旧清单不匹配与 GPU 首轮失败，不能直接
  当作全绿。最终用 `reconcile.py` 再收集 8448 个唯一 node ID，与 396 个成功文件
  的 JUnit 节点逐项一一核对（GPU 选成功的完整复验），无漏跑、无重复。
  `full/initial-summary.json` 保留初次失败汇总，`full/final-verification.json` 记录
  最终对账，`full/summary.json` 带 `inventory_reconciled_against_junit=true`。
- 中途一条 GPU 真实 PDH 探针失败：首拍 6.318 s、第二拍仍 `sampling`，后续 warm
  已为 `ok`。该文件和产品 GPU 实现相对本地父提交及上游均无差异；当时与 CPU 满载
  复跑并行。负载结束后原样重跑完整 `tests/test_gpu_monitor.py`：
  **58 passed / 0 failed / 5.892 s**。不修改断言或 GPU 代码，不声称已找到全部时序根因；
  `full/test_gpu_monitor/` 保留首次失败，`full-reruns/test_gpu_monitor/` 保留复验。
  最终覆盖核对采用完整文件成功结果，不把首轮失败计成成功。

全量命令：

```powershell
python .scratch/upstream-434-merge/run_tests.py .scratch/upstream-434-merge/full
```

已知上游边界仍以 [v4.3.4 说明](RELEASE-v4.3.4.md) 为准；本次不是对所有 150% DPI
故障的根因修复。未验不同 DPR 组合、真实拔插屏幕、跨屏缝碰撞、macOS/Linux 或打包产物。
没有新增持久设置或改设置布局，因此没有另加设置迁移/平台规则；原设置契约、Tab/搜索/
保存、菜单与焦点回归在现有套件中执行。未推送、未创建 PR、未发布。

## 六、最终差异统计

相对本地父提交 `57ee8d7`，合并提交共 356 个文件，新增 54161 行、删除 4087 行；
原始用户修改的两个文件不计入。上游原提交与本地原提交均保留，没有 squash 或重写历史。
