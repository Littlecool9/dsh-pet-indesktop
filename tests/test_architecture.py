# -*- coding: utf-8 -*-
"""架构红线断言（结构线纪律的机器化）。

三条红线，红了就是架构倒退，不许靠改测试放行：
1. 依赖方向：纯逻辑层（physics）不依赖 Qt；
   decode_fanout 不反向依赖 window/webm_clip（钩子经 movie 属性注入）。
2. 私有面冻结：window 私有成员（win._xxx）在 app.py / agent_link.py /
   context_menus/ 中零命中（S2 已清零，防回潮）。
"""
from __future__ import annotations

import re
from pathlib import Path

PET_DIR = Path(__file__).resolve().parents[1] / "pet"


# modern_settings_dialog.py 行数预算：按结构线拆分后实测 1857 行（拆分前 4811 行）。
# 主对话框 ModernSettingsDialog + 对话框装配/配置写回 + 为 pet/ 与 tests/ 保留的
# re-export 留守本文件；控件库 / 菜单布局编辑器 / AI 设置页 / 主题 QSS 已分别拆至
# settings_widgets / settings_menu_layout_editor / chat/ai_settings_page /
# settings_theme_qss。预算随实测校准（早期口径为「实测 + 50 行余量」，2026-09-17
# 起按实测值锁定，见下方逐次记录）；再往上帝类里塞新页面时只许降不涨。
# 2026-09-05 建立（perf/memory-footprint 拆分批）。
# 2026-09-06 上调到 1992：合入上游 main（PR73）带来动画预热开关等 +85 行
# （实测 1942），预算随实测校准。
# 2026-09-08 上调到 1996：新增「随桌宠启动 dsh 服务」开关行（+4，实测 1996）。
# 2026-09-08 上调到 2000：批 C 落种占位语义在保存路径加 user_customized 置位（+4，实测 2000）。
# 2026-09-08 上调到 2009：批 E 清除子肥鱼走 shell 已接线回调（+9，实测 2009）——
# _on_clear_spawned_pets 优先调 win.on_clear_spawned_pets（自带确认框与进程内
# 子窗前置于关闭），拿不到回调时回退原有确认+直接清理；按文件约定校准预算，
# 不为达标压缩行宽/合并语句。
# 2026-09-08 上调到 2018：批 G——「退出子肥鱼」按钮对子肥鱼禁用（+5）+
# _on_clear_spawned_pets 加 instance_id 双保险（+5，含注释折行），实测 2018。
# 2026-09-15 上调到 2270：语音报时设置页接入（页面实例化/SettingRow 收集/
# _write_config 写回/试听透传回调）与两开关、音色下拉改造，实测 2255；
# 按文件约定预算只随实测校准，不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-09-16 上调到 2300：合并上游展开式格式（当时整块 SettingsSection 从
# 紧凑单行改为 Black 风格展开，仅格式就 +100 行以上）叠加设置分组
# （3 行 SettingRow）+「消费统计」一级分组，实测 2300；按文件约定预算只随
# 实测校准，不为达标压缩行宽/合并语句；拆分仍是待办。
# 本文件拆分仍是待办，拆分前预算只随实测校准。
# 2026-09-16 上调到 2300：#128「消费统计/菜单」接入设置页，实测 2300。
# 2026-09-16 再上调到 2311：#127 节日提醒设置页（+11）与 #128 叠加后实测 2311——
# 这正是「红线是组合性质」：两个 PR 各自合并时 CI 都绿，合到一起才越线
# （见 docs/PR-MERGE-LESSONS-2026-09-12.md 教训 2）。按文件约定只随实测校准，
# 不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-09-17 上调到 2327：新增「语音」总域，并按主人定稿口径只收鱼开口说话
# （TTS）类设置——语音报时整组 12 行 + 节日提醒 12 行（原「自动化与联动」域，带
# speak/TTS 播报能力）；音效类回各自功能分组：点击音效 4 行回「互动 · 点击反馈」
# （click_ 前缀整组认领，与 HEAD 行为一致）、碰撞音效 2 行回「桌宠」碰撞组，Agent 提示音效
# （agent_sound_*）留在 Agent 联动折叠框内。实测 2327；按文件约定只随实测校准，
# 不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-09-17 上调到 2341：灵动岛图标下拉框新增「鱼本体头像（推荐）」项，原 10 个
# emoji 选项标签改中文（data 仍是 emoji）——设置页自己渲染 emoji 也会付同一笔
# DirectWrite 彩色字体栈税额（约 33MB）；标签逐项成对写，实测 2341。
# 2026-09-17 上调到 2371：设置页进程隔离（standalone）——__init__ 的 standalone
# 形参/属性、末尾接线 install_standalone_hooks、move_away_from_pet 的 runtime
# 避让分支、_on_voice_chime_preview 的本地试听分支、_write_config 注释共 +30；
# 试听/避让/节日演示的实现全在 pet/settings_standalone.py，本文件仍只做接线；
# 按文件约定预算只随实测校准，不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-09-19 上调到 2393：两批设置改动**组合**后的实测值——拖文件解读新增
# 「文件识别」域（对话框只做接线，实现全在 pet/settings_file_interpret.py）与灵动岛
# 「隐藏时对话气泡」开关（控件 +2、SettingRow +6、_write_config 回写 +1）各自
# 只按自己那批校准（2384 / 2380），合起来才是 2393：单个 PR 都不越线、只有两者
# 同时进才红——又一次「红线是组合性质」的实例（PR-MERGE-LESSONS 第 2 条），
# 故按文件约定只随实测校准，不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-09-19 上调到 2401：新增「气泡文字大小」设置行（bubble_text_scale，+8）——
# 3 行 SettingRow 展开式写法（6 行）+ _write_config 回写 1 行 + 布局编排认领 1 行；
# 控件本体落在 pet/settings_pet_controls.py（与既有的「配图大小」同处），
# 缩放实现全在 pet/speech_bubble*.py。按文件约定只随实测校准，不为达标压行。
# 2026-09-22 上调到 2419：点击台词朗读 / 台词自动预缓存 / 配图概率共 3 个 SettingRow
# 接入「互动」域已存在的两组（点击反馈 + 自言自语），逐项为 SettingRow 展开式写法、
# 随组显隐名单、归属 claim、_write_config 写回，实测 2419；控件本体落在
# pet/settings_pet_controls.py，朗读/预缓存实现全在 pet/self_talk_voice.py 与
# pet/window_alerts.py。同页同组连续加控件，拆出来只会把这组设置割成两半；
# 按文件约定只随实测校准，不为达标压行。设置页拆分仍是待办。
# 2026-09-22 上调到 2436：点击侧显隐解耦（+17）——点击自言自语不再依附周期气泡
# 总开关，因此点击侧另立一个 _update_click_self_talk_controls（含函数 docstring 与
# 两处接线），实测 2436。这是可用性修复（原实现让新开关在默认配置下整组隐藏），
# 不是新功能；分页/拆分后预算会随实测下调（见「互动」域分页改造）。按文件约定
# 只随实测校准，不为达标压行。
# 2026-09-22 上调到 2441：**组合越线**——#176（点击侧显隐解耦，2436）与
# #177（设置页接线的 +5）各自合并时都在预算内，合到一起才越线，
# 又一次「红线是组合性质」的实例（docs/PR-MERGE-LESSONS-2026-09-12.md 教训 2）。
# 实测 2441；随后即由「互动」域分页 + 抽 pet/settings_interaction.py 大幅下调，
# 故这里只做一次性校准，不为达标压行。
# 2026-09-22 **下调到 2347**：兑现上一条的承诺——「互动」域整页搬进
# pet/settings_interaction.py（页内任务标签「点击与音效 / 自言自语」），
# 本文件净减 94 行（2441 → 2347）。这是本文件第一次**因拆分而下调**预算：
# 靠搬代码而不是压行宽解决预算，正是预算作为「绊线」的预期用法。
# 2026-09-23 上调到 2357：纯桌宠版岛隐藏死锁修复——新增
# _chat_feature_available() 构建变体判定助手（+12）并将「隐藏时对话气泡」
# SettingRow 改为按构建变体条件收录（净 +3，注释另计）：无 pet.chat 的
# 打包变体不再展示该死路开关（运行时回退在 pet/dynamic_island.py 的
# chat_available）。实测 2357；按文件约定只随实测校准，不为达标压行。
# 2026-09-23 上调到 2377：4.2c 后段 D12「一键退出子肥鱼」按拓扑分流（+20）——
# overlay 拓扑下子肥鱼是进程内 sprite，跨进程 taskkill 回退（child_pet_cleanup）
# 找不到目标、按钮静默失效，改为写指令文件由主进程消费；legacy 回退逐行不变。
# 拓扑判定/写指令/校验的实现全在零 Qt 的 pet/overlay_settings_command.py，
# 本文件只做一次分支与身份回填（slot_from_instance_id）。
# 2026-09-24 上调到 2391：合入上游更新页接线（更新页主体在 pet/update_settings.py）。
# 实测 2391；按文件约定只随实测校准，不为达标压行（拆分仍是待办）。
# 2026-09-27 上调到 2393：overlay 文案如实（省电模式 hint 改调 settings_pet_controls、
# 窗口级键「对所有桌宠生效」标注接线 +2 行）。
# 2026-10-06 上调到 2403：清空陪伴记忆按 clear() 返回值如实提示（失败弹告警而不是
# 一律「已清空」）+10 行；实测 2403，按文件约定只随实测校准（拆分仍是待办）。
# 2026-10-06 上调到 2407：新增设置行（行构造 + 保存回写，控件本体在
# settings_pet_controls）。实测 2407。
# 2026-10-06 仍为 2407（「恢复默认设置」入口，issue #220）：本文件只加接线——
# import 1 行 + 侧栏按钮构造 3 行 + `_close_after_external_write` 方法 7 行
# （关窗但跳过整表写回，flag 语义留在对话框内），确认框/重置实现全在
# pet/settings_reset_defaults.py。实测恰为 2407（= 当前预算，零余量）：本次不再
# 上调，按文件约定"只随实测校准"；若与其它在飞分支叠加越线，按先例带日期注释校准。
# 2026-10-07 上调到 2415（夜间整合分支：#220 恢复默认设置 +13、#219 静止放手下落
# +4、harness 自启 service 目标下拉项与宽度自适应净 +6，三分支同文件叠加）。
# 实测 2415；按文件约定只随实测校准（拆分仍是待办）。
# 2026-10-08 回调到 2423（#208+#209+#172 叠加后：免打扰 4 行 / 天气 2 行 /
# 网络信息 5 行，实现分别在 pet/settings_quiet.py / settings_network.py）。
# 实测 2423；按文件约定只随实测校准（拆分仍是待办）。
# 2026-10-08 再调到 2426（#172 对齐：菜单入口改运行时置灰——CONTEXT.md 的
# Runtime Disabled）：编排器状态列随开关显示「已停用」——`_sync_menu_action_states`
# +2 行（读开关）与开关接线 +1 行。实测 2426。
# 2026-10-07 上调到 2470（设置页信息架构第一刀，+44）：常规域「启动项（高级）」+
# 桌宠域「播放器路径与标题格式（高级）」两条高级组装配、桌面组件域把探测间隔拆进
# 「网络延迟检测（高级）」（含"全行被依赖隐藏的组整组收起"的 3 行）、_search_settings
# 补 `SettingsSection(advanced=True)` 自动展开分支与「命中行被前置开关隐藏」的说明
# 助手，另含 harness 自启目标与静止放手下落两处定稿文案（净行数含注释折行）。
# 2026-10-08 上调到 2495（设置页信息架构第二刀，+17）：桌宠域拆成两个页内标签
# （显示 / 动作与碰撞），两个 addTab 的装配骨架 + 任务口径注释；组定义行一字
# 未改（只是搬到各自标签的 page_content 里）。实测 2487。
# 2026-10-08 设置页第五刀（按区直找）批 1：恢复被域装配压平的旧页子分区（主动识屏
# 15 行拆 4 组、语音报时 / 节日提醒各 12 行拆 3 组；行键表 20 行）+「自动化与联动」
# 顶层改按下表顺序（删掉 15 行 insertWidget 倒插逻辑）+ page_content 支持已构造好的
# QWidget，实测 2495（= 第二刀的预算值，未上调）。
# 2026-10-08 上调到 2497（同刀批 2）：页内分区跳转条与组描述的接线——import 1 行 +
# 域装配末尾 `settings_page_guide.install(self)` 及其注释 2 行；主体（跳转条、流式
# 布局、SECTION_GUIDE 描述表）全在 pet/settings_page_guide.py，本文件只做接线。
# 2026-10-09 上调到 2501（bug 狩猎修复批，两批叠加）：即时音效开关的 reload 防陈旧
# 快照守卫（+7，B04）+ 子宠页读写路由的配置入口一行与 harness 置灰摘除（+3，F2）。
# 2026-10-14 上调到 2505（TTS provider 化）：语音报时与节日提醒不再按「一组行」收进
# 「语音」域（页面容器会散架、分组标题会丢），改由各自页面自建卡片交给本域——域装配
# 处多出一层容器、两次行序刷新与搜索折叠展开的接线（净 +4）。
# 2026-10-14 再上调到 2508：节日页的行从构造起就挂在页面自己的持有容器里（无父的
# SettingRow 一旦 setVisible 就是顶层窗口，会闪小窗），于是它们的行**也要**在域装配
# 前登记进 claimed，否则会掉进「待分类（开发期）」（+3）。
# 2026-10-16 上调到 2515（设置页外观打磨分批，本文件净 +14）：窗口图标两处接线（import
# +1、setWindowIcon 与注释 +3）、侧栏容器换成按字体算宽的 SettingsSidebarPane（-1，主体
# 在 pet/settings_widgets.py）与两处行距下调（配对注释 +5）、常规域的高级组装配（+1 与其
# 分层口径注释 +5）。控件本体、宽度计算与组描述分别落在 settings_widgets /
# settings_page_guide，本文件只留装配与接线。**同批第二轮把预算内余量用掉、回到 2515**：
# 「光标隐藏时自动穿透」从高级组移回「窗口与系统」、高级组只剩「直播捕获兼容」、默认最大
# 阅读宽度换成 CONTENT_READING_MAX_WIDTH（import +1）、开机自启的范围声明改由
# settings_pet_controls 的作用域 pass 拆成行内标注（-2），其余靠收掉几处重复注释对齐。
# 2026-10-16 上调到 2526（允许桌宠跨屏开关，本文件净 +11）：常规域「窗口与系统」
# 多一行（行装配 8 行 + claim 表加一个 id + 保存回写 2 行）。控件本体与两条说明
# 文案落在 settings_pet_controls（`CROSS_SCREEN_HINT` 与作用域登记），本文件只留
# 装配与接线；行内文案表仍是唯一来源。按文件约定预算只随实测校准，不为达标压缩
# 行宽/合并语句；拆分仍是待办。
# 2026-10-17 累计校准到 2535：main 上 PR267 落地后实测 2533（2526 + TTS provider 化的净 +7），
# 本支的每日一签接线再 +2，合并树实测正是 2535。抽签的页装配不在本文件——它作为「互动」
# 域第四个页内标签由 settings_interaction 挂载（与天气同口径），避免这个"上帝对话框"再涨。
# 仍按文件约定只随实测校准。
# 2026-10-18 上调到 2539（待办语音播报，本文件净 +4）：待办提醒分区多一行
# `SettingRow("todo_reminder_speak", ...)`（行装配 3 行 + 保存回写 1 行；claim 表那行
# 只是多一个 id，不增行）。控件本体在 settings_pet_controls，文案只有行内这一份来源。
# 仍按文件约定只随实测校准，不为达标压缩行宽/合并语句；拆分仍是待办。
# 2026-10-18 上调到 2561（自言自语内容项显隐解耦，本文件净 +22）：周期气泡的细项
# 显隐拆成「节奏项只跟周期开关」+「内容项（显示时间/候选内容/图片目录/配图概率）
# 跟周期或点击任一开启」——新增 `_update_self_talk_content_controls`（含 docstring）
# 与 `_update_self_talk_controls` / `_update_click_self_talk_controls` 两处调用的接线，
# 行数即这两个函数的净增。显隐规则必须贴着这两处开关的 toggled 接线（拆成外部函数
# 反而把"哪一档跟哪个开关"这条唯一契约切散），故按文件约定校准到实测值。
# 2026-10-18 上调到 2563（互动域新增「快捷键」页内标签，本文件净 +2：一行 import
# + 保存路径一行 `save_hotkey_settings`）。行的装配在 settings_hotkeys（新模块），
# 本文件只留接线——这是既定口径（settings_quiet/settings_network 同形）。
# 2026-10-18 上调到 2580（Ctrl+F 聚焦搜索框 + 搜索索引纳入「更新」页作者行，本文件
# 净 +17：两条 import、`_focus_search_box` 槽与其接线、索引来源多一类候选）。
# 2026-10-19 上调到 2594（搜索框 ↑/↓ 逐条翻命中，本文件净 +14：`_search_settings`
# 改成 `advance: int` 步长并补 docstring、`eventFilter` 四键映射）。这一改只动键盘
# 交互，没有新页面/新控件组可拆，按「拆不动则校准到实测」处理。
# 2026-10-19 上调到 2600（同一处再 +6：`eventFilter` 加修饰键闸门——只拦裸键/小键盘键，
# 带 Ctrl/Alt/Shift 的 ↑↓ 透传，避免抢走输入法候选导航）。仍是键盘边界，同上处理。
# 2026-10-19 合并专注模式与上游 v4.3.4：保留 settings_focus 的 import、
# 分区装配和保存接线（上游基础上 +3），预算按合并树实测校准。
MODERN_SETTINGS_DIALOG_PY_LINE_BUDGET = 2603


