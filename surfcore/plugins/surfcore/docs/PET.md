# 桌宠（桌面客户端）

SurfCore 的「桌宠」是一个**独立栏目**，和 QQ / B站 / 记忆 / 语音平级，互不依赖：

- 桌面桌宠是 desktop-pet 仓库根目录的 **PySide6 程序**，不随 SurfCore 安装，也没有安装按钮；
- 它自己读取 `~/.dsh/surfcore/pet/host.json` 连接本插件的 pet-api，所以不需要 SurfCore 启动/停止它；
- 「桌宠」页只显示它的**在线 / 离线**与最近连接时间，以及对话参数。

> 2026-10-25 起，桌宠不再只是「会动的形象」：它和 SurfCore 共用**当前角色**（人格卡 + 衰减记忆卡 + 目的机制），
> 支持 **文本对话 / 语音对话**，也能作为**「目的」栏目的主动搭话载体**。

---

## 1. 两个入口

| 位置 | 用途 |
| --- | --- |
| 设置 → SurfCore → **桌宠** | 桌面客户端**在线状态 / 最近连接**、**对话参数**（开关 / 回复字数 / 上下文轮数 / 思考强度）、专注模式 |
| 设置 → SurfCore → **目的** | 目的机制本身：**触发载体（桌宠 / QQ）**、桌宠主动搭话形式（**文本 / 语音**）、节奏与安静时段、素材、预览、立即试一次 |

「目的」独立于 QQ / B站 / 记忆：只改载体，不改人格与记忆；同一时刻**只有一个载体**在发消息。

---

## 2. 在桌面上怎么用

1. 在桌宠上**右键** → **文本对话** / **语音对话**（托盘菜单同一组入口）。
2. 弹出对话框，输入后发送：
   - 文本对话 → 她用文字回；
   - 语音对话 → 她用语音回（TTS），**气泡里同时显示文字**。
3. 她的每一句话都会在桌宠上方的**气泡**里出现：
   - 主动搭话 → 气泡带「主动来找你」标签；
   - 语音 → 气泡里有播放按钮和时长；
   - **所有气泡都有「回复」按钮**：点它跳到对话框，并按这句话的形式打开（语音→语音对话，文本→文本对话）。
4. 气泡会在几秒后自动收起；鼠标停在气泡上会暂停计时（最多 60 秒）。
   新的一句话会立即顶掉旧气泡，不会排队堵住。

对话框里还能：切「文本 / 语音」模式、重播历史语音、断线时点「重连」。

### 专注模式（不主动打扰）

右键 / 托盘菜单最上面有 **「专注模式（不主动打扰）」**（勾选状态），设置 → 桌宠 → 对话里也有同一个开关。

- 开：**目的机制的自动主动搭话全部暂停**（载体 = 桌宠 或 QQ 都不发）、桌宠不弹主动气泡 / 不播主动语音；
  已经弹出的气泡会立刻收起。**你自己打开对话框聊天仍然正常**。
- 关：恢复；下一次 tick（≤60 秒）重新按排程判断。
- 「目的」页的手动「立即试一次」不受影响——那是你主动点的。
- 单一真相：`~/.dsh/surfcore/pet/focus.json`。桌宠菜单、设置页、插件 tick、QQ 桥接的自动 tick 都读它；
  所以桌宠没开、只在 QQ 里也会遵守（桥接每 10 秒读一次）。

---

## 3. 和 SurfCore 角色的关系

| 上下文 | 来源 |
| --- | --- |
| 人格 | 当前角色的 `persona.md`（`~/.dsh/surfcore/characters/<id>/persona.md`，或旧布局 `roles/*.md`） |
| 长期记忆 | 当前角色记忆卡的 **QQ 注入块**（`memory-card-prompt-qq.md`，会随时间衰减） |
| 心事 / 动机 | 目的状态里的 `pending` / 目标假设 / 最近情绪（`purpose-outreach.json`） |
| 私聊对象 | 设置 → SurfCore 的「管理员」（显示名 / QQ） |
| 模型 | DSH 默认模型（设置 → 模型；默认 `deepseek-account` / `deepseek-flash`），可用「思考强度」控制速度 |
| 语音 | 「语音」页的 TTS 配置（`socialV2.voice.tts`）：本地 / 云端路由、音色、字数上限 |

