# 2026-11-04 目的「立即试一次」假报已投递：目的回合绕过了 QQ 发送通道门

## 现象
设置 → SurfCore → 目的 →「立即试一次（真发）」显示「✓ 已投递：…（等她说）」，QQ 私聊没收到任何消息。

## 定位（只读）
- `~/.dsh/surfcore/gate-events.jsonl`：对 `private:<管理员>` 连续 `gate=snowluma event=send-failed reason=fetch failed`，
  随后 `wake-suspended-after-send-failures`（连续 3 次失败，暂停自动唤醒 30 分钟）；更早一轮是 `OneBot send_private_msg 失败: unauthorized`。
- `surfcore/state/bridge.log`：每次点击都是 `[目的] 已投递…` → `QQ 发送失败 … fetch failed` → `[目的] 回合结束：silent`，
  模型内部输出写着「桥接连不上（fetch failed），消息没发出去」；全程每 15 秒 `SnowLuma 连接断开（code=1006）`。
- `netstat`：127.0.0.1:3000（OneBot HTTP）/3001（WS）都没有监听 —— SnowLuma 没在跑。

## 完整逻辑
1. **链路**：设置页 `client.js doRun` → 插件 `index.js /purpose/run`（载体 QQ 时只检查桥接进程在不在）→ 桥接 `/api/purpose/run`
   → `runPurposeOnce` → `deliverPrompt` 投进 DSH 模型会话 → 模型回合里调 `qq_send_private_message` → 桥接 → SnowLuma OneBot HTTP。
   其它读者：桌宠离线回落 `pet-purpose.js fallbackToQQ`、`/action purpose-run`，都原样透传桥接结果。
2. **机制**：接口的 `ok:true` 只说明「回合投进去了」，发送在回合里异步发生。普通唤醒 `sendWakePromptV2` 在建会话前过
   `qqSendChannelStatus()`；目的回合是后来加的另一条出口，没过这道门。
3. **爆炸半径**：1 进程（桥接）× 3 个调用方（手动、自动 tick、桌宠回落）× 静默（3）。每次点击白花一次模型回合的 token；不碰密钥与用户数据。
4. **取舍**：
   - A（选）：桥接 `runPurposeOnce` 复用 `qqSendChannelStatus()`。一处覆盖三个调用方，和普通唤醒同口径，回滚就是删一个 if。
   - B：只在设置页前置查 `/bridge` 的 `snowluma.connected`（B 站分享按钮的做法）。只修手动按钮，自动 tick/回落照样空烧，弃。
   - C：等回合回执再告诉设置页是否真发出。能覆盖「门放行后才掉线」，但要加轮询/事件，改动大；记为残余。
5. **生效与重启**：改 `src/bridge.js` 需重启 QQ 桥接（设置页「保存并重启 QQ 桥接」或 `stop-qq-bot` + 启动）；
   `client.js` 是设置页前端，重开设置页即可（插件重载后生效）。
6. **验证**：
   ```text
   node scripts/test-purpose-wiring.mjs        # 11 PASS；新 3 条在修复前红
   npm run test:regressions                    # 全部通过
   node scripts/test-snowluma-channel-gate.mjs
   node plugins/surfcore/scripts/test-client-contract.mjs
   node plugins/surfcore/scripts/test-pet-api.mjs
   npm run test:audit                          # 135/142；失败的 fish-guard / watch-history / night-schedule /
                                               # token-guard / token-budget 在未改动代码上同样失败（既有），
                                               # stickers / release-manifest 是工作树缺未跟踪 config.json / git 布局
   ```
   真机：SnowLuma 关着时点「立即试一次」→ 红字「SnowLuma 没连上：这次没让她出发… — 先启动 SnowLuma…」，日志 `[目的] 手动试一次被拦下`；
   启动 SnowLuma、概览页显示已连接后再点 → QQ 收到消息。
7. **回滚与残余**：`git revert` 本提交。残余：门放行后 SnowLuma 才掉线时，回合结局仍记 `silent`、设置页不回显（见 C）。

## 修法
- `src/bridge.js`：`runPurposeOnce` 在 token 额度检查之前过 `qqSendChannelStatus()`；新增 `purposeChannelBlocked()`
  产出 `{ ok:false, reason:'channel', code, error, hint }`；非 force 记 skip 并按 `retryMs` 排下一次（日志 10 分钟节流）。
- `plugins/surfcore/lib/client.js`：`doRun` 失败文案带 code + hint，并弹 toast。
- `scripts/audit-bridge-harness.mjs`：加 `makePurposeDue()`（内存 + 磁盘一起清 `nextFireAt`）。
- 文档：`docs/guides/PURPOSE_OUTREACH.md` §5、`plugins/surfcore/docs/PET.md` 排障表、`docs/PITFALLS.md` #127。