def _read(name: str) -> str:
    return (PET_DIR / name).read_text(encoding="utf-8")


def test_pure_logic_modules_do_not_import_qt():
    # 2026-09-23 加入 overlay_settings_command：D12 指令通道的写/读/消费与拓扑门
    # 必须零 Qt——独立设置进程（pet/__main__.py --settings）禁止导入 pet.app/
    # overlay_shell，env 读取的唯一实现只能落在两侧都能 import 的轻模块里。
    # network_info.py 是「网络信息」弹窗的数据层（属地解析/连通性/文案），必须零
    # Qt——弹窗只在打开时取一次数据，数据层不碰 GUI。
    for name in (
        "physics.py",
        "overlay_settings_command.py",
        "network_info.py",
        # 2026-10-07 加入 island_segments（灵动岛段契约）：段注册契约与宽度/四态
        # 兜底必须零 Qt——测宽靠调用方注入的 QFontMetrics（依赖注入）。
        # 2026-10-07 加入 island_layout（P1 Slice D2 下沉）：段数据/落位/收缩流水线
        # 是纯几何，度量对象同样注入——收缩逐级触发/逆序恢复这些规则要能在没有
        # 窗口、没有真实字体、没有屏幕的替身上直接验，就必须零 Qt。
        "island_segments.py", "island_layout.py",
    ):
        src = _read(name)
        assert "PySide6" not in src, f"{name} 引入了 Qt 依赖，破坏纯函数层定位"