对话**不会**走 DSH 的完整 agent 回合（那会带上所有工具和几万 token），而是插件直接调 DSH 的 `llm` 服务：
人设 / 记忆 / 说话规则拼成 system prompt，一次调用出结果。用量会补记到 token 额度「其他」分类。

### 记忆：桌宠的话也会写进同一张卡

以前记忆卡只从 **QQ**（主人私聊 / 群聊 / 她自己的发言）和 **B站**（视频 / 动态 / 想法）摄取；
2026-10-25 起，桌宠对话也走同一条管道：

```
桌宠 /chat 成功 → 插件追加两条 inbox 事件（platform=pet：主人说的 / 她回的）
  → 记忆卡维护器把「她回的」并进最近一条 pet-owner，形成一问一答
  → 同一套重要度评分 / 脱敏 / 每日遗忘 / 容量压缩
  → 「## 桌宠（私下相处）」小节注入 QQ 与桌宠提示词
```

- 开关：设置 → 桌宠 → **「把桌宠对话写进记忆卡」**（默认开）。关掉就只留在聊天记录里，不写卡。
- 记忆卡总开关（设置 → 记忆）关掉时不会写；已存在的记录不删。
- `scope=pet`：**默认不注入 B站**（B站只看公开/共享记忆）；QQ 和桌宠都能读到。
- 提示词预算紧张时，桌宠小节优先于「最近记得的」被保留（有回归测试钉住），不会被普通最近记忆挤掉。
- 全量卡里单独归到「桌宠（私下相处）」；原始 inbox 行仍保留在 `memory-inbox.jsonl`，去重靠 `inboxSeen`。
- 主动搭话也会落一条 `pet-self`（她主动说的那句），和问答案件分开。

### 语音：跟随「语音」页的本地 / 云端

桌宠**每次合成前都重读** `socialV2.voice.tts`，所以「语音」页切换本地 / 云端后**立刻生效，不用重启桌宠**：

- 路由 = `route`（`local` / `cloud`），地址 = `endpoints[route]`（8765 / 8767）；
- 切换动作本身就是语音页的启动按钮（`POST /api/voice/packs/activate`，会写 `route` 并只留一个引擎在跑）；
- 合成失败（引擎没起、依赖服务没起）→ 只降级成文字，气泡照常显示，不会假装发了语音；
- 桌宠设置页/目的页会显示当前路由与地址，便于核对。

---

## 4. 主动搭话：和 QQ 共用一套目的机制

```
素材（QQ 私聊/群聊 + B站 + 记忆卡 + 人格卡 + 惦记的事）
  → 驱动 / 目标假设（归属 / 置信度 / 价值 / 风险）
  → 选择这一轮要说的目的
  → 载体 = 桌宠 ? 插件生成一句话推给气泡（可选 TTS）
              : 桥接在她的 QQ 会话里调 qq_send_private_message
  → 回执 / 目标记账 / 排下一枪
```

- **同一份配置**：`config.json` 的 `purpose.*`（`carrier` 决定载体，`petModality` 决定桌宠用文本还是语音）。
- **同一份状态**：当前角色目录下的 `purpose-outreach.json`（今日次数 / 下次时间 / 惦记的事 / 目标 / 历史）。
- **互斥**：载体 = 桌宠时，桥接的自动 tick 不再出发（每次 tick 重读 `purpose.carrier`，30 秒内生效）；
  载体 = QQ 时，插件的桌宠 tick 直接返回。所以不会桌宠和 QQ 同时收到一条。
- **回落**：`purpose.petFallbackToQQ`（默认开）—— 桌宠没开着时，这一轮交给桥接按它自己的闸门发 QQ；
  关掉则宁可这轮不发。无论哪种，都不会两边都发。
