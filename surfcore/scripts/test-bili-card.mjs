// 测试：把一条 B 站视频做成 QQ 分享卡，私聊发给 owner（不碰群）。
// 用法：node scripts/test-bili-card.mjs [BV号] [--miniapp]
//
// 默认发「链接卡」（com.tencent.structmsg news）：B站小程序在 QQ 侧已下架，
// 旧的 get_mini_app_ark 卡片点开提示「小程序已下架」。
// --miniapp 只用于确认小程序是否恢复；恢复前别用。
//
// ⚠️ 这个脚本会真的发一条私聊消息给 ownerQQ，属于探针，默认不要跑。
import fs from 'node:fs';
import path from 'node:path';
import { fetchVideoInfo } from '../src/bili-api.js';
import { buildBiliCardArk } from '../src/bili-card.js';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const args = process.argv.slice(2);
const useMiniApp = args.includes('--miniapp');
const bv = args.find((a) => !a.startsWith('--')) || 'BV1JaJo6jEqH';
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
console.log('视频：', info.title);
console.log('封面：', info.pic);

const jumpUrl = `https://www.bilibili.com/video/${bv}`;
let arkData;
if (useMiniApp) {
  console.warn('⚠️ 小程序卡片：B站小程序已下架，点开大概率提示「小程序已下架」');
  const arkRes = await fetch(`${httpUrl}/get_mini_app_ark`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ type: 'bili', title: info.title, desc: info.desc || info.title, picUrl: info.pic, jumpUrl }),
    signal: AbortSignal.timeout(20000),
  });
  const ark = await arkRes.json().catch(() => ({}));
  console.log('ark status:', ark.status, ark.retcode, ark.data?.data?.app, ark.data?.data?.view);
  if (ark.status !== 'ok' || !ark.data?.data) {
    console.log('ark 返回：', JSON.stringify(ark).slice(0, 1000));
    process.exit(1);
  }
  arkData = ark.data.data;
} else {
  arkData = buildBiliCardArk({ bvid: bv, title: info.title, desc: info.desc || info.title, pic: info.pic, jumpUrl });
  console.log('卡片：com.tencent.structmsg / news（链接卡）');
}

const sendRes = await fetch(`${httpUrl}/send_private_msg`, {
  method: 'POST',
  headers: {
    'content-type': 'application/json',
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  },
  body: JSON.stringify({ user_id: uid, message: [{ type: 'json', data: { data: arkData } }] }),
  signal: AbortSignal.timeout(20000),
});
const sent = await sendRes.json().catch(() => ({}));
console.log('send status:', sent.status, sent.retcode, JSON.stringify(sent.data ?? {}).slice(0, 300));
if (sent.status !== 'ok') process.exit(1);
console.log(`已私聊发送 B站${useMiniApp ? '小程序' : '链接'}卡（在 QQ 里点一下，确认能打开视频页）`);