def test_decode_fanout_does_not_depend_on_window_or_player():
    src = _read("decode_fanout.py")
    for banned in ("pet.window", "pet.webm_clip", "from .window", "from .webm_clip",
                   "import window", "import webm_clip"):
        assert banned not in src, f"decode_fanout 反向依赖 {banned}，破坏单向依赖"


# 多进程多宠退役层（PHASE4_DESIGN.md §3 T6 清单，4.4a 停用 / 4.4b 删除）。
# 4.4a 机器化守卫：**overlay 新路径**（单合成窗渲染面）必须零 import 这些
# 模块——新架构的多宠碰撞/身份/生命周期全部在进程内 sprite 世界自足，
# 一旦回潮就是"新路径又骑回多进程 IPC/文件锁"的架构倒退。
# 4.4b 追加守卫：这些模块文件本身必须**不存在**（删除刀不许被静默回退），
# 且全 pet/ 树（不只新路径）不得再 import 它们。
RETIRED_MULTIPROCESS_MODULES = (
    "collision_ipc",
    "collision_codec",
    "collision_client",
    "collision_debug",
    "instance_launcher",
    "child_pet_cleanup",
)


def test_retired_multiprocess_layer_files_are_gone():
    """4.4b 机器化守卫：退役层文件必须不存在（防"删了又被合回来"）。"""
    present = [name for name in RETIRED_MULTIPROCESS_MODULES
               if (PET_DIR / f"{name}.py").exists()]
    assert not present, (
        "多进程多宠退役层文件回潮（T6 清单已删除）：\n" + "\n".join(present)
    )