- **手动试一次**：「目的」页的按钮按当前载体路由：桌宠 → 直接推一条到气泡；QQ → 交给桥接。
- **专注模式**：`focus.json` 开着时，两边的**自动** tick 都停（QQ 桥接也读同一份），只有手动「试一次」还能发。
  见第 2 节的「专注模式」。

> 细节见 [../guides/PURPOSE_OUTREACH.md](../../../docs/guides/PURPOSE_OUTREACH.md) 的「载体」一节。

---

## 5. 数据位置

```
~/.dsh/surfcore/pet/
  host.json            桌面端发现文件：{ baseUrl, token, api, pluginVersion }（插件每次启动/每 2 分钟重写）
  host-token           本地令牌（0600；host.json 里是同一把）
  focus.json           专注模式：{ enabled, updatedAt, source }（桌宠/设置页/桥接共读）
  chat/
    history-<charId>.json   对话历史（气泡重放 / 模型上下文）
  voice/               TTS 缓存（wav，内容寻址）
```

- `host.json` 里的 `token` 只在本机回环上使用；DSH 端口漂移后桌宠会自动重读这个文件。
- 对话历史按**角色**分开：换角色后不会串台；目的状态同样按角色隔离。
- 桌面桌宠的程序与数据在 desktop-pet 仓库里管理，SurfCore 不再写 `pet/app/`、`pet.pid` 或安装配置。

---

## 6. 启动与连接（用户操作）

1. 从 desktop-pet 仓库启动桌面桌宠（`python -m pet` 或该仓库的启动脚本）。
2. 桌宠自己读 `~/.dsh/surfcore/pet/host.json`，连接 SurfCore 的 pet-api，并长轮询 `/events`。
3. 设置 → SurfCore → **桌宠**：显示「桌宠在线 / 离线」与最近连接时间；几秒内没上线就刷新一次。
4. 对话参数（启用 / 回复字数 / 上下文轮数 / 思考强度 / 专注模式）仍在这里改；不需要重启桌宠。

桌面桌宠的启动、皮肤、进程管理都在 desktop-pet 仓库；SurfCore 不安装、不启动、不停止、不更新它。

---

## 7. 宿主接口

设置页（走 DSH 会话鉴权）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dsh-surfcore/api/pet/status` | 桌面客户端 `client.{online,lastSeenAt}`、**对话 / 语音 / 模型 / 专注** |
| POST | `/dsh-surfcore/api/pet/chat-test` | 在设置页发一句，结果推给桌宠气泡 |
| POST | `/dsh-surfcore/api/pet/focus` | 设置页切换专注模式（`{ enabled }`），并推事件给桌宠 |
| GET | `/dsh-surfcore/api/purpose/status` | 目的状态（按载体路由到插件或桥接） |
| POST | `/dsh-surfcore/api/purpose/preview` | 只读预览（零副作用） |
| POST | `/dsh-surfcore/api/purpose/run` | 立即按当前载体出发一次 |

桌宠进程（**不能**用上面的路径：DSH 的 `connection.requestRejection` 会因为没有会话 Cookie 返回 401）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dsh-surfcore/pet-api/health` | 探活 |
| GET | `/dsh-surfcore/pet-api/status` | 对话 / 语音 / 模型 / `client.{online,lastSeenAt}` / 事件游标 |
| GET | `/dsh-surfcore/pet-api/config` | 角色名、对话上限、主动搭话载体与形式 |
| GET | `/dsh-surfcore/pet-api/history?limit=` | 对话历史（含语音回放地址） |
| POST | `/dsh-surfcore/pet-api/chat` | `{ text, modality }` → 文本/语音回复 |
| POST | `/dsh-surfcore/pet-api/chat/test` | 同上，并把结果作为事件推给所有桌宠（设置页测试用） |
| POST | `/dsh-surfcore/pet-api/focus` | `{ enabled, source }` → 写 `focus.json`，并推 `focus` 事件唤醒长轮询 |
| GET | `/dsh-surfcore/pet-api/events?since=&wait=` | 长轮询：主动搭话 / 测试回复事件 |
| GET | `/dsh-surfcore/pet-api/audio/<key>.wav?token=` | 语音回放 |
| GET/POST | `/dsh-surfcore/pet-api/purpose/*` | 目的状态 / 预览 / 手动出发（本地排障） |

