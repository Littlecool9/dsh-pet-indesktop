// B站「观看历史」离线回归：追加 / 去重 / 轮转 / 旧记忆回填 / 评分合并 / 查询。
// 不联网、不碰真实 ~/.dsh 状态（全部用临时目录）。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { appendWatch, readWatchHistory } from '../plugins/surfcore/tools/lib/watch-history.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'surfcore-watch-'));
const file = path.join(dir, 'watch-history.jsonl');
const memoryFile = path.join(dir, 'bili-memory.json');
const scoresFile = path.join(dir, 'scores.json');
const at = (iso) => new Date(iso).toISOString();

try {
  // ── 追加 + 读回 ─────────────────────────────────────────────────────────
  const r1 = appendWatch({
    at: at('2026-10-23T06:00:00+08:00'),
    bvid: 'BV1KXpN6QEJm',
    aid: '123',
    title: '杀戮尖塔2 蓝色大肥鱼替换鸡煲皮肤',
    up: '某个UP',
    duration: 321,
    mode: 'meta',
    source: 'debrief',
  }, { file });
  assert.equal(r1.ok, true, JSON.stringify(r1));
  assert.equal(r1.item.bvid, 'BV1KXpN6QEJm');

  // 同一条视频、同一种读法、30 分钟内 → 只留一条
  const dup = appendWatch({
    at: at('2026-10-23T06:05:00+08:00'),
    bvid: 'BV1KXpN6QEJm',
    title: '重复调用',
    mode: 'meta',
  }, { file });
  assert.equal(dup.ok, false);
  assert.equal(dup.reason, 'duplicate');

  // 同一条视频、换成深看 → 允许记（浅看→深看是一次升级）
  const full = appendWatch({
    at: at('2026-10-23T06:10:00+08:00'),
    bvid: 'BV1KXpN6QEJm',
    title: '杀戮尖塔2 蓝色大肥鱼替换鸡煲皮肤',
    up: '某个UP',
    duration: 321,
    mode: 'full',
    frames: true,
    sheet: 'C:/tmp/sheet.jpg',
    source: 'debrief',
  }, { file });
  assert.equal(full.ok, true, JSON.stringify(full));

  // 非法 BV 不写，但标题还在时允许（用于旧数据/异形投稿）
  const bad = appendWatch({ at: at('2026-10-23T06:20:00+08:00'), bvid: 'not-a-bv', title: '异形投稿', mode: 'meta' }, { file });
  assert.equal(bad.ok, true);
  assert.equal(bad.item.bvid, '');

  // ── 旧记忆回填 + 评分合并 ──────────────────────────────────────────────
  fs.writeFileSync(memoryFile, JSON.stringify({
    entries: [
      { type: 'video', bvid: 'BV1JaJo6jEqH', title: '偷看DeepSeek娘的深度思考', at: at('2026-10-22T06:01:45+08:00'), score: 16, reason: '动情' },
      // 已经在 JSONL 里的不应重复回填
      { type: 'video', bvid: 'BV1KXpN6QEJm', title: '旧记忆里的同名视频', at: at('2026-10-21T06:00:00+08:00') },
      // 2026-10-23 回归：at 是空字符串时不能回落到 Date.now()（否则每次刷新都像刚看过）
      { type: 'video', bvid: 'BV1DateOnly6', title: '只有日期的旧记忆', at: '', date: '2026-10-20' },
      { type: 'video', bvid: 'BV1NoDate666', title: '连日期都没有的旧记忆', at: '' },
    ],
  }), 'utf8');
  fs.writeFileSync(scoresFile, JSON.stringify({
    '2026-10-23': [{ bv: 'BV1KXpN6QEJm', score: 15, reason: '自己做 mod' }],
  }), 'utf8');

  const read = readWatchHistory({ file, memoryFile, scoresFile, now: new Date('2026-10-23T12:00:00+08:00').getTime() });
  assert.equal(read.ok, undefined, 'readWatchHistory 不需要 ok 字段');
  assert.equal(read.items.some((x) => x.bvid === 'BV1JaJo6jEqH'), true, '旧记忆应回填');
  assert.equal(read.items.filter((x) => x.bvid === 'BV1KXpN6QEJm').length, 1, '同一视频只出现一次');
  assert.equal(read.items.find((x) => x.bvid === 'BV1KXpN6QEJm').score, 15, '评分应合并且以详细记录为主');
  assert.equal(read.stats.backfilled >= 1, true);
  assert.equal(read.stats.today >= 1, true);
  assert.equal(read.stats.deep >= 1, true);
  // 空 at + 有 date：按 date 回填并标 dateOnly，不能变成“刚刚看过”
  const dateOnly = read.items.find((x) => x.bvid === 'BV1DateOnly6');
  assert.equal(dateOnly?.dateOnly, true);
  assert.equal(new Date(dateOnly.at).getFullYear(), 2026);
  assert.equal(new Date(dateOnly.at).getMonth(), 9, '10 月');
  assert.equal(new Date(dateOnly.at).getDate(), 20);
  // 连 date 都没有：1970 + unknownDate，页面显示“日期未知”，不计入今天
  const unknown = read.items.find((x) => x.bvid === 'BV1NoDate666');
  assert.equal(unknown?.unknownDate, true);
  assert.equal(unknown.at.startsWith('1970-'), true);
  assert.equal(read.stats.today >= 1, true, '今天计数来自真实 at，不应被无日期旧记忆污染');

  // 查询 / 天数 / 条数
  const q = readWatchHistory({ file, memoryFile, scoresFile, q: 'deepseek', now: Date.now() });
  assert.ok(q.items.every((x) => `${x.title} ${x.up} ${x.bvid}`.toLowerCase().includes('deepseek')));
  const limited = readWatchHistory({ file, memoryFile, scoresFile, limit: 1, now: Date.now() });
  assert.equal(limited.items.length, 1);
  assert.ok(limited.total >= 2);
  const recent = readWatchHistory({ file, memoryFile, scoresFile, days: 1, now: new Date('2026-10-23T12:00:00+08:00').getTime() });
  assert.equal(recent.items.every((x) => new Date(x.at).getTime() >= new Date('2026-10-22T12:00:00+08:00').getTime()), true);

  // ── 轮转：超过 2MB 时当前文件改名为 .1，读取仍能合并 ─────────────────────
  const big = path.join(dir, 'big.jsonl');
  // 前面塞满 2MB 无效行，最后一行放一条有效旧记录；轮转后 readTail 仍能读到它。
  fs.writeFileSync(big, `${'x'.repeat(2 * 1024 * 1024)}\n`);
  fs.appendFileSync(big, `${JSON.stringify({ at: at('2026-10-20T00:00:00+08:00'), bvid: 'BV1xx411c7mD', title: '旧的' })}\n`);
  const rotated = appendWatch({ at: at('2026-10-23T00:00:00+08:00'), bvid: 'BV1KXpN6QEJm', title: '新的' }, { file: big });
  assert.equal(rotated.ok, true, JSON.stringify(rotated));
  assert.equal(fs.existsSync(path.join(dir, 'big.1.jsonl')), true, '2MB 后应轮转');
  const merged = readWatchHistory({ file: big, memoryFile, scoresFile, now: Date.now() });
  assert.ok(merged.items.some((x) => x.bvid === 'BV1xx411c7mD'), '轮转文件里的旧记录仍要读得到');
  assert.ok(merged.items.some((x) => x.bvid === 'BV1KXpN6QEJm'));

  // ── 接线契约：debrief / bili-watch / 角色迁移都要带上它 ─────────────────
  const debrief = fs.readFileSync(path.join(root, 'plugins/surfcore/tools/commands/debrief.mjs'), 'utf8');
  assert.ok(debrief.includes('appendWatch'), 'debrief 没有写观看历史');
  assert.ok(debrief.includes('SURFCORE_WATCH_PARENT'), 'debrief 调 bili-watch 时没有传防重复标记');
  const watch = fs.readFileSync(path.join(root, 'plugins/surfcore/tools/commands/bili-watch.mjs'), 'utf8');
  assert.ok(watch.includes('appendWatch'), 'bili-watch 没有写观看历史');
  assert.ok(watch.includes('SURFCORE_WATCH_PARENT'), 'bili-watch 没有识别 debrief 的防重复标记');
  const persona = fs.readFileSync(path.join(root, 'src/character-persona.js'), 'utf8');
  assert.ok(persona.includes('watch-history.jsonl'), '角色迁移/快照没有带上观看历史');
  const client = fs.readFileSync(path.join(root, 'plugins/surfcore/lib/client.js'), 'utf8');
  assert.ok(client.includes('"/watch-history'), '设置页没有调用观看历史接口');
  assert.ok(client.includes('function WatchTab') || client.includes('const WatchTab'), '设置页没有观看历史页');

  console.log('watch history tests OK');
} finally {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch {}
}