def test_pet_tree_has_zero_retired_layer_imports():
    """4.4b 机器化守卫：整个 pet/ 树（含 legacy 路径）零 import 退役层模块。

    与上一条互补：文件不存在是"删干净"，本条约住"任何模块都不得再 import"
    （含函数级延迟 import 与 from pet.xxx 绝对写法）。
    """
    offenders = []
    for path in sorted(PET_DIR.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            for retired in RETIRED_MULTIPROCESS_MODULES:
                if re.search(rf"\b{retired}\b", stripped):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "pet/ 内仍有 import 多进程多宠退役层（架构倒退）：\n"
        + "\n".join(offenders)
    )


# 死面 facade 退役（2026-10-09，bug 狩猎 F4 清理）：config_domains 是「只建不用」
# 的配置域 facade——五个 ``Config.*_config`` 方法全仓零产品调用方（只有它自己的
# 测试在用），留着只会让人按假象面改代码踩空。整层删除后按退役层先例守卫：
# 文件必须不存在，且全 pet/ 树不得再 import——防「死面被静默合回」。
RETIRED_DEAD_FACADE_MODULES = ("config_domains",)


def test_retired_dead_facade_files_are_gone():
    """死面 facade 机器化守卫：文件必须不存在（防"删了又被合回来"）。"""
    present = [name for name in RETIRED_DEAD_FACADE_MODULES
               if (PET_DIR / f"{name}.py").exists()]
    assert not present, (
        "死面 facade 文件回潮（2026-10-09 已整层删除）：\n" + "\n".join(present)
    )


