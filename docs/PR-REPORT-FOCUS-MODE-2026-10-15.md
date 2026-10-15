# 专注模式交付报告（2026-10-15）

> 基线：`f08e9f0`，备份分支 `codex/baseline-before-focus-20261015`。
> 开发分支：`codex/focus-mode`；平台：Windows 10，CPython 3.13.16 / PySide6 6.12.0。
> 关联：[用户功能说明](../README.md)、[设置准入记录](SETTINGS-CHANGE-GATES.md)、
> [Focus Session 契约](../CONTEXT.md)、[Qt 完整回归顺序](ACCEPTANCE_TESTS.md)。

## 一、核心特性

工作背景在设置里填写一次、长期保存；专注时自动附加角色人设与背景。一个进程一份
番茄钟，所有宠物共享；灵动岛显示倒计时、展开卡片操作，右键菜单提供恢复入口。
默认 25/5/15 分钟，每四轮长休息；阶段结束后等待用户开始下一段。
专注暂停随机走动，保留任务相关的人设鼓励；Windows 下可看前台窗口，判断相关、
可能偏离或信息不足。相关教程不因“是视频”而判分心，信息不足保持安静。

检查默认三分钟，偏离提醒至少间隔五分钟；每日默认 100 次实际 HTTP 请求含重试。
普通识屏在专注阶段让路，免打扰保持独立。暂停、修改背景、结束或退出后迟到结果
不再说话；暂停/退出在发送前取消未发出的网络请求。走动门禁只作用于 normal 行为，
不改写抛掷物理接管的速度。API 故障显示真实原因，不停计时。

## 二、修改文件说明

本次不删除文件、不新增依赖或随包二进制。已跟踪文件用 `git diff --numstat f08e9f0`，
新增文本按实际行数统计；新增截图为二进制，另列大小。以下仅包含本功能差异。

