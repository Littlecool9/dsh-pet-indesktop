// 观看历史的「操作」：评论分类 / 挂到哪一次观看 / 收藏 / 动态 / 汇总。
// 不联网、不碰真实 ~/.dsh 状态（临时文件）。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  attachWatchActions, classifyComment, enrichWatchHistory, readWatchActions, summarizeWatchActions,
} from '../plugins/surfcore/tools/lib/watch-actions.mjs';

const at = (iso) => new Date(iso).toISOString();
const comment = (over = {}) => ({
  type: 'comment', at: at('2026-10-23T04:00:00+08:00'), target: 'BV:BV1jen464E32',
  note: '看完 wo 有点想笑 mer', auto: true, ...over,
});

// ── 评论分类：主评论 / 鱼群聚拢 / 回复 / 搭话 / 动态回复 / 分享 ────────────
{
  assert.equal(classifyComment(comment()).kind, 'main');
  assert.equal(classifyComment(comment({ parent: '321' })).kind, 'gather', '有 parent 但没有 reply = 鱼群聚拢');
  assert.equal(classifyComment(comment({ parent: '321', reply: true })).kind, 'reply');
  assert.equal(classifyComment(comment({ parent: '321', reply: true, ta: true })).kind, 'ta');
  assert.equal(classifyComment(comment({ parent: '321', mine: true })).kind, 'mine');
  assert.equal(classifyComment(comment({ share: true })).kind, 'share');
  assert.equal(classifyComment(comment({ type: 'like' })), null);
  assert.equal(classifyComment(comment({ at: 'not-a-date' })), null);
  assert.equal(classifyComment(comment({ target: 'oid:123' })), null, '没有 BV 的评论无法挂到观看历史');
  assert.match(classifyComment(comment({ parent: '321' })).label, /鱼群保护/);
}

// ── 读动作：quota + 收藏 + 动态，去重、按时间升序 ─────────────────────────
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'surfcore-actions-'));
const quotaFile = path.join(dir, 'quota.json');
const favoritesFile = path.join(dir, 'favorites.json');
const memoryFile = path.join(dir, 'bili-memory.json');
try {
  fs.writeFileSync(quotaFile, JSON.stringify({ log: [
    comment({ at: at('2026-10-23T04:00:00+08:00'), note: '主评论内容' }),
    comment({ at: at('2026-10-23T04:05:00+08:00'), parent: '321', note: '聚拢内容' }),
    comment({ at: at('2026-10-23T04:10:00+08:00'), parent: '322', reply: true, note: '回复内容' }),
    comment({ at: at('2026-10-23T04:15:00+08:00'), parent: '323', reply: true, ta: true, note: '搭话内容' }),
    { type: 'like', at: at('2026-10-23T04:20:00+08:00'), target: 'BV:BV1jen464E32' },
  ] }));
  fs.writeFileSync(favoritesFile, JSON.stringify({ items: [
    { bv: 'BV1jen464E32', at: at('2026-10-23T04:30:00+08:00'), reason: '值得回看' },
  ] }));
  fs.writeFileSync(memoryFile, JSON.stringify({ entries: [
    { type: 'dynamic', at: at('2026-10-23T04:40:00+08:00'), title: '发了一条动态', text: '推荐 https://www.bilibili.com/video/BV1jen464E32/' },
    { type: 'video', at: at('2026-10-23T04:41:00+08:00'), title: '不是动态，不该产生动作' },
  ] }));

  const actions = readWatchActions({ quotaFile, favoritesFile, memoryFile });
  assert.equal(actions.length, 6, `应有 5 条评论动作（like 不算）+ 收藏 + 动态，实际 ${actions.length}`);
  assert.deepEqual(actions.map((a) => a.kind), ['main', 'gather', 'reply', 'ta', 'favorite', 'dynamic']);
  assert.equal(actions.every((a) => a.bvid === 'BV1jen464E32'), true);

  const items = [
    { at: at('2026-10-23T03:00:00+08:00'), bvid: 'BV1jen464E32', title: '第一条观看' },
    { at: at('2026-10-23T05:00:00+08:00'), bvid: 'BV1jen464E32', title: '第二条观看' },
    { at: at('2026-10-23T05:10:00+08:00'), bvid: 'BV1zzzzzzzzz', title: '只看过' },
    { at: at('2026-10-23T05:20:00+08:00'), bvid: 'BV1noactions', title: '另一个只看过' },
  ];
  attachWatchActions(items, actions);
  // 04:00~04:15 的动作应挂到 03:00 那次观看；收藏/动态（04:30/04:40）也挂 03:00（05:00 还没到）
  assert.equal(items[0].actions.length, 6, '第一次观看应挂 6 个动作');
  assert.equal(items[1].actions.length, 0, '第二次观看没有动作');
  assert.equal(items[2].actions.length, 0, '没动作的视频是空数组');
  assert.ok(items.every((item) => Array.isArray(item.actions)));

  // 动作早于所有观看：挂到最早那条并标 beforeFirstWatch
  const early = [{ at: at('2026-10-23T03:00:00+08:00'), bvid: 'BV1jen464E32' }];
  attachWatchActions(early, [{ ...actions[0], at: at('2026-10-22T03:00:00+08:00') }]);
  assert.equal(early[0].actions.length, 1);
  assert.equal(early[0].actions[0].beforeFirstWatch, true);

  // 汇总
  const summary = summarizeWatchActions(items);
  assert.equal(summary.comments, 4, '主/聚拢/回复/搭话各 1 条');
  assert.equal(summary.main, 1);
  assert.equal(summary.gather, 1);
  assert.equal(summary.reply, 1);
  assert.equal(summary.ta, 1);
  assert.equal(summary.favorite, 1);
  assert.equal(summary.dynamic, 1);
  assert.equal(summary.watchedOnly, 3, '三条观看记录没有动作');
  assert.equal(summary.items, 4);

  // 一步到位
  const enriched = enrichWatchHistory([
    { at: at('2026-10-23T03:00:00+08:00'), bvid: 'BV1jen464E32' },
  ], { quotaFile, favoritesFile, memoryFile });
  assert.equal(enriched.items[0].actions.length, 6);
  assert.equal(enriched.actions.total, 6);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.log('OK test-watch-actions');
