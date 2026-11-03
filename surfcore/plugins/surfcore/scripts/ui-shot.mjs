/**
 * 用本机 Edge 的 CDP 打开 DSH Web，点进「设置 → SurfCore」，截图。
 * 仅用于本地验收，不修改任何配置。
 *
 * 运行：node scripts/ui-shot.mjs
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { discoverDshSessionCookie } from '../../../src/dsh-client.js';
import { discoverDshBaseUrl } from '../../../src/dsh-port.js';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9225;
// 端口会漂移（PITFALLS #5）：优先 DSH_URL，其次自动发现，最后才用旧默认值。
const DSH = process.env.DSH_URL || await discoverDshBaseUrl() || 'http://127.0.0.1:3080';
const PROFILE = path.join(os.tmpdir(), `dsh-ui-shot-${Date.now()}`);
const OUT = path.join(import.meta.dirname, '..', 'docs', 'ui-shot.png');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitJson(url, timeoutMs = 20000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(300);
  }
  throw new Error(`timeout waiting ${url}`);
}

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, 'about:blank',
], { stdio: 'ignore', windowsHide: true });

try {
  const version = await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  console.log('edge', version.Browser);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(String(event.data));
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result?.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  const cookie = discoverDshSessionCookie(DSH);
  if (cookie) {
    const [name, ...rest] = cookie.split('=');
    await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' });
  }
  await send('Page.navigate', { url: DSH });
  await sleep(5000);

  // 1. 关掉「预览版说明」弹窗
  console.log('dismiss preview:', await evaluate(`(() => {
    const b = [...document.querySelectorAll('button')].find((e) => (e.innerText || '').trim() === '继续');
    if (b) { b.click(); return 'clicked'; }
    return 'no preview modal';
  })()`));
  await sleep(1200);

  // 2. 打开账号菜单
  console.log('account menu:', await evaluate(`(() => {
    const b = document.querySelector('[aria-label="账号菜单"]');
    if (!b) return 'not found';
    b.click(); return 'clicked';
  })()`));
  await sleep(1200);

  const menu = await evaluate(`(() => [...document.querySelectorAll('button,[role="button"],a')].map((e) => ({
    text: (e.innerText || '').trim().slice(0, 30),
    aria: e.getAttribute('aria-label') || '',
    title: e.title || '',
  })).filter((x) => (x.text + x.aria + x.title).trim()))()`);
  console.log('menu candidates:', JSON.stringify(menu, null, 2).slice(0, 2000));

  // 3. 点“设置”（账号菜单项可能不是 button，用叶子文本精确定位）
  console.log('settings:', await evaluate(`(() => {
    const leaves = [...document.querySelectorAll('*')].filter((e) => e.children.length === 0 && (e.textContent || '').trim() === '设置');
    for (const leaf of leaves) {
      const target = leaf.closest('[role="menuitem"],button,a') || leaf.parentElement || leaf;
      if (target && typeof target.click === 'function') {
        target.click();
        return 'clicked: ' + target.tagName;
      }
    }
    return 'not found';
  })()`));
  await sleep(2500);

  // 4. 设置里点「SurfCore」（找叶子节点，避免点到包含全部导航文字的祖先）
  console.log('section:', await evaluate(`(() => {
    const leaves = [...document.querySelectorAll('*')].filter((e) => e.children.length === 0 && (e.textContent || '').trim() === 'SurfCore');
    for (const leaf of leaves) {
      const target = leaf.closest('button,[role="button"],a') || leaf.parentElement || leaf;
      if (target && typeof target.click === 'function') {
        target.click();
        return 'clicked: ' + target.tagName + ' / ' + (target.textContent || '').slice(0, 40);
      }
    }
    return 'not found';
  })()`));
  await sleep(3000);

  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
  console.log('screenshot:', OUT, fs.statSync(OUT).size);

  const body = await evaluate('document.body.innerText');
  console.log('body text:', String(body ?? '').slice(0, 2500));
  ws.close();
} finally {
  try { edge.kill(); } catch {}
  await sleep(500);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
