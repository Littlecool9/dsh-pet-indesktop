// QQ 鱼群触发记录整理（给设置页）的离线回归。
// 数据来自桥接写进 social-v2.json 的 fishGuardLog / fishGuard / lastFishGuard；
// 这里只测纯函数，不碰真实状态。
import assert from 'node:assert/strict';
import { summarizeQqFishGuard } from '../plugins/surfcore/lib/qq-fish-guard.js';
import { appendFishGuardTrigger } from '../src/fish-guard.js';

const now = new Date('2026-10-23T08:40:00+08:00').getTime();
const at = (iso) => new Date(iso).getTime();

// 空数据
{
  const r = summarizeQqFishGuard({}, { now });
  assert.deepEqual(r.items, []);
  assert.equal(r.active, 0);
  assert.equal(r.today, 0);
}

// 两个群：一个当前保护中 + 历史触发；一个只有 lastFishGuard
{
  const data = {
    conversations: {
      'group:111': {
        fishGuard: { at: at('2026-10-23T08:30:00+08:00'), until: now + 5 * 60000, reason: 'fish-count', fishCount: 5, fishMessages: 9, totalMessages: 12, fishRatio: 0.75 },
        fishGuardLog: [
          { at: at('2026-10-23T08:30:00+08:00'), groupId: '111', groupName: '摸鱼群', reason: 'fish-count', fishCount: 5, fishMessages: 9, totalMessages: 12, fishRatio: 0.75, until: now + 5 * 60000 },
          { at: at('2026-10-22T20:10:00+08:00'), groupId: '111', groupName: '摸鱼群', reason: 'fish-streak', fishCount: 2, fishMessages: 6, totalMessages: 8, fishRatio: 0.75, consecutiveFish: 6, until: at('2026-10-22T20:20:00+08:00') },
        ],
      },
      'group:222': {
        lastFishGuard: { at: at('2026-10-23T07:00:00+08:00'), until: at('2026-10-23T07:10:00+08:00'), reason: 'fish-ratio', fishCount: 3, fishMessages: 8, totalMessages: 10, fishRatio: 0.8 },
      },
      'private:333': { fishGuardLog: [{ at: at('2026-10-23T06:00:00+08:00'), reason: 'fish-count' }] },
    },
  };
  const r = summarizeQqFishGuard(data, { now });
  assert.equal(r.items.length, 3, JSON.stringify(r.items));
  // 当前冷却与日志里的同一次触发去重，且 active 优先
  const current = r.items.find((x) => x.groupId === '111' && x.reason === 'fish-count');
  assert.equal(current.active, true);
  assert.equal(current.groupName, '摸鱼群');
  assert.equal(r.active, 1);
  // 按时间倒序：08:30 当前 > 07:00 last > 昨天 20:10
  assert.equal(r.items[0].groupId, '111');
  assert.equal(r.items[1].groupId, '222');
  assert.equal(r.items[2].groupName, '摸鱼群');
  assert.equal(r.items[2].ended, false);
  // today 只算今天（08:30 + 07:00），昨天那条不算
  assert.equal(r.today, 2);
}

// 当前冷却已过期 → active=false，但仍然显示
{
  const data = {
    conversations: {
      'group:999': { fishGuard: { at: at('2026-10-23T07:00:00+08:00'), until: at('2026-10-23T07:10:00+08:00'), reason: 'fish-count', fishCount: 3 } },
    },
  };
  const r = summarizeQqFishGuard(data, { now });
  assert.equal(r.items.length, 1);
  assert.equal(r.items[0].active, false);
  assert.equal(r.active, 0);
}

// 桥接写入：appendFishGuardTrigger 只在新一轮触发时调用，每群最多 30 条
{
  const state = {};
  for (let i = 0; i < 35; i += 1) {
    appendFishGuardTrigger(state, {
      key: 'group:777',
      groupName: '鱼群测试',
      until: now + 600000,
      now: now + i * 1000,
      assessment: { reason: 'fish-count', fishCount: 5 + i, fishMessages: 9, totalMessages: 12, fishRatio: 0.75, consecutiveFish: 3 },
    });
  }
  assert.equal(state.fishGuardLog.length, 30, '每群最多 30 条');
  assert.equal(state.fishGuardLog[0].fishCount, 10, '最早的 5 条应被裁掉');
  assert.equal(state.fishGuardLog.at(-1).groupId, '777');
  assert.equal(state.fishGuardLog.at(-1).groupName, '鱼群测试');
  const r = summarizeQqFishGuard({ conversations: { 'group:777': state } }, { now });
  assert.equal(r.items.length, 30);
  assert.equal(r.items[0].groupName, '鱼群测试');
}

console.log('qq fish guard summary tests OK');
