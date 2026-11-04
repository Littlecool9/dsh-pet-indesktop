// 目的机制接线：真实 bridge.js 的配置/预览/投递/发送回执/回合回执（VM 夹具，不连真 QQ）。
import assert from 'node:assert/strict';
import { bridgeHarness } from './audit-bridge-harness.mjs';

let failures = 0;
async function test(name, run, options) {
  const h = await bridgeHarness(options);
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

function seedOwner(h) {
  h.appendSocialV2Message('private:123', '主人', '明天面试有点紧张', '明天面试有点紧张', false, true, 'm1');
  h.appendSocialV2Message('private:123', '主人', '你最近在忙什么', '你最近在忙什么', false, true, 'm2');
}

await test('配置默认开、owner 回退到 config.ownerQQ', async (h) => {
  assert.equal(h.cfg.purpose.enabled, true);
  assert.equal(h.cfg.purpose.ownerUin, '123');
  assert.ok(h.cfg.purpose.quietStart);
  assert.ok(h.cfg.purpose.quietEnd);
});

await test('只读预览：会读素材/拼提示词，但不建会话、不投递、不改状态', async (h) => {
  seedOwner(h);
  const before = JSON.stringify(h.purposeState);
  const r = await h.runPurpose({ preview: true });
  assert.equal(r.ok, true);
  assert.equal(r.preview, true);
  assert.ok(r.materials.length >= 2);
  assert.ok(r.prompt.includes('【主动找主人 · 目的回合】'));
  assert.ok(r.prompt.includes('qq_send_private_message'));
  assert.ok(r.prompt.includes('明天面试有点紧张'));
  assert.equal(h.calls.prompts.length, 0);
  assert.equal(h.calls.created.length, 0);
  assert.equal(JSON.stringify(h.purposeState), before);
});

await test('强制投递：落到 private:owner，状态先记 pending', async (h) => {
  seedOwner(h);
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, true);
  assert.equal(r.delivered, true);
  assert.equal(h.calls.prompts.length, 1);
  assert.equal(h.calls.prompts[0].sessionId, h.state.sessions['private:123']);
  assert.equal(h.purposeState.countToday, 1);
  assert.equal(h.purposeState.lastOutcome, 'pending');
  assert.equal(h.purposeState.nextFireAt, 0);
  assert.ok(r.selected?.text);
});

await test('回合回执：真发了 = sent；内部备忘的「待续」进 pending', async (h) => {
  seedOwner(h);
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, true);
  const sid = h.state.sessions['private:123'];
  h.notePurposeOutbound('private:123', ['主人，明天面试的事……']);
  h.notePurposeTurnEnded(sid, {
    reason: { kind: 'completed' },
    text: '【目的】关心一下面试\n【类型】关心\n【状态】待续\n【待续】面试结果出来再问一次',
  }, true);
  assert.equal(h.purposeState.lastOutcome, 'sent');
  assert.equal(h.purposeState.attempts, 0);
  assert.ok(h.purposeState.lastSentAt > 0);
  assert.ok(h.purposeState.nextFireAt > Date.now());
  assert.equal(h.purposeState.history.at(-1).outcome, 'sent');
  assert.equal(h.purposeState.pending.length, 1);
  assert.equal(h.purposeState.pending[0].text, '面试结果出来再问一次');
});

await test('回合回执：没发消息且正常结束 = silent，不重试', async (h) => {
  seedOwner(h);
  const r = await h.runPurpose({ force: true });
  const sid = h.state.sessions['private:123'];
  h.notePurposeTurnEnded(sid, { reason: { kind: 'completed' }, text: '【目的】无【状态】跳过' }, false);
  assert.equal(r.ok, true);
  assert.equal(h.purposeState.lastOutcome, 'silent');
  assert.equal(h.purposeState.attempts, 0);
  assert.ok(h.purposeState.nextFireAt > Date.now());
});

