/**
 * 截一张「定时分享视频到群（B站 → QQ）」的图，用来验收 PITFALLS #21。
 *
 * 为什么单独一个脚本：ui-tabs.mjs 每页只截首屏，分享段在管理员卡/今天用量卡下面，
 * 首屏经常看不到；这里直接按标题滚过去，顺便断言它在新版 client.js 里真的存在。
 *
 * 运行：node plugins/surfcore/scripts/ui-share-shot.mjs
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { discoverDshSessionCookie } from '../../../src/dsh-client.js';
import { discoverDshBaseUrl } from '../../../src/dsh-port.js';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9227;
const DSH = process.env.DSH_URL || await discoverDshBaseUrl() || 'http://127.0.0.1:3080';
const PROFILE = path.join(os.tmpdir(), `dsh-ui-share-${Date.now()}`);
const OUT = path.join(import.meta.dirname, '..', 'docs', 'ui-share-section.png');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitJson(url, ms = 20000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try { const r = await fetch(url); if (r.ok) return r.json(); } catch {}
    await sleep(300);
  }
  throw new Error('timeout');
}

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  '--window-size=1440,1000', 'about:blank',
], { stdio: 'ignore', windowsHide: true });

try {
  await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  let id = 1;
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(String(e.data));
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    }
  });
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = id++;
    pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  const cookie = discoverDshSessionCookie(DSH);
  const [name, ...rest] = cookie.split('=');
  await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' });
  await send('Page.navigate', { url: DSH });
  await sleep(5000);

  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='继续'); if(b)b.click(); })()`);
  await sleep(1000);
  await evaluate(`document.querySelector('[aria-label="账号菜单"]')?.click()`);
  await sleep(1000);
  await evaluate(`(() => { const l=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&(e.textContent||'').trim()==='设置'); (l?.closest('button,[role="menuitem"],a')||l?.parentElement)?.click(); })()`);
  await sleep(2000);
  const sec = await evaluate(`(() => {
    const nav=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='通用设置');
    const container=nav?.parentElement ?? document.body;
    const target=[...container.querySelectorAll('button,a,[role="button"],[role="tab"]')].find(e=>(e.innerText||'').trim()==='SurfCore');
    if(!target) return 'not found';
    target.click(); return target.tagName;
  })()`);
  console.log('SurfCore section:', sec);
  await sleep(2500);
  const tabClicked = await evaluate(`(() => {
    const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='B站');
    if(!b) return 'not found';
    b.click(); return 'clicked';
  })()`);
  console.log('B站 tab:', tabClicked);
  await sleep(1500);

  const resources = await evaluate(`JSON.stringify(performance.getEntriesByType('resource').map((r) => r.name).filter((n) => /surfcore|plugin/i.test(n)).slice(0, 20))`);
  console.log('plugin resources:', resources);
  const title = '定时分享视频到群（B站 → QQ）';
  const hasOld = await evaluate(`document.body.innerText.includes('B站 → QQ 自动分享')`);
  console.log('页面里还有旧标题「B站 → QQ 自动分享」:', hasOld);
  const found = await evaluate(`(() => {
    const wanted=${JSON.stringify(title)};
    const all=[...document.querySelectorAll('*')].filter((e) => (e.textContent||'').includes(wanted));
    all.sort((a,b) => a.textContent.length - b.textContent.length);
    const el=all[0];
    if(!el) return 'not found';
    // 设置弹窗有内部滚动容器，scrollIntoView 不一定带走它；手动把祖先的 scrollTop 推到位。
    const notes=[];
    let node=el;
    while(node && node!==document.body){
      if(node.scrollHeight>node.clientHeight+2){
        const delta=(el.getBoundingClientRect().top - node.getBoundingClientRect().top) - 12;
        node.scrollTop = Math.max(0, node.scrollTop + delta);
        notes.push((node.className||node.tagName)+':'+Math.round(node.scrollTop));
      }
      node=node.parentElement;
    }
    return 'found top='+Math.round(el.getBoundingClientRect().top)+' ancestors='+notes.join('|');
  })()`);
  console.log('share section:', found);
  await sleep(800);
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
  console.log('saved:', OUT, fs.statSync(OUT).size);
  if (found !== 'found') process.exitCode = 1;
  ws.close();
} finally {
  try { edge.kill(); } catch {}
  await sleep(500);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