<!-- FILES_BEGIN -->
| 文件 | 增删 | 改了什么、为什么 |
|---|---|---|
| `CONTEXT.md` | +11 / −0 | 定义进程共享的 Focus Session，明确运行态、全局偏好与免打扰边界。 |
| `README.md` | +10 / −1 | 补充使用路径、循环、费用/识屏边界，并更新官方视觉型号说明。 |
| `docs/ACCEPTANCE_TESTS.md` | +33 / −0 | 记录本机两轮同点原生崩溃与独立进程验收顺序，保持全部测试覆盖。 |
| `docs/INDEX.md` | +1 / −0 | 登记交付报告，保证新文档可发现。 |
| `docs/PR-REPORT-FOCUS-MODE-2026-10-15.md` | +234 / −0 | 新增；新增交付证据，记录行为、测试、实机、性能与回滚。 |
| `docs/SETTINGS-CHANGE-GATES.md` | +24 / −0 | 登记八个全局偏好的默认值、保存、能力与恢复契约。 |
| `docs/screenshots/focus-mode/island-card.png` | 二进制 32.3 KiB | 新增；保存实际 Windows 窄/深色设置或岛运行/错误态截图，作为视觉证据。 |
| `docs/screenshots/focus-mode/island-error.png` | 二进制 36.3 KiB | 新增；保存实际 Windows 窄/深色设置或岛运行/错误态截图，作为视觉证据。 |
| `docs/screenshots/focus-mode/island-idle.png` | 二进制 31.8 KiB | 新增；保存实际 Windows 窄/深色设置或岛运行/错误态截图，作为视觉证据。 |
| `docs/screenshots/focus-mode/settings-dark-1100.png` | 二进制 126.1 KiB | 新增；保存实际 Windows 窄/深色设置或岛运行/错误态截图，作为视觉证据。 |
| `docs/screenshots/focus-mode/settings-light-720.png` | 二进制 113.4 KiB | 新增；保存实际 Windows 窄/深色设置或岛运行/错误态截图，作为视觉证据。 |
| `pet/app.py` | +2 / −0 | 将共享计时状态的刷新信号连接到灵动岛。 |
| `pet/chat/settings_dialog.py` | +1 / −1 | 更正视觉自动选择说明，避免继续把官方模型称为预览版。 |
| `pet/config.py` | +5 / −0 | 登记全局 focus_mode 默认值、归一化与热重载白名单。 |
| `pet/context_menus/registry.py` | +4 / −2 | 登记专注命令、标准名称和语义图标，菜单预览同源。 |
| `pet/dynamic_island.py` | +53 / −3 | 加入倒计时和控制区，保持宽度/高度账目；清理原生销毁后的订阅。 |
| `pet/focus_mode.py` | +192 / −0 | 新增；新增无 Qt 的截止时间状态机、配置归一化、任务提示词和保守结果解析。 |
| `pet/focus_service.py` | +243 / −0 | 新增；新增 Qt 主线程计时、串行后台请求、额度/冷却、代次和故障显示。 |
| `pet/focus_ui.py` | +85 / −0 | 新增；新增灵动岛及菜单共用命令，按钮可访问名称、运行状态和错误说明。 |
| `pet/menu_templates/modern-default-v1.json` | +1 / −0 | 在工具区加入专注入口，关闭岛时仍能暂停或结束。 |
| `pet/modern_settings_dialog.py` | +3 / −0 | 仅接入设置分区与保存委托，主体放独立模块。 |
| `pet/multi_window_shared.py` | +7 / −0 | 应用持有单份计时/陪伴控制器，统一退出收口。 |
| `pet/overlay_shell.py` | +6 / −0 | 专注期间普通随机自言自语让位给人设专注陪伴，兼顾逐宠和聚合入口。 |
| `pet/proactive.py` | +9 / −0 | 专注/暂停期间普通识屏让路，丢弃迟到普通气泡与截图。 |
| `pet/settings_default_marks.py` | +3 / −0 | 将专注数字/开关映射到同源配置默认值，支持改回默认。 |
| `pet/settings_focus.py` | +52 / −0 | 新增；新增长期工作背景、时长、观察与请求预算控件；使用既有行/数值/开关。 |
| `pet/settings_page_guide.py` | +1 / −0 | 加入分区说明，导航 chip 自动沿用既有布局。 |
| `pet/settings_search.py` | +4 / −0 | 添加番茄钟/工作内容/专注模式的口语搜索别名。 |
| `pet/sprite_behavior.py` | +6 / −1 | 阻止随机位移，取消已走动及转向后排定的移动，保留拖拽/物理接管。 |
| `pet/vision.py` | +5 / −1 | 官方端点使用 deepseek-flash，手填与第三方中转的原语义保留。 |
| `pet/window.py` | +5 / −1 | 旧窗口路径同样阻止和取消专注期间的位移，不改持久 no_move。 |
| `pet/window_alerts.py` | +3 / −0 | 旧窗口的随机自言自语让位给进程共享专注陪伴。 |
| `scripts/verify_focus_mode.py` | +428 / −0 | 新增；新增微基准、真实 GUI/整应用/受控前台识屏、满载三遍及完整清单分进程验收入口。 |
| `tests/test_architecture.py` | +2 / −1 | 校准三行设置接线的实测行数预算，功能主体仍拆出。 |
| `tests/test_config_schema.py` | +1 / −0 | 将新增全局键登记到显式配置/重载快照。 |
| `tests/test_desktop_pet_features.py` | +2 / −0 | 更新默认菜单快照；PR 报告归证据豁免，产品源码/README仍扫品牌文案。 |
| `tests/test_file_interpret.py` | +3 / −2 | 附件全局提示词回退测试改用独立无 manifest 角色，隔离基线新增人设，不改产品解读逻辑。 |
| `tests/test_focus_mode.py` | +181 / −0 | 新增；新增轮次/暂停/睡眠跨终点、配置路由、提示词、设置/岛、能力和原生销毁回归。 |
| `tests/test_focus_service.py` | +247 / −0 | 新增；新增真实 Qt 事件循环下前台请求、迟到隔离、取消、错误及提醒冷却回归。 |
| `tests/test_menu_layout.py` | +6 / −0 | 更新模板与实际 QMenu 顺序，校验专注恢复入口。 |
| `tests/test_settings_page_guide.py` | +2 / −0 | 更新自动化分区顺序，三端装配保持一致。 |
| `tests/test_sprite_behavior.py` | +61 / −0 | 新增走动中进入专注及转向后残留计划的公开行为回归。 |
| `tests/test_vision.py` | +6 / −6 | 更新官方型号预期，明确手填覆盖仍优先。 |
<!-- FILES_END -->

## 三、实现要点

- `focus_mode` 为主配置里的全局对象，不进入 `PER_SLOT_SETTING_KEYS`；设置搜索、
  同源默认值、子槽位路由、热重载与全局重置复用既有链路。
