# 跨会话发送 + 私聊记忆进群：让她像真人一样串起两边

日期：2026-11-04

## 现象

- 主人在私聊里跟她聊了一个故事，想让她「也去群里说说」，她做不到：发送端点要求 token 必须属于目标会话。
- 之后在群里 @ 她，她完全不记得私聊里讲过的故事：群提示词的记忆块里没有私聊记录。
- 用户原话：希望她尽量像真人一样；私下聊过的事在群里也可以自然接上，但说什么、说不说由她自己拿捏。

## 环境

| 项 | 值 |
| --- | --- |
| 系统 / DSH 版本 | Windows / DSH 0.2.1-rc.5 |
| SurfCore 版本 | 0.8.8（dev） |
| 安装方式 | worktree / git |
| 其它相关版本 | Node 24 |

## 根因

1. **发送令牌按目标绑定**：`surfcore/src/bridge.js` 的发送端点（send-message / send-burst / send-sticker / send-voice / send-poke / `/api/send/*`）都写 `agentTokenOk(key, token)`。每个二代会话有独立 `agentToken`，所以私聊里的 token 只能发到私聊。
2. **记忆可见性按会话隔离**：`surfcore/src/memory-card.js` 的 `visibleFor()` 在群会话里直接 `if (recordIsPrivate(record)) return false`，私聊记录永远不进群提示词（这是 `2026-11-02-memory-sharing-circles.md` 定下的语义）。
3. 两处叠在一起：她既发不出去，也不会在群里想起私聊内容。

## 完整逻辑（给用户看的那一遍）

- **链路**：DSH 唤醒 → `bridge.js` 组装唤醒提示（`buildWakePromptV2`）/ `qq_get_prompt` → MCP 工具 `qq_send_message` 带 `key + token` → 发送端点 → OneBot。记忆侧：inbox → `maintainMemoryCard` → `saveMemoryCardOutputs` 写 `memory-card-prompt-qq-groups.json` → `memoryCardPromptBlock(key)` 注入。
- **机制**：问题不是「哪一行写错」，而是两条契约都假设「一个会话只能动自己」：token 绑定目标、记忆按会话过滤。要更像真人，必须把「发送」从会话绑定里松出来，同时保留读取侧的严格隔离；记忆则只把「私聊 → 群」这一个方向打开。
- **爆炸半径**：桥接进程 × 所有 reserved2 会话；发送侧只放宽「令牌属于谁」，白名单/静默/暂停/限频/敏感词/引用归属全部仍按目标会话；记忆侧只影响 QQ 群提示词，私聊与桌宠可见性不变。不碰密钥、不发真实消息（测试全是夹具）。
- **取舍**：
  - A：每个发送端点各写一段跨会话判断 —— 改动分散、难测，否。
  - B（采用）：独立纯模块 `src/cross-session.js` 做判定，bridge 只调用；可单测、后续改策略只改一处。
- **生效与重启**：桥接代码改动需重启 SurfCore 桥接；记忆卡配置改动在下次记忆维护/写盘后生效。

## 修法

### 1. 跨会话发送（默认开）

`src/cross-session.js` 新增：

- `resolveSendToken({ targetKey, token, conversations, cfg, eq })`：令牌命中任意活跃会话即放行；开关 `socialV2.crossSession.enabled === false` 时回退旧行为。
- `reachableTargets()`：唤醒提示/`qq_get_prompt` 用，只列白名单群 + 主人私聊，最多 12 条，群名单行化。

`src/bridge.js`：

- 发送端点改用 `resolveSendAuth(key, token)`；读端点仍用 `agentTokenOk(key, token)`。
- 每回合发送额度（`tokenGuardSendBlock`）记到 **token 所属会话**（来源），限频/鱼群/静默/暂停仍按目标。
- 目标会话 `recentMessages` 写入 `viaKey: 'private:123'` + `viaLabel`；唤醒快照、`qq_get_recent_messages`、`qq_get_context_snapshot` 渲染成「（你在 主人私聊 / private:123 那边决定发到这里的）」，下次在目标会话醒来时知道这是自己跨会话发的。
- 目标会话没有 live wake 也能建状态并接收。

### 2. 私聊记忆进群（默认开）

`src/memory-card.js`：

