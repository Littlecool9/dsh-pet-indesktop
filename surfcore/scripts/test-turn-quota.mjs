// 每次醒来最多发 N 条（maxOutboundPerTurn）的计数口径：真实 bridge.js + VM 夹具，不连真 QQ。
// 2026-11-04 现场：一个私聊回合里和主人来回 4 轮各 2 条，第 9 条被拦 —— 实时对话全挤在同一次醒来里。
// 新口径：回合进行中，对方「直接找她」的新消息（私聊消息/拍一拍、群里 @/叫名字）重新给一份名额；
// 群里普通闲聊不刷新（否则热闹群里名额永远用不完）；目的回合投递前也清零。
import assert from 'node:assert/strict';
import { bridgeHarness } from './audit-bridge-harness.mjs';

let failures = 0;
async function test(name, run) {
  // 夹具默认关掉 Token 防爆破；这里要测的就是它，显式打开。
  const h = await bridgeHarness({ config: { socialV2: { tokenGuard: { enabled: true, maxOutboundPerTurn: 8 } } } });
  try {
    h.setMode('reserved2');
    await run(h);
    console.log('PASS', name);
  } catch (error) {
    failures += 1;
    console.error('FAIL', name, error.message);
  } finally {
    await h.close();
  }
}

/** 建会话并标记「本回合正在跑」，计数打满。 */
async function busyAndExhausted(h, key) {
  await h.ensureSession(key);
  h.v2TurnStartAt.set(h.state.sessions[key], Date.now());
  const st = h.getSocialV2State(key);
  const max = h.cfg.socialV2.tokenGuard.maxOutboundPerTurn ?? 8;
  st.tokenTurnSent = max;
  assert.ok(h.tokenGuardSendBlock(key, st, 1), '前提：名额已用完，下一条应被拦');
  return st;
}

await test('私聊：回合进行中主人又发来一条，本回合名额重新计', async (h) => {
  const key = 'private:123';
  const st = await busyAndExhausted(h, key);
  h.scheduleWakeV2(key, 'private');
  assert.equal(h.tokenGuardSendBlock(key, st, 2), null, '主人的新消息之后应能再发');
  assert.equal(st.tokenTurnSent, 2);
});

await test('私聊：回合进行中被拍一拍，同样重新计', async (h) => {
  const key = 'private:123';
  const st = await busyAndExhausted(h, key);
  h.scheduleWakeV2(key, 'poke');
  assert.equal(h.tokenGuardSendBlock(key, st, 1), null);
});

await test('群聊：普通闲聊 / 关键词 / 拍一拍不刷新名额', async (h) => {
  const key = 'group:456';
  const st = await busyAndExhausted(h, key);
  for (const reason of ['anyMessage', 'keyword', 'question', 'poke']) h.scheduleWakeV2(key, reason);
  assert.ok(h.tokenGuardSendBlock(key, st, 1), '群里没人直接找她，仍按原名额拦');
});

await test('群聊：@ 她 / 叫她名字，重新计', async (h) => {
  const key = 'group:456';
  let st = await busyAndExhausted(h, key);
  h.scheduleWakeV2(key, 'atMention');
  assert.equal(h.tokenGuardSendBlock(key, st, 1), null, '@ 之后应能再发');
  st = await busyAndExhausted(h, key);
  h.scheduleWakeV2(key, 'nameMention');
  assert.equal(h.tokenGuardSendBlock(key, st, 1), null, '叫名字之后应能再发');
});

await test('目的回合：投递前清零，不继承上一回合用掉的名额', async (h) => {
  h.appendSocialV2Message('private:123', '主人', '明天面试有点紧张', '明天面试有点紧张', false, true, 'm1');
  h.appendSocialV2Message('private:123', '主人', '你最近在忙什么', '你最近在忙什么', false, true, 'm2');
  const st = h.getSocialV2State('private:123');
  st.tokenTurnSent = 8;
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(st.tokenTurnSent, 0, '目的回合应从 0 开始计');
});

console.log(`\n${failures ? 'FAILED' : 'OK'}（turn quota）`);
process.exitCode = failures ? 1 : 0;