- 状态机用单调时钟截止时间，不按 tick 次数递减；睡眠或事件循环阻塞跨过终点时
  只结束当前阶段，不连续补出多轮。运行状态不落盘，重启回空闲。
- 应用共享子系统持有一个 Qt 控制器，1 Hz 计时器只在阶段运行时开启。GUI 线程
  快照配置、人设与凭据；一条有界后台请求管线执行 OS 截图和网络，结果通过 Qt
  信号排队回主线程。后台不操作 QWidget。近期判断只保留三条，不存截图/窗口标题。
- 角色提示词复用聊天 `PromptBuilder` 的角色 manifest 优先级，身份来自共享聊天的
  slot0 视图。背景附加，不覆盖人设。画面文字明示为不可信观察内容。
- 官方 DeepSeek 视觉自动映射更新为 `deepseek-flash`；第三方中转保留旧映射，
  明确手填型号优先。当前官方能力见 [视觉文档](https://api-docs.deepseek.com/guides/vision/)。

## 四、性能分析

命令：`.venv/Scripts/python.exe scripts/verify_focus_mode.py`；同机，五组、每组
100,000 次，取每次耗时中位数（真实产品函数，无替身）。

| 路径 | 实测 |
|---|---:|
| 空闲状态 tick | 0.056706 μs/次 |
| 走动路径新增的空闲专注判定（包含惰性 import） | 0.277108 μs/次 |
| 活跃截止时间 tick | 0.127234 μs/次 |
| 剩余时间文案 | 0.988949 μs/次 |
| 归一化偏好 | 1.829180 μs/次 |

同脚本 `--gui`，真实 Windows Qt 平台，卡片刷新五组×100 次：浅色设置环境
4.362358 ms/次、深色环境 4.240898 ms/次。运行时最高 1 Hz，即该次测量约占每秒
4.4 ms 的 GUI 时间；展开卡片沿用原有自己的更新时间节拍，隐藏岛跳过几何刷新。
这是当前路径的绝对成本，不声称等于改动前后的净差。微基准/截图时另有本地测试负载，
未隔离系统；所有结果只作本机观测。

同脚本 `--application`，一秒采样一次共 67 点。第 20–60 秒（41 点）RSS 平均
183.478 MiB、范围 168.426–193.598 MiB；最后十个运行采样点平均 177.470 MiB、
范围 173.781–184.578 MiB。首五点仍在预热，不能拿启动均值作稳态基线。
同一进程第 20–60 秒 CPU 为单核口径 73.945%，末十点为 17.708%，动画/预热负载变化
很大，不能归因为番茄钟开销；67 点都无专注后台线程，因为未到三分钟请求间隔。
短时样本没有证明长期无增长；结构上新增记忆只有三条、图片不缓存。

稳态：空闲计时器不跑，无新增常驻线程；走动/自言自语/普通识屏增加纯内存判定。
运行期间：1 Hz Qt 计时和岛内容刷新；阶段暂停/等待即停止计时器，隐藏的岛不重算几何。
新请求：默认每三分钟最多派发一条后台任务；看图会调用现有前台窗口查询和内存抓图，
随后发 HTTP；不抓图时只发文字。既有传输重试计入每日预算，连续三次失败当日熔断。
磁盘：请求频控/额度复用 `ProactiveLimiter` 的有锁状态文件，每次真实请求与结果盖戳，
不在 1 Hz 计时热路径写盘；只有偏好保存写主配置。新存储为一个有界额度文件。
内存：一份状态、控件、一个在途图像/请求与至多三条判断；不积累截图或对话历史。
同脚本 `tracemalloc` 实测 1,000 个纯状态对象，含列表引用平均 506.128 B/个；
单对象开始/结束 10,000 次，Python 追踪净增 404 B、峰值增量 484 B（含基准循环局部
变量，不是 Qt 原生堆或整进程测量）。这提供纯状态路径的增长量，不能代替长期 RSS 验证。

## 五、实机运行记录

GUI 命令：`$env:QT_QPA_PLATFORM='windows'; .venv/Scripts/python.exe scripts/verify_focus_mode.py --gui`。
实际平台输出 `windows`，720/1100/1200 三档与明暗设置主题均无横向溢出，背景编辑器
宽度分别 420/800/900 逻辑像素；Tab 可离开多行编辑器，岛按钮有可访问名称与焦点样式。
全部截图位于 `.scratch/focus-mode/evidence-final/`，已实际检查设置、岛展开与错误图，
不以文件存在替代复核。随报告保留代表图：[窄设置](screenshots/focus-mode/settings-light-720.png)、
[深色设置](screenshots/focus-mode/settings-dark-1100.png)、[岛卡片](screenshots/focus-mode/island-card.png)、
[岛错误态](screenshots/focus-mode/island-error.png)、[空闲及禁用按钮](screenshots/focus-mode/island-idle.png)。错误图的文案由视觉探针设置，实际故障行为
另由真实 Qt 控制器与网络边界替身验证。
设置截图隔离了 OS 登录项读点，未操作用户的真实自启设置。

整应用命令：同一脚本 `--application`；独立数据目录，无网络替身或播放器替身。
真实输出：

```text
Native application: island button started a 60-second focus
Native application: expiry after 61.014s; manual break / pause / resume / end passed
sample_count: 67; platform: windows
```

整应用命令退出码为 0。解释器退出阶段仍打印两条 `QAbstractNativeEventFilter.nativeEventFilter`
未实现异常及 `pet/library.py:94` 的 shiboken/QTimer 溢出警告；本轮没有修改这两处退出链路，
也未通过基线对照证明其来源。上述计时和按钮行为已经确认，不能据此宣称退出阶段 stderr 无异常。

真实模型命令：同一脚本 `--live-ai`，只允许自建测试窗口的 HWND 通过前台抓图，
窗口切走则取消；密钥由现有凭据存储解析，未输出到日志或报告。实际官方端点
`api.deepseek.com` / `deepseek-flash` 两次请求均成功：

| 控制窗口 | 实际结果 |
|---|---|
| PySide6 QTimer 文档学习笔记 | 当前画面与工作相关；回复提醒“把 timer 存成 self 的” |
| 猫咪/美食/游戏娱乐推荐 | 当前画面可能偏离工作；回复“猫猫和炸鸡先放一放……回来看看定时器吧” |

两次请求与 Qt 探针创建的完整命令墙钟耗时 7.812 秒，不当作单次模型推理延迟。
这确认当前凭据能接收真实窗口截图并给出任务相关判断，不声称能准确衡量用户的注意力。
错误路径由真实 Qt 控制器 + 网络边界替身验证，计时仍运行，岛卡片显示实际错误原因。
macOS/Linux 没有真机运行证据；当前自动前台观察只支持 Windows。

## 六、测试与验证

红：新增公开状态/设置/岛入口测试因模块不存在而收集失败。
绿：首轮 17 passed；相关设置/菜单/走动/免打扰/识屏 318 passed；岛/共享服务/视觉族
706 passed / 1 skipped。后续边界红→绿：暂停发生在截图期间阻止新的 HTTP；
转向后残留走动在旧实现移动了 1.488095px，修复后保持原位。

Qt 原生销毁探针另有红→绿：`deleteLater()` 绕过 `closeEvent` 后仍留刷新订阅；
现改为 `destroyed` 注销 + 无效 wrapper 守卫，完整 focus/config/desktop/shared 文件族
193 passed。品牌扫描的既有规则已区分贡献/研究证据；本次同样将 PR 交付报告归为
证据文档，避免把 Git 分支名和来源 URL 误当产品文案，产品源码与 README 仍受扫描。
显式配置与默认菜单快照按新增键/动作同步登记。最终完整结果见下方后续验证表。

附件解读的一个既有测试原先用 `shenshen` 却断言全局提示词；基线已存在该角色的
专属 manifest，整套诊断因此暴露其资产依赖。改用独立无 manifest 的测试角色验证
原来的全局回退契约，`pet/file_interpret.py` 与角色 manifest 均未修改。
另补 normal→抛掷时进入专注的红→绿：旧门禁将 `(160,-600)` 清零，现仅取消
normal 状态下的移动；走动及附件两个完整文件合计 78 passed。

到点通知改走既有提醒队列，审批或飞行期间保留，用户开始下一阶段或结束时解决旧
事件 ID；真实 Qt 事件循环的到点/排队/解决回归先红后绿，focus/quiet/file/sprite 族
161 passed。最后设置文案检查将普通组的缩写换为「每日模型请求上限」「看图模型服务」，
不放宽文案门禁；文案与专注文件 27 passed。

<!-- VALIDATION_BEGIN -->
| 验证 | 实际结果 |
|---|---|
| ruff：`python -m ruff check pet tests scripts/verify_focus_mode.py --output-format concise` | All checks passed |
| 最后重点：focus 状态/服务、设置文案、报告纪律 | 176 passed，10.15s |
| 最终交付：报告纪律、架构预算、设置文案 | 168 passed，7.18s；ruff 与 `git diff --check` 通过 |
| 满载：`scripts/verify_focus_mode.py --stress-tests`，16 个 CPU 忙循环子进程，三遍 focus/shared 族 | CPU 100%；各 36 passed，pytest 用时 78.86s / 15.23s / 18.41s；三遍退出码 0，子进程已清理 |
| 前半：非解码文件名 `< test_q`，233 个独立文件进程，共 4,744 项 | 4,734 passed / 10 skipped，233 个退出码均为 0；JUnit 时间合计 850.945s，两并发进程墙钟跨度 554.292s |
| 后半：非解码文件名 `>= test_q`，2,770 项 | 2,765 passed / 5 skipped，514.77s，退出码 0 |
| 两个解码扇出文件（非解码用例全部通过后单独运行） | 30 passed，5.27s，退出码 0 |
| 全量清单合计 | **7,529 passed / 15 skipped / 0 failed / 0 errors，共 7,544 项** |

实际命令分别为 `scripts/verify_focus_mode.py --suite-tests --output .scratch/focus-mode/suite-final`
（后半成功，前半大进程原生失败）、`--suite-tests --suite-part before-q --output .scratch/focus-mode/suite-files`
（233 文件全部成功）、`--suite-tests --suite-part decode --output .scratch/focus-mode/suite-decode`
（解码全部成功）。最终合计只取成功的 233 个前半文件、后半组和解码组，不计崩溃轮次。
三个清单文件集合并集等于完整收集的 359 个文件，互不重复；JUnit 总数与 7,544 项一致。
后半成功运行之后没有修改任何 `pet/` 或 `tests/` Python 源码（文件时间探针确认），
只完善验证工具与文档，因此保留该成功结果，没有无意义重复运行。

最终主套件之前的诊断轮为 2 failed / 7495 passed / 15 skipped，1340.12s；
两个失败分别是上文的附件夹具与普通组缩写，已修复。这一轮不当作最终全绿证据。

后续主套件曾在约 63% 的 `test_quick_chat.py:59` 事件派发中发生 Windows 原生访问
冲突（退出码 −1073741819），此前无行为断言失败；专注/快捷聊天/免打扰隔离组合
91 passed，不能据当前堆栈认定快捷聊天为来源。复核发现新增销毁测试全局派发了
`DeferredDelete`，违反既有 Qt 生命周期约定；现改为仅向该测试创建的 island 派发。
定向修正后开启原生诊断的下一轮仍在同一用例、同一行崩溃，不能将它当作根因修复。
单独隔离快捷聊天后，同样异常移到免打扰 `test_quiet_mode.py:288` 的事件派发，
说明单文件隔离不足。按 AGENTS.md 的隔离要求，新增 `--suite-tests`：收集全部
7,544 个唯一用例，非解码文件分为 `< test_q` 的 4,744 项与 `>= test_q` 的 2,770 项，
后半完整通过；前半大进程后来在 `test_proactive.py:1370` 再次原生崩溃，故改为
233 个文件独立进程（最多两个并发），保留已通过后半的结果，期间产品与测试代码未改动。
全部非解码进程通过后才跑 30 项解码。清单校验并集完整、交集为空；各进程有独立
APPDATA、缓存和诊断目录，逐段 JUnit XML 与退出码留证。全部用例仍执行，具体顺序
与排查证据已加入 `ACCEPTANCE_TESTS.md`。
不将发生崩溃或主动中断的轮次算作通过，原生风险来源仍未确定。
<!-- VALIDATION_END -->

## 七、限制与回滚

屏幕只能提供任务关联线索，不能证明用户心理上的专注。空背景仅鼓励；非 Windows
不自动看前台。暂停或退出不保证已发出的请求能在服务端撤销，但不再发下一次重试，
迟到结果不展示。计时会受 Qt 事件循环调度影响，本机一分钟实测晚约一秒提醒。
不新增跨重启恢复或长期专注统计。回滚到基线前应另存后续用户修改，使用
`codex/baseline-before-focus-20261015` 创建独立检出比较；不直接硬重置脏工作区。
旧版本会忽略新增偏好，额度文件可保留；本次不触碰既有聊天会话及用户角色档案。