- `normalizeMemorySharing()` 增加 `privateToGroups`（默认 true）。
- 群会话 `visibleFor()`：私聊记录在 `privateToGroups !== false` 时可见；桌宠记录始终排除；群↔群互通圈语义不变。
- 私聊记录保持原来的来源格式（`主人（私聊）：…` / `琳琳（私聊）：…`），不改变称呼归属；
  群里含私聊记录时追加一句分寸提示。
- `saveMemoryCardOutputs()` 额外写默认群块 `group:*`（私聊 + 手动全局记忆，不含具体群记录）；
  桥接对没有自己记录的群回退到该块。`privateToGroups=false` 时不写、不回退，保持旧隔离。

### 3. 开关与回滚

- 跨会话发送：`socialV2.crossSession.enabled: false`（回到「agent token 无效」403）。
- 私聊记忆进群：`memoryCard.sharing.privateToGroups: false`（回到 2026-11-02 的群隔离）。
- 代码回滚：`src/cross-session.js` 删除 / `bridge.js` 恢复 `agentTokenOk`；`memory-card.js` 恢复 `visibleFor` 的私聊硬排除。

## 验证

- 自动化：
  - `node scripts/test-cross-session.mjs`：helper、源码接线、真 bridge.js HTTP（跨会话发送、来源额度、viaKey、未知 token、白名单、读端点、暂停、静默、开启/关闭提示）。
  - `node scripts/test-memory-sharing.mjs`：默认私聊进群 + 标签 + 分寸提示；`privateToGroups=false` 回旧隔离；桌宠排除；按会话 map。
  - `node scripts/test-turn-quota.mjs`、`test-memory-card.mjs`、`test-memory-card-wiring.mjs`、`test-hardening.mjs`、`test-audit-bridge.mjs`、`test-callname.mjs`。
  - `npm run test:audit`。
- 失败路径：跨会话关闭/过期 token/白名单外目标/暂停/静默都返回 403；读端点用别的会话 token 仍 403。
- 没验证到的部分：真实 QQ 双会话联调（需要 SnowLuma 在线 + 两个真实会话）；语音/表情跨会话的网关侧行为只做了源码接线与 helper 验证。

## 遗留 / 后续

- 如果以后要做跨会话**读**（她主动去看别的群），需要另立安全设计；本次不做。
- 设置页没有开关（本次按约定只留 config key）。

---

## 补充：反向——私聊里回看群聊 + 群记忆进私聊（2026-11-04）

### 现象

主人先在一个群里跟她说话，她也在群里答了；随后主人在**私聊**里问「我刚才在群里说了什么」，她答不上来：

1. 读端点仍把令牌绑在目标 key 上，私聊会话的令牌读不了群会话的 recent/message-detail。
2. 记忆卡的私聊可见性只放行「当前私聊自己的记录」，群聊记录永远不进私聊提示词。

### 根因

- `bridge.js` 的 `/api/socialV2/recent` 与 `/api/socialV2/message-detail` 都写 `agentTokenOk(key, token)`；上一版只松开了发送侧。
- `memory-card.js` 的 `visibleFor()` 在 `currentPrivate` 分支里 `!recordIsPrivate(record) return false`，群记录被硬排除。

### 修法

1. **跨会话读取（默认开）**：`socialV2.crossSession.read !== false` 时，`/recent` 与 `/message-detail` 接受任意活跃二代会话令牌读**白名单内**的目标；`src/cross-session.js` 新增 `crossSessionReadEnabled()` / `resolveReadToken()`，bridge 里对应 `resolveReadAuth()`。
   - 其余端点（unread / mark-read / snapshot / memory-* / state / prompt / wake-config / close / wait / forward-* / images / stickers 等）仍严格 `agentTokenOk`，跨会话一律 403。
   - 跨读走 `peekSocialV2State()`：不新建目标状态、不挂定时器；也不调用 `noteModelMessagesV2()`，所以目标未读数、读水位、`lastActionAt`、`noActionCount`、`modelSeenSeqs` 都不变；不记发送额度。
   - `message-detail` 的 message id 仍必须在**目标会话**里（本地 recent 或按目标 kind/id 查网关）。