def test_pet_tree_has_zero_dead_facade_imports():
    """死面 facade 机器化守卫：整个 pet/ 树零 import（含函数级延迟 import）。"""
    offenders = []
    for path in sorted(PET_DIR.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            for retired in RETIRED_DEAD_FACADE_MODULES:
                if re.search(rf"\b{retired}\b", stripped):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "pet/ 内仍有 import 死面 facade（2026-10-09 已整层删除）：\n"
        + "\n".join(offenders)
    )


# 旧版右键菜单退役层（2026-10-08 全量退役，见
# docs/PR-REPORT-LEGACY-MENU-RETIREMENT-2026-10-08.md）。
# 守卫分三层，同多进程层先例：
#   ① 退役文件必须**不存在**（删除刀不许被静默回退）；
#   ② 整个 pet/ 树不得再 import 退役模块；
#   ③ 退役符号（旧版建造器 / 旧模板装载 / 模板切换）不得在任何一行重新出现——
#      包括函数体、字符串与注释：这些符号一旦回潮，就意味着"又有一棵菜单树按
#      模板分流"，正是本次删掉的东西。
# 退役配置键另有一条更精确的守卫（test_retired_menu_template_key_confined_to_migration）：
# 它必须还能被**迁移**引用一次（丢旧值），但不许再被任何消费方读/写。
RETIRED_LEGACY_MENU_PATHS = (
    "context_menus/legacy.py",
    "context_menus/menu_styles/legacy.py",
    "menu_templates/legacy.json",
    "menu_templates/modern.json",
)
RETIRED_LEGACY_MENU_MODULES = (
    "context_menus.legacy",
    "menu_styles.legacy",
)
RETIRED_LEGACY_MENU_SYMBOLS = (
    "build_legacy_menu",
    "apply_legacy_menu_style",
    "load_menu_template",
    "normalize_template_id",
    "add_template_switch",
)
#: 已退役的右键菜单模板键：只允许出现在 config.py 的迁移函数里。
RETIRED_MENU_TEMPLATE_KEY = "context_menu_template"
RETIRED_MENU_TEMPLATE_MIGRATION = "pet/config.py::_migrate_menu_template_config"


