# 大肥鱼对话人设文案（2026-10-15）

> **基线**：`b55f203`，本地分支 `codex/local-setup`。
> **范围**：新增角色聊天 manifest 与本报告，并登记文档索引；用户原有工作区修改保留。
> **关联**：[README 的 AI 对话提示词与角色 manifest 说明](../README.md)、[工程规则](../AGENTS.md)。

## 一、核心特性

用户先审阅草案，再明确将“聪明可靠”调整为“有点小聪明但发挥不稳定、认真却容易想岔、嘴硬又蠢萌”，最后授权填入。
角色提示词保留这三段确认内容：核心性格、蠢萌的表现、做事时的态度；结合此前审阅的白饭/token 口粮、摸鱼与相处口吻，以及五条确认的对话示例。
蠢萌通过语气与反应呈现，不要求模型故意提供错误答案，也不允许编造任务完成或检查结果。

参考资料于 2026-10-15 阅读；以下是社区二创资料，不视为官方人设或模型能力评测：

- [社区设定来源整理](https://github.com/roseion/dsh-dayu-fish-skin/blob/main/SOURCES.md)：白米饭、金币与被说吃白饭时的抗议。
- [3DM 大肥鱼现象介绍](https://www.3dmgame.com/original/3746336.html)：贪吃、摸鱼、走神与嘴硬的社区喜剧题材。
- [社区桌宠角色规范](https://github.com/YunYueSama/codex-deepseek-pet/blob/main/docs/角色设定.md)：作为对照阅读，未引入该项目独有的造型或固定角色背景。

## 二、修改文件说明

| 文件 | 增删 | 改了什么、为什么 |
|---|---|---|
| `assets/characters/shenshen/manifest.json`（新增） | +5 / −0 | 在既有聊天加载器读取的位置提供 `chat.system_prompt`，让默认角色携带经用户确认的人设；不把文案写进 Python。 |
| `docs/INDEX.md`（修改） | 本次 +2 / −1；相对 HEAD +3 / −1 | 登记本报告，并在 README 的阅读触发条件中互链；该文件另有用户先前未提交的修改。 |
| 本报告（新增） | +112 / −0 | 留存授权、内容来源、实际请求读取结果与验证范围。 |

无删除文件；无 Python 产品代码或测试代码修改；`videos/manifest.json` 原有身体框、头部框不变。
新增文件用 `git diff --no-index --numstat -- NUL <文件>` 计数，已跟踪索引用 `git diff --numstat -- docs/INDEX.md` 核对，并单列既有修改。

## 三、实现要点

使用现有 `PromptBuilder` 的优先级：显式 `role_prompt` > 角色根目录 manifest > 全局默认提示词。
现代聊天、经典聊天和快捷聊天在每次发送时都调用 `build_messages`，因此已有会话的下一次发送也会重新读取角色提示词，无需改写会话历史。
动画仍读取 `videos/manifest.json`，与新增根目录聊天 manifest 的用途分开。
全局设置里的默认 System Prompt 不变；手动/主动识屏目前直接使用该全局字段，本次不扩展其路由。

## 四、性能分析

本次只有提示词文案与文档，按工程规则可按文案豁免；仍记录实际读取成本与文本增量。
环境：Windows 10 build 19045、CPython 3.13.16；修改前后各 5 组，每组 1,000 次。修改后采样时同时运行了聚焦测试与静态检查，未隔离系统负载；数值只作本机路径成本观测，不视为因果性能对照。

可复现命令（PowerShell，仓库根目录；修改前在尚无角色根 manifest 时执行相同脚本）：

```powershell
$env:PYTHONUTF8 = '1'
@'
import statistics, sys, timeit
from pathlib import Path
from pet.chat.models import ChatSettings
from pet.chat.prompt import PromptBuilder
b = PromptBuilder(Path('assets/characters'))
s = ChatSettings()
p = b.effective_system_prompt(s, 'shenshen')
r = timeit.repeat(lambda: b.effective_system_prompt(s, 'shenshen'), number=1000, repeat=5)
print(round(statistics.median(r) * 1000, 3), len(p), len(p.encode('utf-8')), sys.getsizeof(p))
'@ | .\.venv\Scripts\python.exe -
```

| 指标 | 修改前 | 修改后 |
|---|---:|---:|
| 提示词读取每次中位耗时 | 177.250 μs | 334.607 μs |
| 提示词字符数 | 28 | 1,148 |
| 提示词 UTF-8 字节数 | 84 | 3,310 |
| Python 提示词字符串对象大小 | 114 B | 2,354 B |

① 无渲染、计时器等稳态路径修改；两次聊天提示词读取观测相差 157.357 μs/次，其中也包含未隔离的系统负载差异。
② 成本发生在创建聊天会话或发送消息时，无新增轮询；模型输入每次增加 1,120 字符 / 3,226 UTF-8 字节，实际 token 数与费用随服务端 tokenizer 而异，未测量推理耗时。
③ 既有文件尝试读取现在读到一个实际 JSON 文件；成功读取会走文件内容读取系统调用，无新增文件写入、网络请求次数或线程。
④ 提示词字符串对象增加 2,240 B；无新增缓存。该数字不是进程 RSS 或峰值内存测量。

## 五、实机运行记录

在本机真实文件系统上调用 `PromptBuilder.effective_system_prompt` 与 `build_messages`，未使用 mock、未调用远程模型。

修改前公开入口探针：

```text
character_prompt_exists: False
effective_prompt: 你是一只可爱的桌面宠物，请用自然、友善的中文和用户交流。
AssertionError: Approved persona is absent from the effective character prompt
```

修改后用同一角色构造请求，并断言三段确认内容进入 system 消息、时间上下文仍附加、当前用户输入保持原样。实际输出：

```text
approved_persona_in_request: True
explicit_role_override: True
missing_character_fallback: True
geometry_unchanged: True
```

边界：不存在的角色仍回退全局提示词；显式角色覆盖仍优先；动画身体框 `[212,60,428,330]` 与头部框 `[185,60,436,195]` 未改变。
用户已经确认文案口吻；本次只确认发往模型的文本，未执行联网生成，不把提示词加载成功视为模型实际回复风格已经验收。模型会受到服务商、模型与既有对话上下文影响。

## 六、测试与验证

统一使用 `.venv\Scripts\python.exe`，Qt 测试设 `QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向 `.local/test-appdata`。

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet/ tests/` | `All checks passed!` |
| 聚焦 | `python -m pytest -q --tb=short tests/test_chat_subsystem.py::test_prompt_priority_and_limits tests/test_chat_subsystem.py::test_character_prompt_load tests/test_chat_time_awareness.py` | `8 passed in 1.63s` |
| 相关聊天入口与报告纪律 | `python -m pytest -q --tb=short tests/test_chat_subsystem.py tests/test_quick_chat.py tests/test_chat_shared_behavior.py tests/test_pr_report_discipline.py` | `313 passed, 1 skipped in 20.35s` |
| 差异检查 | `git diff --check` | 通过 |
| 全量与高负载时序复跑 | 未执行 | 仅新增提示词文案，既有加载、接口、持久化结构、生命周期和平台分派均未修改；本次不推送、不合并，无新增时序路径。 |

聚焦测试前两次在沙箱中因 pytest 临时目录 `PermissionError: [WinError 5]` 无法进入测试 setup；第二次改为新建工作区临时目录仍被拒。随后在普通本机环境运行相同聚焦用例，8 项通过。未修改产品或测试以掩盖环境问题。

## 七、风险与回滚

模型实际表现需要用户在自己的聊天服务上体验；没有能力评测、联网生成或推理性能的验收声明。
移除新增的角色根目录 manifest 即恢复此前的全局提示词回退；用户配置、密钥和会话历史无需迁移。