2. **群记忆进私聊（默认开）**：`memoryCard.sharing.groupsToPrivate !== false` 时，私聊 `visibleFor()` 放行「任意群聊记录 + 手动全局记忆」；别人的私聊、桌宠记录仍排除；群记录保留 `群聊·群名 / group:ID` 来源。
   - 私聊块含群记录时追加一句分寸提示：`带「群聊」标记的是群里发生的事：私聊里让对方知道之前，像真人一样想想该不该说。`
   - `saveMemoryCardOutputs()` 额外写默认 `private:*` 块（合成 key `private:*` 不匹配任何真实私聊，只装群聊 + 手动记忆）；bridge `memoryCardPromptBlock()` 对 map 里没有的 `private:N` 回退到它，镜像 `group:*`。
3. **提示词 / 工具描述**：`crossSessionPromptInfo()` 增加 `read`；`crossSessionPromptLine()` 在读开关开启时追加 `【跨会话读取】…qq_get_recent_messages / qq_get_message_detail…`。`mcp-snowluma-safe.js` 的两个工具描述说明 key 可以是别的会话、token 仍用当前令牌。

### 开关与回滚

- 跨会话读取：`socialV2.crossSession.read: false`（recent/message-detail 回到旧的 403）。
- 群记忆进私聊：`memoryCard.sharing.groupsToPrivate: false`（回到「私聊只看自己的私聊」，且不写/不回退 `private:*`）。
- 两个开关互相独立，也分别独立于发送侧的 `socialV2.crossSession.enabled` / `memoryCard.sharing.privateToGroups`。
- 代码回滚：bridge 两个读端点恢复 `agentTokenOk`；`memory-card.js` 恢复 `currentPrivate` 的硬排除并删除 `private:*` 分支。

### 隐私取舍

打开后，**私聊里的任何人**都可能从她的记忆/回看里得知群里发生的事；是否转述由她按分寸提示自行判断，不设硬拦截。若不想承担这个风险，把 `groupsToPrivate` 或 `crossSession.read` 设为 `false`。

### 验证

- `node scripts/test-cross-session.mjs`：read helper、默认跨读 200 / `read=false` 403、非白名单/过期令牌 403、其它端点仍 403、跨读不改目标未读/读水位/lastActionAt/唤醒计数、提示词只在读开关开时出现 `【跨会话读取】`。
- `node scripts/test-memory-sharing.mjs`：默认私聊看到任意群记录 + 来源标签 + 分寸提示；别人的私聊/桌宠排除；`groupsToPrivate=false` 回旧隔离；`private:*` 默认块写入/不写入。
- `node scripts/test-memory-card-wiring.mjs`：`private:N` 缺块回退 `private:*`，没有 `private:*` 时保持空块（fail closed）。

## 补丁：真机私聊里仍读不到群消息（快照工具没接跨读）

### 现象

- 合入跨会话读取后真机测试：群记忆能进私聊，但在私聊里让她「看看群里刚才说了什么」，她说读不到群消息。

### 根因

- `src/mcp-snowluma-safe.js` 按工具档位（`socialV2.toolProfile`，默认 `balanced`）在**注册期**隐藏
  `qq_get_recent_messages`，模型手里只有合并工具 `qq_get_context_snapshot`。
- 跨会话读取只接了 `/api/socialV2/recent` 与 `/message-detail`；`/api/socialV2/snapshot` 仍是 `agentTokenOk` 严格绑定。
- 提示词点名的又是被隐藏的 `qq_get_recent_messages` —— 模型既看不到这个工具，能用的快照又被 403。
- 测试只打 HTTP 端点、没核对「提示里点名的工具在默认档位是否注册」，所以单测全绿、真机不通。

### 修法

- `/api/socialV2/snapshot` 接 `resolveReadAuth`；跨读用 `peekSocialV2State`（不建状态），不附带目标会话的
  「去 wait/unread」催促（`unreadNotice`），本会话读取行为不变。
- 提示词 `【跨会话读取】` 改为点名 `qq_get_context_snapshot`（有 recent 工具时也可用）；快照工具描述补「key 可以是别的会话、token 用当前」。
- 测试：`test-cross-session.mjs` 增加快照跨读 200 / `read=false` 403、目标状态不变、提示点名快照工具，
  以及守卫「`balanced` 隐藏列表不得包含 `qq_get_context_snapshot`」；`audit-bridge-harness.mjs` 补注入 `context-snapshot.js`
  （此前夹具里快照端点只能走到 403，成功路径从未被执行过）。