def test_retired_legacy_menu_files_are_gone():
    """退役的旧版菜单文件必须不存在（防"删了又被合回来"）。"""
    present = [rel for rel in RETIRED_LEGACY_MENU_PATHS
               if (PET_DIR / rel).exists()]
    assert not present, (
        "旧版右键菜单退役层文件回潮（已全量删除）：\n" + "\n".join(present)
    )


def _function_block(source: str, name: str) -> tuple[int, int, str]:
    """按缩进切出一个方法体（返回 (起始行号, 结束行号, 文本)）。"""
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"    def {name}"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("    def ") or lines[i].startswith("    @"):
            end = i
            break
    return start, end, "\n".join(lines[start:end])


def test_retired_menu_template_key_confined_to_migration():
    """退役的模板键在 pet/ 里只许存活于迁移函数内（丢旧值的那一处）。

    这是"读入即弃"的机器判据：别处再出现这个键，就等于又有一个消费方读它
    （配置重新分叉）；迁移函数里出现则是必须的——旧存档得有个地方丢掉它。
    """
    config_src = (PET_DIR / "config.py").read_text(encoding="utf-8")
    _, _, block = _function_block(config_src, "_migrate_menu_template_config")
    assert RETIRED_MENU_TEMPLATE_KEY in block, (
        f"{RETIRED_MENU_TEMPLATE_MIGRATION} 必须仍丢弃这个键（旧存档的去向）")
    outside = [(no, line) for no, line in enumerate(config_src.splitlines(), 1)
               if RETIRED_MENU_TEMPLATE_KEY in line]
    block_start, block_end, _ = _function_block(config_src, "_migrate_menu_template_config")
    offenders = [
        f"pet/config.py:{no}: 退役键出现在迁移函数之外"
        for no, _line in outside
        if not (block_start + 1 <= no <= block_end)
    ]
    for path in sorted(PET_DIR.rglob("*.py")):
        if path.name == "config.py":
            continue
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"\b{RETIRED_MENU_TEMPLATE_KEY}\b", line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "退役的右键菜单模板键回潮（只许在迁移函数里丢旧值）：\n"
        + "\n".join(offenders)
    )