鉴权：`x-pet-token: <host.json.token>`（音频用 `?token=`）。只接受 127.0.0.1 / localhost / ::1；
写操作必须是 `application/json`，且 Origin 同源（或没有 Origin）。

实现：`lib/pet-chat.js`（对话/语音/事件）、`lib/pet-purpose.js`（目的载体）、
`lib/pet-api.js`（桌宠专用路由）；设置页路由在 `lib/index.js` 的 `handlePet` / `handlePurpose`。
桌面桌宠本身在 desktop-pet 仓库的 `pet/`（PySide6），不在本插件里。

---

## 8. 为什么不再有「安装目录」

SurfCore 侧不再安装桌宠，因此也没有 `pet/app` / Electron 路径可填。桌面桌宠的安装、运行参数和
Chromium/Qt 环境由 desktop-pet 仓库自己的启动方式决定；插件只提供 pet-api 与发现文件。

## 9. 运行状态怎么判断

「在线」= 桌面桌宠在 60 秒内长轮询过 `/events`（或请求过 pet-api），由 `petChat.online()` 记录；
设置页显示同一个 `client.online` / `lastSeenAt`，主动搭话的回落判断也看它。
SurfCore 不再检查 pid 或安装目录。

---

## 10. 排障

| 现象 | 先看什么 |
| --- | --- |
| 对话框一直「没连上 SurfCore」 | `~/.dsh/surfcore/pet/host.json` 是否存在；SurfCore 插件日志；desktop-pet 侧日志里的 `[chat] surfcore connected` |
| 设置页测试有回复，但桌宠没气泡 | 「桌宠」页的在线徽章；桌宠是否在跑**新版**（右键菜单里有「文本对话」） |
| 语音回复没声音 | 「语音」页的 TTS 是否启动（本地 8765 / 云端 8767）；气泡里的播放按钮是否可点；文字回复是否正常（语音失败只降级文字） |
| 切了本地/云端，桌宠没跟着 | 看「语音」页的「当前」和桌宠设置页的「语音：…」是否一致；改完不需要重启桌宠，下一次合成就重读配置 |
| 专注模式开了还在主动搭话 | 看 `~/.dsh/surfcore/pet/focus.json` 的 `enabled`；桥接每 10 秒重读，插件每次 tick 读；手动「试一次」本来就不受限制 |
| 桌宠对话没进记忆卡 | 「桌宠 → 把桌宠对话写进记忆卡」是否开；设置 → 记忆的总开关；记忆卡是每 10 分钟整理一次，急的话点记忆页「立即整理」 |
| 桌宠和 QQ 都发主动搭话 | 检查 `purpose.carrier`；载体 = 桌宠时桥接应跳过自动 tick（插件日志会写 `[pet-purpose]`） |
| 手动「立即试一次」报 `pet-offline` | 桌宠没在跑 / 还没连上；先启动，或把载体切回 QQ |
| QQ 载体「立即试一次」报 `SNOWLUMA_OFFLINE` / `SEND_RECENTLY_FAILED` | SnowLuma 没启动或没登录（3000/3001 端口不在），或访问令牌不一致（`unauthorized`）；启动 SnowLuma、等概览页 QQ 显示已连接再试。旧版本这里会假报「已投递」、QQ 收不到（PITFALLS #127） |
| 插件刚重启后第一条主动搭话没收到 | 事件游标随插件重启归零，客户端会先取新水位（不重放旧消息）；下一条正常 |

---

## 11. 注意

- 桌面桌宠是 desktop-pet 仓库里的独立 PySide6 进程，SurfCore 不安装、不启动、不停止它，也没有安装包来源或 Electron 路径。
- 它自己读 `host.json` 连过来；SurfCore 退出后它会显示离线，重新打开 DSH 后会自己重连。
- 对话内容会落在 `pet/chat/history-<角色>.json`，模型调用会算 token；不想要就把「启用桌宠对话」关掉。
