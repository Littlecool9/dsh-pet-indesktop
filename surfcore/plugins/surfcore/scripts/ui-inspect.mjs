import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { discoverDshSessionCookie } from '../../../src/dsh-client.js';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9224;
const DSH = 'http://127.0.0.1:58750';
const PROFILE = path.join(os.tmpdir(), `dsh-ui-inspect-${Date.now()}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitJson(url, ms = 20000) { const until = Date.now() + ms; while (Date.now() < until) { try { const r = await fetch(url); if (r.ok) return r.json(); } catch {} await sleep(300); } throw new Error('timeout'); }
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
try {
  await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  let id = 1; const pending = new Map();
  ws.addEventListener('message', (e) => { const m = JSON.parse(String(e.data)); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } });
  const send = (method, params = {}) => new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  const cookie = discoverDshSessionCookie(DSH); const [name, ...rest] = cookie.split('=');
  await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' });
  await send('Page.navigate', { url: DSH }); await sleep(5000);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  const dump = await send('Runtime.evaluate', { expression: `(() => {
    const rows = [];
    for (const el of document.querySelectorAll('button,a,[role="button"],[aria-label],[title]')) {
      const text = (el.innerText || '').trim().slice(0, 40);
      const aria = el.getAttribute('aria-label') || '';
      const title = el.title || '';
      if (text || aria || title) rows.push({ tag: el.tagName, text, aria, title, cls: String(el.className).slice(0, 60) });
    }
    return rows.slice(0, 120);
  })()`, returnByValue: true });
  console.log(JSON.stringify(dump.result?.value, null, 2));
  ws.close();
} finally { try { edge.kill(); } catch {} await sleep(500); try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {} }