// 2026-11-04 现场：SnowLuma 没开时「立即试一次」显示投递成功，模型回合发 QQ 全部 fetch failed。
// 目的回合必须和普通唤醒一样过「发送通道门」：不建会话、不烧回合、不吃今日次数，并给出可行动的原因。
await test('SnowLuma 没连上：手动试一次也不投递，返回 code + hint', async (h) => {
  seedOwner(h);
  h.setSnowlumaHealth({ connected: false });
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'channel');
  assert.equal(r.code, 'SNOWLUMA_OFFLINE');
  assert.ok(r.error && r.error.includes('SnowLuma'), `error 应点名 SnowLuma：${r.error}`);
  assert.ok(r.hint && r.hint.length > 0, 'hint 不能为空');
  assert.equal(h.calls.prompts.length, 0, '通道断着不能投递模型回合');
  assert.equal(h.purposeState.countToday, 0, '没投递不吃今日次数');
});

await test('最近发送刚失败：手动试一次同样拦下（SEND_RECENTLY_FAILED）', async (h) => {
  seedOwner(h);
  h.setSnowlumaHealth({ connected: true, lastSendOkAt: 0, lastSendFailAt: Date.now(), lastSendError: 'fetch failed' });
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'SEND_RECENTLY_FAILED');
  assert.ok(r.hint);
  assert.equal(h.calls.prompts.length, 0);
});

await test('SnowLuma 没连上：自动 tick 跳过并排一个重试时间，不每分钟空转', async (h) => {
  seedOwner(h);
  h.makePurposeDue();
  h.setSnowlumaHealth({ connected: false });
  const r = await h.runPurpose({});
  assert.equal(r.ok, false);
  assert.equal(r.code, 'SNOWLUMA_OFFLINE', `应被通道门拦下：${JSON.stringify(r)}`);
  assert.equal(h.calls.prompts.length, 0);
  assert.ok(h.purposeState.nextFireAt > Date.now(), '应排下一次检查时间');
  // 正对照：通道恢复后同样的排程条件会真正出发（证明上面拦它的是通道门，不是别的排程判断）。
  h.setSnowlumaHealth({ connected: true, lastSendOkAt: Date.now(), lastSendFailAt: 0 });
  h.makePurposeDue();
  const ok = await h.runPurpose({});
  assert.equal(ok.ok, true, `通道恢复后应出发：${JSON.stringify(ok)}`);
  assert.equal(h.calls.prompts.length, 1);
}, { config: { purpose: { quietStart: '00:00', quietEnd: '00:00', idleThresholdMs: 0 } } });

const pad2 = (n) => String(n).padStart(2, '0');
const clockOf = (ms) => {
  const d = new Date(ms);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
await test('安静时段：非强制不投递；force 仍可手动试一次', async (h) => {
  seedOwner(h);
  h.purposeState.nextFireAt = 0;
  const quiet = await h.runPurpose({});
  assert.equal(quiet.ok, false);
  assert.equal(quiet.reason, 'quiet');
  assert.equal(h.calls.prompts.length, 0);
  const r = await h.runPurpose({ force: true });
  assert.equal(r.ok, true);
  assert.equal(h.calls.prompts.length, 1);
}, {
  config: {
    purpose: {
      quietStart: clockOf(Date.now() - 60 * 60 * 1000),
      quietEnd: clockOf(Date.now() + 60 * 60 * 1000),
    },
  },
});

await test('启动预热：不投递，但把人格/记忆/群聊素材变成 goals 写进状态', async (h) => {
  seedOwner(h);
  h.appendSocialV2Message('group:456', '群友', '那个养鱼游戏怎么玩啊', '那个养鱼游戏怎么玩啊', false, false, 'm3');
  await h.warmPurposeState();
  assert.ok(h.purposeState.goals.length >= 1, '预热后应有目标假设');
  assert.ok(h.purposeState.drives.connect >= 0, '预热后驱动应落盘');
  assert.ok(h.purposeState.observations.length >= 1, '预热后观察账本应有条目');
  assert.ok(h.purposeState.lastCandidateCount >= 1, '预热后应能算出候选');
  assert.equal(h.calls.prompts.length, 0, '预热不能投递');
});

await test('关掉总开关：非强制不投递；模式不对也不投递', async (h) => {
  seedOwner(h);
  h.cfg.purpose.enabled = false;
  const r = await h.runPurpose({});
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'disabled');
  h.cfg.purpose.enabled = true;
  h.setMode('chat');
  const r2 = await h.runPurpose({});
  assert.equal(r2.ok, false);
  assert.equal(r2.reason, 'mode');
});

console.log(`\n${failures ? 'FAILED' : 'OK'}（purpose wiring）`);
process.exitCode = failures ? 1 : 0;
