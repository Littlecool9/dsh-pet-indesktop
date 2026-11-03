// 动态同步的离线模拟：把状态复制到临时目录，删掉一条 seen，验证它会当成“新动态”推出去。
// 不碰真实 state/，也不会往 QQ 群发消息。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createBiliDynamicsSync } from '../src/bili-dynamics.js';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const realState = path.join(ROOT, 'state');
const stateFile = path.join(realState, 'bili-dynamics-state.json');
const cacheFile = path.join(realState, 'bili-dynamics-cache.json');
assert.ok(fs.existsSync(stateFile), '缺少 state/bili-dynamics-state.json（先启动一次桥接建立基线）');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bili-dyn-test-'));
fs.copyFileSync(stateFile, path.join(tmp, 'bili-dynamics-state.json'));
if (fs.existsSync(cacheFile)) fs.copyFileSync(cacheFile, path.join(tmp, 'bili-dynamics-cache.json'));

const st = JSON.parse(fs.readFileSync(path.join(tmp, 'bili-dynamics-state.json'), 'utf8'));
const ids = Object.keys(st.seen ?? {});
assert.ok(ids.length > 0, '基线里没有 seen 动态');
const removed = ids[0];
delete st.seen[removed];
fs.writeFileSync(path.join(tmp, 'bili-dynamics-state.json'), JSON.stringify(st, null, 2) + '\n');

const captured = [];
const sync = createBiliDynamicsSync({
  stateDir: tmp,
  log: () => {},
  sendToQQ: async (key, text) => { captured.push({ key, text }); },
  groups: ['10001', '10002'],
  isReady: () => true,
});
const result = await sync.pollOnce();
assert.equal(result.ok, true, `pollOnce 失败：${result.why ?? ''}`);
assert.equal(result.fresh, 1, `应识别 1 条新动态，实际 ${result.fresh}`);
assert.equal(captured.length, 2, `应发 2 个群，实际 ${captured.length}`);
assert.ok(captured[0].text.includes('【B站动态】'), '动态消息缺少标题');
assert.ok(captured[0].text.includes('t.bilibili.com') || captured[0].text.includes('bilibili.com'), '动态消息缺少链接');
assert.ok(captured[0].key.startsWith('group:'), '发送 key 不是群会话');

const after = JSON.parse(fs.readFileSync(path.join(tmp, 'bili-dynamics-state.json'), 'utf8'));
assert.ok(after.seen[removed], '发送后没有把动态写回 seen');

fs.rmSync(tmp, { recursive: true, force: true });
console.log('✅ 动态同步逻辑测试通过');
console.log(`   模拟新动态：${removed}；已发 2 个群；消息预览：`);
console.log(captured[0].text.split('\n').slice(0, 3).join('\n'));