def test_pet_tree_has_zero_retired_legacy_menu_references():
    """整个 pet/ 树零退役菜单符号：谁再把旧版建造器/模板装载/模板键写回来，
    这里就红——比"文件不存在"更严，挡住"换个文件名复活"与"注释里留老路"。"""
    offenders = []
    for path in sorted(PET_DIR.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            for retired in RETIRED_LEGACY_MENU_SYMBOLS:
                if re.search(rf"\b{retired}\b", line):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            for retired in RETIRED_LEGACY_MENU_MODULES:
                if re.search(rf"\b{re.escape(retired)}\b", stripped):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "pet/ 内仍有旧版右键菜单退役层引用（架构倒退）：\n"
        + "\n".join(offenders)
    )


def _overlay_new_path_modules() -> tuple[str, ...]:
    """新路径模块清单：overlay_* / sprite_* / pet_sprite / tick_*。

    按目录枚举（而不是硬编码文件名）——新路径新增模块自动纳入守卫，
    不会因为"忘了加名单"漏掉一次回潮。
    """
    patterns = ("overlay_*.py", "sprite_*.py", "tick_*.py")
    names = {"pet_sprite.py"}
    for pattern in patterns:
        names.update(p.name for p in PET_DIR.glob(pattern))
    return tuple(sorted(names))


