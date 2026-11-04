# 2026-11-04 「每次醒来最多发 8 条」改为按对方新消息重新计

## 现象
私聊里和她来回聊了 4 轮（每轮 2 条），她再回就被拦：`Token 防爆破：本次醒来最多发 8 条（已发 8 条）`。
gate 事件 19:33:42Z / 19:34:40Z 两次 `TOKEN_GUARD_SEND_LIMIT private:<管理员>`。

## 定位（只读）
桥接日志（本地时间）：11:32:17 因补历史醒来一次 → 期间主人的消息全部「会话繁忙，暂存唤醒原因」并进同一回合 →
11:32:43 / 11:33:12 / 11:33:34 / 11:33:40 各「工具统一发送 成功 2/2 条」= 8 → 第 9 条被拦 → 11:34:47 回合收尾。

## 完整逻辑
1. **链路**：入站消息 → `scheduleWakeV2(key, reason)` →（会话繁忙）暂存原因；（空闲）8 秒合并后 `sendWakePromptV2` 新醒来并 `resetTokenTurn`。
   发送工具 → `tokenGuardSendBlock` → `evaluateOutbound(used=tokenTurnSent)`。目的回合 `runPurposeOnce` → `deliverPrompt`（不经 `sendWakePromptV2`）。
2. **机制**：计数只在「新醒来」清零，而实时对话中模型留在同一回合里等消息，所以一场对话共用 8 条；目的回合连清零都没有。
3. **爆炸半径**：1 进程（桥接）× 所有私聊/群会话；以前是「误拦」（报错=1，有 gate 事件），现在放宽了刷新条件。不碰密钥/用户数据；
   花钱面：每条直呼消息最多再换 8 条，仍受每分钟发送频率、每日唤醒次数、每日花费上限约束。
4. **取舍**：
   - A（选）：直呼类新消息并入回合时刷新名额。保持「一个请求最多 8 条」的防刷屏语义，实时对话不再误拦。
   - B：只调大 `maxOutboundPerTurn`。不改代码，但长对话迟早还会撞上，且单次刷屏上限也一起变大。
   - C：每条入站消息都刷新。群里闲聊会让名额永远用不完，防爆破失效，弃。
5. **生效与重启**：`src/bridge.js` / `src/token-guard.js` 需重启 QQ 桥接；`client.js` 设置页说明重开设置页生效。
6. **验证**：
   ```text
   node scripts/test-turn-quota.mjs        # 5 PASS；修复前 4 红 1 绿（绿的是「群里闲聊不刷新」护栏）
   node scripts/test-purpose-wiring.mjs    # 11 PASS
   node scripts/test-reply-wait.mjs        # 12 pass / 0 fail
   npm run test:regressions                # 全部通过
   npm run test:audit                      # 135/142，失败集合与修改前相同（时区相关 5 个 + 工作树缺 config.json / git 布局 2 个）
   ```
   `test-token-guard.mjs` 在本机（UTC-8）第 12 行时区断言就退出；单独抽出其「发送条数」与「桥接接线」两段跑，均通过。
   真机：私聊里连续来回 5 轮以上，不再出现 `TOKEN_GUARD_SEND_LIMIT`，日志出现 `[token-guard] private:… 本回合发送名额重新计`。
7. **回滚与残余**：`git revert` 本提交。群里引用回复她的消息也会刷新（`bridge.js` 里 `atSelf || quoteTargetIsSelf` 都归为 `atMention`）。
   残余：真机长对话尚未验证。

## 修法
- `src/bridge.js`：新增 `refreshTokenTurnOnDirectMessage`，在两处「暂存唤醒原因」后调用；`runPurposeOnce` 投递前 `resetTokenTurn(st)`；
  提示词【Token 防爆破】说明重新计的条件。
- `src/token-guard.js`：拦截文案「本次醒来」→「本轮」。
- `plugins/surfcore/lib/client.js`：设置项说明。
- `scripts/audit-bridge-harness.mjs`：导出 `scheduleWakeV2`；新增 `scripts/test-turn-quota.mjs`。
- 文档：`docs/guides/DATA-AND-CONFIG.md`、`docs/PITFALLS.md` #128。
