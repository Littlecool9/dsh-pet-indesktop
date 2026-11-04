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