def test_overlay_new_path_has_zero_retired_layer_imports():
    """4.4a 停用刀：新路径零 import 多进程多宠退役层（T6）。"""
    offenders = []
    modules = _overlay_new_path_modules()
    assert "overlay_shell.py" in modules and "sprite_physics.py" in modules, (
        "新路径模块枚举失效（目录变动？），守卫清单必须非空"
    )
    for name in modules:
        for lineno, line in enumerate(_read(name).splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue  # 只查 import 语句，注释里的历史提及不算回潮
            for retired in RETIRED_MULTIPROCESS_MODULES:
                if re.search(rf"\b{retired}\b", stripped):
                    offenders.append(f"{name}:{lineno}: {stripped}")
    assert not offenders, (
        "overlay 新路径 import 了多进程多宠退役层模块（架构倒退）：\n"
        + "\n".join(offenders)
    )


def test_window_private_surface_frozen():
    """S2 收口成果：window 私有成员跨模块访问在以下文件中必须保持零命中。"""
    pattern = re.compile(r"(?:win|pet|window)\._[a-z]")
    offenders = []
    for rel in ("app.py", "agent_link.py"):
        for lineno, line in enumerate(_read(rel).splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    for path in sorted((PET_DIR / "context_menus").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"context_menus/{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "window 私有面回潮：\n" + "\n".join(offenders)


# —— 行数预算的意图与使用约定（给所有贡献者，含 AI 驱动）——
# 为什么有预算：modern_settings_dialog.py 这类文件膨胀到几千行后，
# 人和 AI 都难读难改、定位问题成本高、合并冲突频发。预算只是倒逼拆分的
# 「绊线」，本身不是目的，更不是红线。触发时的正确动作按优先级：
#   1. 首选：把新内容拆到独立模块/控制器；
#   2. 实在拆不动或强拆更伤可读性时：把预算常量校准到新实测值，注明日期+理由，
#      并在 PR 里说明（超一点没关系，说清楚就行）。
# 禁止的反向优化：靠压缩行宽/合并语句/删注释把行数硬塞回预算内——
# 那比超预算本身更伤维护性。宁可校准预算，不要压行。

def test_modern_settings_dialog_py_line_budget():
    lines = len(_read("modern_settings_dialog.py").splitlines())
    assert lines <= MODERN_SETTINGS_DIALOG_PY_LINE_BUDGET, (
        f"modern_settings_dialog.py 涨到 {lines} 行（预算 {MODERN_SETTINGS_DIALOG_PY_LINE_BUDGET}）。"
        "预算是防膨胀的绊线（文件太大则难读难改、合并冲突多、问题定位难），"
        "不是红线：新页面/新控件组优先拆出（控件库/布局编辑器/AI 设置页/"
        "主题 QSS 已是先例）；拆不动可校准预算到新实测值（带日期注释）并说明理由。"
        "请勿为达标压缩行宽/合并语句。"
    )


def test_modern_settings_dialog_no_top_level_chat_import():
    """no-chat 打包变体 excludes=['pet.chat']：modern_settings_dialog 顶层若直接
    import pet.chat.*（如 ai_settings_page），产物运行时点「桌宠设置」会在模块
    导入期抛 ModuleNotFoundError，导致设置界面整体打不开（测试环境因 pet.chat
    齐全而全绿，属打包专属回归）。chat 依赖必须延迟到 include_ai 分支内的
    函数级 import，no-chat 时 include_ai=False 不触发。"""
    offenders = []
    for lineno, line in enumerate(_read("modern_settings_dialog.py").splitlines(), 1):
        if line[:1].isspace():
            continue  # 仅检查模块顶层（无缩进）import；函数内延迟 import 合法
        stripped = line.strip()
        if (stripped.startswith("from .chat")
                or stripped.startswith("from pet.chat")
                or stripped.startswith("import pet.chat")
                or stripped == "from . import chat"):
            offenders.append(f"modern_settings_dialog.py:{lineno}: {stripped}")
    assert not offenders, (
        "modern_settings_dialog 顶层 import pet.chat 回潮：no-chat 打包变体"
        "（excludes=['pet.chat']）运行时设置界面会打不开。chat 依赖须延迟到"
        " include_ai 分支内的函数级 import。\n" + "\n".join(offenders)
    )


def test_settings_widgets_orphan_cluster_guard():
    """孤儿簇（批6-7 拆分被上游合并静默回退的死文件）防再发：settings_widgets.py
    与 settings_styles*.qss 不允许「存在且零引用」态——要么已删除，要么被
    pet/ 内某模块 import/读取（read_text/QFile）。"""
    targets = (
        "settings_widgets.py",
        "settings_styles.qss",
        "settings_styles_dark.qss",
        "settings_styles_dark_browser.qss",
    )
    py_sources = [p.read_text(encoding="utf-8") for p in PET_DIR.rglob("*.py")]
    for name in targets:
        path = PET_DIR / name
        if not path.exists():
            continue  # 已删除：允许的终态
        needle = name[:-3] if name.endswith(".py") else name
        assert any(needle in src for src in py_sources), (
            f"{name} 存在但零引用——批6-7 孤儿簇回退态，须删除或恢复接线"
        )
