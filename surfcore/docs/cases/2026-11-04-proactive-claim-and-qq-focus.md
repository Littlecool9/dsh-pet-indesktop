# 共享主动说话额度 + QQ 主人专注上下文

## 现象

- 桌宠的视觉观察 / 自言自语和 SurfCore 目的机制各自判断「能不能主动说话」，
  两边都用自己的计数器；同一天可能连着发两条，也会互相覆盖 `purpose-outreach.json`。
- 主人开着专注模式时，QQ 侧的小肥鱼完全不知道，仍然按普通上下文回复；
  用户要求：QQ 继续回复，但要知道「主人在专注 / 休息 + 大概几点结束」，**不能知道工作内容**。

## 根因

- 目的状态文件（`characters/<id>/purpose-outreach.json`）被两个进程读写：
  - 插件：`plugins/surfcore/lib/pet-purpose.js`（桌宠载体 + 新的 claim）；
  - 桥接：`src/bridge.js`（QQ 载体，启动时把状态读进内存）。
  桥接不重新合并磁盘计数时，会用自己的旧 `countToday/lastSentAt` 覆盖插件刚写的值。
- 专注真相只有插件进程写的 `~/.dsh/surfcore/pet/focus.json`，QQ 提示词拼装
  （`withSlangContext`）之前只读了一个布尔值，没有阶段/结束时间。

## 接口与规则

`POST /dsh-surfcore/pet-api/proactive/claim`（和其它 pet-api 一样：回环 + `x-pet-token`）

```json
请求：{ "source": "vision" | "self-talk" | "任意非空字符串" }
放行：{ "ok": true, "granted": true, "remainingToday": 1, "nextAllowedAt": 1700000000000 }
拒绝：{ "ok": true, "granted": false, "reason": "focus|quiet|daily|gap", "retryAt": 1700000000000, "hint": "下一步做什么" }
```

判定顺序（`pet-purpose.js` 的 `claim()`）：

1. `chat.focusEnabled()` → `focus`（retryAt = focus.json 的 endsAt，未知则 0）
2. `inQuietHours` → `quiet`，retryAt = `quietEndAfter`
3. `dailyMax > 0 && countToday >= dailyMax` → `daily`，retryAt = `nextDayStartAfter`
4. `now - lastSentAt < gapMinMs` → `gap`，retryAt = `lastSentAt + gapMinMs`
5. 放行：`countToday += 1`、`lastSentAt = now`、`lastClaim = { source, at }`、
   `nextFireAt = max(nextFireAt, now + gapMinMs)`，原子写回。

- 每次 claim 都**从磁盘重读**并先 `ensurePurposeDay`（跨天清零），不复用内存缓存。
- `remainingToday`：`dailyMax = 0`（不限次）时为 `null`。
- 请求体不是合法 JSON → `400 code=invalid-json`；`source` 缺失/空白/非字符串
  → `400 code=invalid-source`；两者都带 `error` + `hint`。额度拒绝仍是 HTTP 200。

桥接侧：`bridge.js` 的 `mergePurposeCountersFromDisk()` 在每次目的 tick 判定前
（`runPurposeOnce` 里、`evaluatePurposeTick` 之前）读磁盘同一天的状态，
`countToday` / `lastSentAt` 各取 max，避免把插件领走的额度覆盖掉。

QQ 专注上下文：`src/pet-focus-context.js`

- `readPetFocus(file)`：缺失/损坏/非法 → `{ enabled:false, phase:'', endsAt:0 }`。
- `focusContextLine(focus, now)`：专注关 → `''`；`work` →
  `【主人状态】主人正在专注，预计 HH:MM 结束（不知道他在做什么，别打听）`；
  `short_break/long_break` → `【主人状态】主人在专注间隙休息，预计 HH:MM 回到专注`；
  `endsAt` 为 0 或已过去时省略时间。只有状态与时间，**永不包含工作内容**。
- `bridge.js` 的 `petFocusEnabled()` 改用 `readPetFocus`（保留 10 秒缓存），
  `withSlangContext()` 把这一行插在【当前时间】之后、黑话块之前。

## 完整逻辑

- **链路**：桌宠/视觉 → pet-api `/proactive/claim` → `pet-purpose.claim()` →
  `purpose-outreach.json`；QQ → `bridge.js` 目的 tick → 同一文件（合并计数）。
  专注：桌宠 → `/focus` → `pet-chat.setFocus()` → `pet/focus.json` →
  `pet-focus-context.readPetFocus()` → `withSlangContext()` → QQ 每轮提示词。
- **机制**：两个进程共享一份状态文件，唯一安全的合并方式是「先读盘、同日取 max」；
  claim 先判定再写，桥接判定前合并，双方都不会把对方的 +1 抹掉。
- **爆炸半径**：2 个进程 × 2 个读者（插件/桥接，外加桌宠只读 claim 结果）；
  只写本机 `~/.dsh/surfcore` 状态，不碰密钥、不发 QQ、不花钱。
- **取舍**：A 引入跨进程锁/单写者服务，收益小且改动大；B 每次读盘 + 同日取 max，
  成本低、失败可回退（删掉 claim 路由即恢复旧行为）。选 B。
- **生效与重启**：插件/桥接各自重载后生效；focus 提示词最多延迟 10 秒（缓存）。

## 验证

```bash
# 插件（在 surfcore/plugins/surfcore）
node scripts/test-pet-purpose-claim.mjs
node scripts/test-pet-api.mjs
# 审计（在 surfcore/）
node scripts/test-pet-focus-context.mjs
```

自动化覆盖：grant / focus / quiet / daily / gap / 跨天 / 磁盘重读 / nextFireAt 推后；
pet-api 的 401、400（invalid-json / invalid-source）、200 两种 granted；
focusContextLine 的阶段/时间/隐私措辞；bridge 源码接线检查。

没验证到的部分：真实 QQ 会话里的提示词效果需要启动桥接后人工观察（本任务不启动服务）。

## 回滚

- 删除 `/proactive/claim` 路由与 `claim()`、删除 bridge 的合并调用即可回到旧行为；
- focus 上下文只影响提示词，删掉 `withSlangContext` 里的两行注入即恢复。
