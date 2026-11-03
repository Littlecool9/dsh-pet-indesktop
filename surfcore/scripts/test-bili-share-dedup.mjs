// 分享去重回归（2026-10-26 修）：
//   以前"新鲜池空了"会回退到整个池子，同一支最高分视频会被一天天反复发。
//   现在必须：没新鲜素材就不发；只有 allowReuse 才允许复用。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createBiliMemory } from '../src/bili-memory.js';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bili-share-dedup-'));
const stateDir = path.join(dir, 'state');
fs.mkdirSync(stateDir, { recursive: true });

const today = new Date().toISOString().slice(0, 10);
const entries = Array.from({ length: 10 }, (_, i) => ({
  id: `bv:BVTEST${i}`,
  bvid: `BVTEST${i}`,
  title: `测试视频 ${i}`,
  text: `这是第 ${i} 条测试见闻，长度足够触发分享条件。`,
  date: today,
  score: 20 - i,
  priority: 5,
  shareable: true,
  type: 'video',
}));
fs.writeFileSync(path.join(stateDir, 'bili-memory.json'), JSON.stringify({ entries }));

const memory = createBiliMemory({ stateDir, home: dir, log: () => {} });

// 1) 连发 8 档：应该是 8 条不同素材
const picks = [];
for (let slot = 0; slot < 8; slot += 1) {
  const card = memory.pickShareCard({ slotIndex: slot, dateKey: today });
  assert.ok(card, `第 ${slot} 档不该为空`);
  picks.push(card.id);
  memory.recordShare(card.id, `${today} ${slot}`);
}
assert.equal(new Set(picks).size, 8, `8 档应有 8 条不同素材，实际 ${new Set(picks).size}`);

// 2) 把剩下两条也记成"刚发过" → 池子里全是旧素材
for (const e of entries) memory.recordShare(e.id, `${today} extra`);
assert.equal(
  memory.pickShareCard({ slotIndex: 0, dateKey: today }), null,
  '全都发过时必须返回 null（不能回退到旧素材）',
);

// 3) 显式 allowReuse 才允许复用
const reused = memory.pickShareCard({ slotIndex: 0, dateKey: today, allowReuse: true });
assert.ok(reused && reused.id, 'allowReuse=true 时应能复用');

// 4) 历史过期后（把 used 改成 30 天前）应重新可选
const histFile = path.join(stateDir, 'bili-share-history.json');
const hist = JSON.parse(fs.readFileSync(histFile, 'utf8'));
const old = new Date(Date.now() - 30 * 86400000).toISOString();
for (const k of Object.keys(hist.used)) hist.used[k] = old;
fs.writeFileSync(histFile, JSON.stringify(hist));
assert.ok(memory.pickShareCard({ slotIndex: 0, dateKey: today }), '冷却期过后应能正常再发');

fs.rmSync(dir, { recursive: true, force: true });
console.log('✅ 分享去重回归通过');
