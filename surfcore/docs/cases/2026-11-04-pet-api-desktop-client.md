# 桌宠本地接口扩展：人格 / 自言自语 / 额度 / 直连用量 / 专注阶段

## 现象

- 桌面端要从旧 Electron `surfpet` 换成 SurfCore 的 PySide6 桌宠客户端，但 `/dsh-surfcore/pet-api` 只有对话、历史、专注开关等旧路由：
  - 客户端拿不到当前人格卡，无法做本地缓存；
  - 桌宠想按自己的节奏说一句心里话，没有接口，也不想污染聊天历史 / 记忆卡；
  - 桌宠直连模型（对话窗、看图）的用量没有 DSH 会话事件可采，额度看板会漏；
  - 专注模式只有开 / 关，客户端排不出「工作 / 短休息 / 长休息 + 预计结束时间」。
- 影响面：只新增只读 / 按需接口，不改已有对话与主动搭话行为；不碰用户数据。

## 环境

| 项 | 值 |
| --- | --- |
| 系统 | Windows |
| Node | v24（`E:\NodeJs\node.exe`） |
| SurfCore | 仓库内 `surfcore/`（0.8.8，未 bump） |
| 安装方式 | 工作树 + run_surfcore.py 链接 node_modules |

## 根因 / 设计

- `pet-api.js` 的路由只覆盖旧能力；`pet-chat.js` 里已有 `roleInfo / ownerInfo / memoryBlock / purposeBackground / complete / tokenBudget`，缺的是把它们组合成桌宠客户端需要的稳定形状。
- 额度服务 `token-budget.js` 已有 `status({takeAlertFlag})`、`block(scope)`、`recordExternalUsage({category, sessionId, label, model, usage})`，足够支撑新接口，不需要改额度模型。
- 专注状态唯一真相仍是 `pet/focus.json`；新字段只做归一化与透传，旧文件（没有 `phase/endsAt`）按空值读取。

## 完整逻辑

- **链路**：PySide6 桌宠 → `POST/GET /dsh-surfcore/pet-api/*`（回环 + `x-pet-token`）→ `pet-api.js` → `pet-chat.js` → 人格 / 记忆 / 目的状态、`llm` 服务、`token-budget` 服务；专注写 `~/.dsh/surfcore/pet/focus.json` 并推 `focus` 事件给长轮询。
- **机制**：
  - `/persona` 只读 `roleInfo()`，`hash` 是合成后人格文本的 sha1 前 12 位，客户端据此判断缓存是否失效。
  - `/self-talk` 同一时刻只允许一条在飞（`busy`），先查 `tokenBudget.block('other')`，再走 `complete()`；结果只返回文本，不写历史、不写记忆 inbox、不 `emit()`。
  - `/budget` 组合 `status()` + `block('other')`；没有额度服务时明确返回 `available:false`，不假装额度无限。
  - `/usage` 校验 `usage` 必须是非空对象且已知 token 字段为非负数字，再以 `other / pet-direct` 记账。
  - `/focus` 的 `phase` 只认 `work / short_break / long_break`，`endsAt` 接受 epoch 毫秒或 ISO 字符串；关闭专注会清空两者。
- **爆炸半径**：只影响桌宠客户端接口；模型调用只发生在 `/self-talk`，且被额度闸门保护；不写聊天 / 记忆，不改 QQ 桥接和目的引擎。
- **取舍**：新能力放 `pet-chat.js` 而不是在 `pet-api.js` 里直接拼提示词——路由保持薄，人格 / 记忆 / 目的 / 额度都只有一个入口；代价是 `pet-api` 的假服务测试需要同步补齐新方法。
- **生效与重启**：插件热重载后新路由生效；桌宠重新读取 `host.json` 即可。无需重启 QQ 桥接。

## 接口与失败码

| 方法 | 路径 | 成功形状 | 说明 |
| --- | --- | --- | --- |
| GET | `/persona` | `{ok, role:{id,name}, persona, owner:{name}, hash}` | 只读，不调模型；`hash` 为 12 位十六进制 |
| POST | `/self-talk` | `{ok, text, role:{name}}` | body `{context?:{focus?:{phase,endsAt}, recent?}}`；一次一句 ≤40 字 |
| GET | `/budget` | `{ok, available, scope:'other', blocked, message, usage, limits, ratios, blockedScopes, day, alert, alertedToday}` | 无服务时 `{ok:true, blocked:false, available:false}` |
| POST | `/usage` | `{ok, recorded, label, model}` | body `{model, usage, label?}`；`label` 截 40 字并加 `桌宠直连：` 前缀 |
| POST | `/focus` | `{ok, focus:{enabled, phase, endsAt, ...}}` | 在旧 `enabled/source` 上扩展 `phase/endsAt` |

失败响应统一 `{ok:false, code, error, hint}`：

- `invalid-json`（400）：body 不是合法 JSON。
- `invalid-usage`（400）：`usage` 不是对象、没有已知 token 字段，或字段不是非负数字。
- `busy`（409）：上一条自言自语还在生成。
- `budget-blocked`（429）：`other` / 总额度已到上限。
- `llm-unavailable`（503）：DSH 模型服务未就绪。
- `budget-unavailable`（503）：额度服务未接入或读取失败。
- `model-failed` / `empty-reply` / `usage-record-failed`（502/502/503）：模型失败、空回复、记账失败。

## 修法

- `pet-chat.js`：新增 `persona()`、`selfTalk()`、`budget()`、`recordDirectUsage()`；`recordUsage()` 支持自定义标签；`readFocus/setFocus/publicEvent` 增加 `phase/endsAt` 归一化与透传；导出 `cleanSelfTalk` 与专注字段纯函数。
- `pet-api.js`：新增 4 条路由并扩展 `/focus`；所有新失败返回 `code/error/hint`，并沿用回环 + 同源 + `x-pet-token` 判据。
- 测试：`scripts/test-pet-api.mjs` 钉路由 / 鉴权 / 状态码映射；新增 `scripts/test-pet-self-talk.mjs` 用临时 `DSH_HOME` + 假模型 / 假额度服务钉行为（不碰真实 `~/.dsh`）；两脚本都已进 `plugins/surfcore/package.json` 的 `test`。
- 回滚：还原以上文件即可；`focus.json` 新增字段对旧客户端是可选字段，旧文件继续可读。

## 验证

- `node plugins/surfcore/scripts/test-pet-api.mjs` → 全绿，含 `/persona` 401、`/self-talk` busy 409 / 额度 429 / 非法 JSON 400、`/budget` 503、`/usage` 400、`/focus` phase/endsAt 透传。
- `node plugins/surfcore/scripts/test-pet-self-talk.mjs` → 全绿，覆盖人格文本与 hash、自言自语不写历史/记忆/事件、额度检查与 `桌宠自言自语` 记账、并发 busy、各失败码的 `code/hint`、直连用量校验、专注字段持久化/事件/旧文件兼容。
- `node plugins/surfcore/scripts/test-pet-chat.mjs` → 原有纯逻辑与专注开关回归仍绿。
- 集成：`python .scratch/modularization/run_surfcore.py` → `run_surfcore: rc=0`。

## 遗留 / 后续

- 桌宠客户端需要自己决定「每小时大概说一句」的节奏；SurfCore 只提供按需生成，不记录这句话。
- 旧 Electron `surfpet` 的安装 / 更新代码未在本任务删除。
