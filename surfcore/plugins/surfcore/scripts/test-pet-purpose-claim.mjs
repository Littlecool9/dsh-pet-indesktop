/**
 * 共享「主动说话额度」/proactive/claim 的行为回归（纯本地文件，不连 DSH / QQ）。
 *
 * 规则顺序：专注 → 安静时段 → 今日上限 → 最小间隔 → 放行。
 * 重点钉住三件事：
 *   1. 每次判定都从磁盘重读（桥接/插件是两个进程写同一份文件）；
 *   2. 放行会 +1、写 lastSentAt/lastClaim，并把 nextFireAt 推到 now+gap 之后；
 *   3. 跨天会先归零再判定。
 *
 * 运行：node plugins/surfcore/scripts/test-pet-purpose-claim.mjs
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pet-purpose-claim-'));
const qqRoot = path.join(tmp, 'qq');
const dshHome = path.join(tmp, 'dsh');
const stateFile = path.join(dshHome, 'surfcore', 'characters', 'demo', 'purpose-outreach.json');
fs.mkdirSync(path.join(qqRoot, 'src'), { recursive: true });
fs.mkdirSync(path.dirname(stateFile), { recursive: true });
fs.writeFileSync(path.join(qqRoot, 'src', 'bridge.js'), '// probe only\n');
// QQBOT_ROOT 的探针要求 config.json + src/bridge.js 同时存在；必须在 import 前就位。
fs.writeFileSync(path.join(qqRoot, 'config.json'), JSON.stringify({ purpose: { enabled: true } }));

// paths.js 在 import 时解析 QQBOT_ROOT / DSH_HOME，所以必须先设环境再动态 import。
process.env.SURFCORE_ROOT = qqRoot;
process.env.DSH_HOME = dshHome;

let focusOn = false;
const chat = {
  purposeStateFile: () => stateFile,
  focusEnabled: () => focusOn,
  readFocus: () => ({ enabled: focusOn, phase: 'work', endsAt: focusOn ? Date.now() + 60 * 60 * 1000 : 0 }),
};

const { createPetPurposeService } = await import('../lib/pet-purpose.js');

function pad(n) { return String(n).padStart(2, '0'); }
function dayKey(at = Date.now()) {
  const d = new Date(at);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function clockMinute(offsetMinutes) {
  const d = new Date(Date.now() + offsetMinutes * 60 * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function writeQqPurpose(purpose) {
  fs.writeFileSync(path.join(qqRoot, 'config.json'), JSON.stringify({ purpose }, null, 2));
}
function writeState(extra = {}) {
  fs.writeFileSync(stateFile, JSON.stringify({
    version: 1,
    day: dayKey(),
    countToday: 0,
    lastSentAt: 0,
    nextFireAt: 0,
    ...extra,
  }, null, 2));
}
function readState() {
  return JSON.parse(fs.readFileSync(stateFile, 'utf8'));
}

const GAP = 5 * 60 * 1000;
const basePurpose = {
  enabled: true,
  dailyMax: 2,
  gapMinMs: GAP,
  quietStart: '00:00',
  quietEnd: '00:00', // start === end → 不启用安静时段
};

const service = createPetPurposeService({ chat, pluginLog: () => {} });

try {
  // ── 1. 放行：+1、记录 source、nextFireAt 至少 now+gap ───────────────────
  {
    writeQqPurpose(basePurpose);
    writeState({ countToday: 1, lastSentAt: 0, nextFireAt: 0 });
    const before = Date.now();
    const result = service.claim({ source: 'vision' });
    assert.equal(result.ok, true);
    assert.equal(result.granted, true, '额度没用完且不在间隔内 → 放行');
    assert.equal(result.remainingToday, 0, 'dailyMax=2、这次用掉第 2 次 → 今天还剩 0');
    assert.ok(result.nextAllowedAt >= before + GAP - 1000, 'nextAllowedAt ≈ now + gapMinMs');
    const disk = readState();
    assert.equal(disk.countToday, 2, '放行后磁盘 countToday +1');
    assert.ok(disk.lastSentAt >= before, '放行后磁盘 lastSentAt = now');
    assert.equal(disk.lastClaim?.source, 'vision', '记录 lastClaim.source');
    assert.ok(disk.lastClaim?.at >= before, '记录 lastClaim.at');
    assert.ok(disk.nextFireAt >= disk.lastSentAt + GAP, 'nextFireAt 不早于 lastSentAt + gap');
  }

  // ── 2. 专注：最先判定，磁盘状态不动 ────────────────────────────────────
  {
    writeQqPurpose(basePurpose);
    writeState({ countToday: 0, lastSentAt: 0 });
    focusOn = true;
    const result = service.claim('vision');
    assert.equal(result.granted, false);
    assert.equal(result.reason, 'focus', '专注模式优先于其它规则');
    assert.ok(result.retryAt > Date.now(), '专注带结束时间时 retryAt 指向结束');
    assert.ok(result.hint);
    assert.equal(readState().countToday, 0, '专注拒绝不占额度');
    focusOn = false;
  }

  // ── 3. 安静时段：retryAt = 安静结束 ────────────────────────────────────
  {
    writeQqPurpose({
      ...basePurpose,
      quietStart: clockMinute(-15),
      quietEnd: clockMinute(15),
    });
    writeState({ countToday: 0, lastSentAt: 0 });
    const result = service.claim({ source: 'vision' });
    assert.equal(result.granted, false);
    assert.equal(result.reason, 'quiet');
    assert.ok(result.retryAt > Date.now(), 'retryAt 必须是之后的安静结束时刻');
    assert.equal(readState().countToday, 0);
  }

  // ── 4. 今日上限：retryAt = 下一天起点 ──────────────────────────────────
  {
    writeQqPurpose(basePurpose);
    writeState({ countToday: 2, lastSentAt: 0 });
    const result = service.claim({ source: 'self-talk' });
    assert.equal(result.granted, false);
    assert.equal(result.reason, 'daily');
    assert.ok(result.retryAt > Date.now(), 'retryAt 是明天起点');
    assert.equal(readState().countToday, 2, '拒绝不写盘');
  }

  // ── 5. 最小间隔：retryAt = lastSentAt + gapMinMs ────────────────────────
  {
    writeQqPurpose(basePurpose);
    const lastSentAt = Date.now() - 60 * 1000;
    writeState({ countToday: 0, lastSentAt });
    const result = service.claim({ source: 'vision' });
    assert.equal(result.granted, false);
    assert.equal(result.reason, 'gap');
    assert.equal(result.retryAt, lastSentAt + GAP, 'retryAt 精确等于上次 + gap');
  }

  // ── 6. 跨天：先归零再判定 ──────────────────────────────────────────────
  {
    writeQqPurpose(basePurpose);
    writeState({
      day: '2020-01-01',
      countToday: 9,
      lastSentAt: Date.now() - GAP - 60 * 1000,
    });
    const result = service.claim({ source: 'vision' });
    assert.equal(result.granted, true, '旧日期的 countToday 不能压住今天');
    const disk = readState();
    assert.equal(disk.day, dayKey(), '跨天后 day 改成今天');
    assert.equal(disk.countToday, 1, '跨天后从 0 重新计数');
  }

  // ── 7. 每次从磁盘重读：外部写入的次数必须立刻生效 ───────────────────────
  {
    writeQqPurpose(basePurpose);
    writeState({ countToday: 0, lastSentAt: 0 });
    assert.equal(service.claim({ source: 'vision' }).granted, true, '第一次放行（内存缓存 count=1）');
    // 模拟桥接进程/另一次 claim 直接把磁盘改成用满；内存缓存仍是 1。
    writeState({ countToday: 2, lastSentAt: 0 });
    const result = service.claim({ source: 'vision' });
    assert.equal(result.granted, false);
    assert.equal(result.reason, 'daily', '不能用 stale cache 再放行一次');
    assert.equal(readState().countToday, 2);
  }

  // ── 8. nextFireAt 只会被推后，不会被提前 ────────────────────────────────
  {
    writeQqPurpose(basePurpose);
    const earlyFireAt = Date.now() - 60 * 1000;
    writeState({ countToday: 0, lastSentAt: 0, nextFireAt: earlyFireAt });
    assert.equal(service.claim({ source: 'vision' }).granted, true);
    const disk = readState();
    assert.ok(disk.nextFireAt >= disk.lastSentAt + GAP, '早于 now+gap 的 nextFireAt 被推后');
  }
  {
    writeQqPurpose(basePurpose);
    const farFuture = Date.now() + 10 * GAP;
    writeState({ countToday: 0, lastSentAt: 0, nextFireAt: farFuture });
    assert.equal(service.claim({ source: 'vision' }).granted, true);
    assert.equal(readState().nextFireAt, farFuture, '本来就更晚的 nextFireAt 保持不动');
  }

  // ── 9. 直接调用（绕过路由）时的 body 校验 ───────────────────────────────
  {
    const bad = service.claim({});
    assert.equal(bad.ok, false);
    assert.equal(bad.code, 'invalid-source');
    assert.ok(bad.error && bad.hint);
  }

  console.log('pet-purpose claim tests OK');
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
