/**
 * 目的栏目 + 桌宠对话卡的本地验收截图（只读，不改配置）。
 *
 * 运行：node plugins/surfcore/scripts/ui-purpose.mjs
 * 输出：plugins/surfcore/docs/ui-purpose.png / ui-pet-chat.png
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
const PROFILE = path.join(os.tmpdir(), `dsh-ui-purpose-${Date.now()}`);
const OUT_DIR = path.join(import.meta.dirname, '..', 'docs');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitJson(url, ms = 20000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(300);
  }
  throw new Error('timeout ' + url);
}

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore', windowsHide: true });
try {
  await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  let id = 1;
  const pending = new Map();
  const consoleErrors = [];
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(String(event.data));
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
      consoleErrors.push((msg.params.args ?? []).map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(String(msg.params?.exceptionDetails?.exception?.description ?? '').slice(0, 300));
    }
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = id++;
    pending.set(i, { resolve, reject });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  const cookie = discoverDshSessionCookie(DSH);
  if (!cookie) throw new Error('拿不到 DSH 会话 Cookie（DSH 是否在跑？）');
  const [name, ...rest] = cookie.split('=');
  await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' });
  await send('Page.navigate', { url: DSH });
  await sleep(5000);

  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='继续'); if(b)b.click(); })()`);
  await sleep(800);
  await evaluate(`document.querySelector('[aria-label="账号菜单"]')?.click()`);
  await sleep(800);
  await evaluate(`(() => { const l=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&(e.textContent||'').trim()==='设置'); (l?.closest('button,[role="menuitem"],a')||l?.parentElement)?.click(); })()`);
  await sleep(2000);
  const section = await evaluate(`(() => {
    const nav=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='通用设置');
    const container=nav?.parentElement ?? document.body;
    const target=[...container.querySelectorAll('button,a,[role="button"],[role="tab"]')].find(e=>(e.innerText||'').trim()==='SurfCore');
    if(!target) return 'not found';
    target.click(); return 'clicked';
  })()`);
  console.log('section', section);
  await sleep(2500);

  const clickTab = async (label) => {
    const clicked = await evaluate(`(() => {
      const b=[...document.querySelectorAll('.qbw-tab')].find(e=>(e.innerText||'').trim()===${JSON.stringify(label)});
      if(!b) return 'not found';
      b.click(); return 'clicked';
    })()`);
    await sleep(1400);
    return clicked;
  };
  const shot = async (file) => {
    const data = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(file, Buffer.from(data.data, 'base64'));
    return fs.statSync(file).size;
  };

  console.log('purpose tab', await clickTab('目的'));
  const purposeCheck = await evaluate(`(() => {
    const text = document.body.innerText;
    return {
      carrier: text.includes('触发载体'),
      petOption: text.includes('桌宠气泡 / 语音'),
      qqOption: text.includes('QQ 私聊（默认）'),
      modality: text.includes('桌宠主动搭话形式'),
      purposeCard: text.includes('主动找主人 · 目的机制'),
      testCard: text.includes('桌宠对话'),
      fallback: text.includes('桌宠没开着时回落到 QQ'),
      errors: [...document.querySelectorAll('.qbw-err')].map(e => e.innerText).slice(0, 3),
    };
  })()`);
  console.log('purpose-check', JSON.stringify(purposeCheck));
  console.log('ui-purpose.png', await shot(path.join(OUT_DIR, 'ui-purpose.png')));

  console.log('pet tab', await clickTab('桌宠'));
  const petCheck = await evaluate(`(() => {
    const text = document.body.innerText;
    return {
      chatCard: text.includes('启用桌宠对话'),
      focusRow: text.includes('专注模式（不主动打扰）'),
      rememberRow: text.includes('把桌宠对话写进记忆卡'),
      limits: text.includes('文本回复上限') && text.includes('语音回复上限'),
      reasoning: text.includes('思考强度'),
      status: text.includes('角色：'),
      errors: [...document.querySelectorAll('.qbw-err')].map(e => e.innerText).slice(0, 3),
    };
  })()`);
  console.log('pet-check', JSON.stringify(petCheck));
  console.log('ui-pet-chat.png', await shot(path.join(OUT_DIR, 'ui-pet-chat.png')));

  console.log('console-errors', JSON.stringify(consoleErrors.slice(0, 8)));
  if (!purposeCheck.carrier || !purposeCheck.petOption || !purposeCheck.modality || !purposeCheck.purposeCard) {
    console.error('FAIL: 目的栏目没有渲染出预期内容');
    process.exitCode = 1;
  }
  if (!petCheck.chatCard || !petCheck.limits || !petCheck.focusRow || !petCheck.rememberRow) {
    console.error('FAIL: 桌宠对话卡没有渲染出预期内容');
    process.exitCode = 1;
  }
} finally {
  try { edge.kill(); } catch {}
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
