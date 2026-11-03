/**
 * 诊断：QQ 到底认哪种「B站视频卡片」。
 *
 * 背景（2026-10-23）：群里发 `com.tencent.structmsg` 新闻卡，QQ 显示
 * 「发送者版本过低，无法展示内容」；而旧的 `get_mini_app_ark` 小程序卡能显示
 * （只是点开提示「小程序已下架」）。需要确认是 ver 太低、字段太多，还是
 * SnowLuma 这个发送端根本不能发 structmsg。
 *
 * 用法：node scripts/probe-bili-card-formats.mjs [BV号] --go
 *   · 只发**私聊给 ownerQQ**，不碰群；
 *   · 一次发 4 条，标题带 [测试N]，方便肉眼判断哪条能正常显示；
 *   · 不带 --go 只打印将要发送的 JSON，不发送。
 *
 * 属于探针脚本：默认不跑。
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fetchVideoInfo } from '../src/bili-api.js';
import { buildBiliCardArk } from '../src/bili-card.js';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const args = process.argv.slice(2);
const go = args.includes('--go');
const bv = args.find((a) => !a.startsWith('--')) || 'BV14Gpj6UESm';
const token = cfg.snowluma?.accessToken || '';
const httpUrl = String(cfg.snowluma?.httpUrl || 'http://127.0.0.1:3000').replace(/\/+$/, '');
const uid = Number(cfg.ownerQQ || 0);
if (!uid) {
  console.error('config.json 里没有 ownerQQ，无法决定私聊对象');
  process.exit(1);
}

const info = await fetchVideoInfo(bv);
if (!info.ok) {
  console.log('视频信息获取失败：', info.why);
  process.exit(1);
}
const jumpUrl = `https://www.bilibili.com/video/${bv}`;
const pic = String(info.pic || '').replace(/^http:\/\//i, 'https://');
const base = buildBiliCardArk({ bvid: bv, title: info.title, desc: info.desc || info.title, pic, jumpUrl });

// 1) SnowLuma 原生 share 段：最极简的 structmsg（没有 ver / config / extra）
const shareSegment = { type: 'share', data: { url: jumpUrl, title: `[测试1] ${info.title}`, content: '极简 share 段', image: pic } };

// 2) structmsg + 高 ver（对齐小程序 ARK 的 1.0.0.19）+ 带 token 的 config
const highVer = {
  ...base,
  ver: '1.0.0.19',
  config: { autosize: true, ctime: Math.floor(Date.now() / 1000), forward: true, token: crypto.randomBytes(16).toString('hex'), type: 'normal' },
  prompt: `[测试2] ${info.title}`,
  meta: { news: { ...base.meta.news, title: `[测试2] ${info.title}` } },
  extra: { ...base.extra, title: `[测试2] ${info.title}` },
};

// 3) structmsg 但不带 ver（看是不是 ver 触发了版本门）
const noVer = JSON.parse(JSON.stringify(base));
delete noVer.ver;
noVer.prompt = `[测试3] ${info.title}`;
noVer.meta.news.title = `[测试3] ${info.title}`;
noVer.extra.title = `[测试3] ${info.title}`;

// 4) 控制组：纯文本链接
const text = { type: 'text', data: { text: `[测试4 纯文本] ${info.title}\n${jumpUrl}` } };

const variants = [
  ['1 share 极简', [shareSegment]],
  ['2 structmsg 高ver', [{ type: 'json', data: { data: highVer } }]],
  ['3 structmsg 无ver', [{ type: 'json', data: { data: noVer } }]],
  ['4 纯文本链接', [text]],
];

console.log('视频：', info.title);
console.log('目标：私聊', uid);
for (const [name, message] of variants) {
  console.log(`\n--- ${name} ---`);
  console.log(JSON.stringify(message).slice(0, 600));
  if (!go) continue;
  const res = await fetch(`${httpUrl}/send_private_msg`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ user_id: uid, message }),
    signal: AbortSignal.timeout(20000),
  });
  const body = await res.json().catch(() => ({}));
  console.log('send:', body.status, body.retcode, JSON.stringify(body.data ?? {}).slice(0, 120));
  await new Promise((r) => setTimeout(r, 1200));
}
if (!go) console.log('\n（未发送；加 --go 才会真的发私聊）');
else console.log('\n已发 4 条私聊，看一下哪条能正常显示，把编号告诉管理员。');
