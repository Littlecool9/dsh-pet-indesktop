/**
 * B站 工具链路径隔离：有角色时行为账本进角色包，凭证/表情包仍走账号目录。
 * 全部在临时 DSH_HOME 里跑。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'surfcore-bili-paths-'));
process.env.DSH_HOME = temp;
process.env.USERPROFILE = temp;
fs.mkdirSync(path.join(temp, 'surfcore', 'bili'), { recursive: true });

const store = await import('../src/character-persona.js');
const paths = await import(`../plugins/surfcore/tools/lib/state-paths.mjs?x=${Date.now()}`);

assert.equal(paths.biliStateDir(), path.join(temp, 'surfcore', 'bili'), '没有角色时回退账号目录');
assert.equal(paths.biliState('quota.json'), path.join(temp, 'surfcore', 'bili', 'quota.json'));
assert.equal(paths.accountBili('credentials.json'), path.join(temp, 'surfcore', 'bili', 'credentials.json'));

const character = store.createCharacter({ name: '角色甲', personaText: '# 卡' });
store.switchCharacter(character.character.id);
// state-paths 有 mtime 缓存；写指针后重新 import 一个新实例模拟新进程。
const paths2 = await import(`../plugins/surfcore/tools/lib/state-paths.mjs?x=${Date.now() + 1}`);
assert.equal(paths2.biliStateDir(), path.join(temp, 'surfcore', 'characters', character.character.id, 'bili'));
assert.equal(paths2.biliState('quota.json'), path.join(temp, 'surfcore', 'characters', character.character.id, 'bili', 'quota.json'));
assert.equal(paths2.accountBili('credentials.json'), path.join(temp, 'surfcore', 'bili', 'credentials.json'), '凭证不能进角色包');

// 真跑一条工具链命令：quota status 必须读角色自己的账本，而不是旧目录。
const today = new Date().toLocaleDateString('sv-SE');
fs.writeFileSync(paths2.biliState('quota.json'), JSON.stringify({
  date: today,
  log: [{ at: new Date().toISOString(), type: 'comment', target: 'BVtest', auto: true }],
}));
const out = execFileSync(process.execPath, [path.join(import.meta.dirname, '..', 'plugins', 'surfcore', 'tools', 'bili.mjs'), 'quota', 'status'], {
  env: { ...process.env, DSH_HOME: temp, USERPROFILE: temp },
  encoding: 'utf8',
  timeout: 30_000,
});
assert.match(out, /共 1 条/, `工具没有读到角色账本：${out.slice(0, 300)}`);

try { fs.rmSync(temp, { recursive: true, force: true }); } catch {}
console.log('bili state paths tests OK');
