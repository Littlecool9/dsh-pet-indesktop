/**
 * 设置页可编辑性验收（本地真机）：逐个标签页检查“非只读”的输入/下拉/开关是否真的能改。
 *
 * 背景（2026-10-24）：用户反馈 B站「作息窗口」加不了/删不了、输入框打字弹回。
 * 根因是 setPath 收到字符串路径后按字符遍历，生成 n.i.g.h.t... 垃圾键；同类问题
 * （白名单全放行、记忆 B站→QQ 开关）也一起修了。这个脚本把“整页非只读项必须能改”
 * 变成可重复执行的验收，避免下次又靠用户点一遍才发现。
 *
 * 规则：只改本地状态，每项后点「撤销改动」；从不点保存，不写服务端配置。
 * 搜索框（不是设置）和「运行模式」下拉（有服务端副作用）不测。
 *
 * 运行：npm run ui:audit（需要 DSH Web 已启动 + 本机 Edge）
 * 退出码：0 = 全部可改；1 = 有失败项（逐条打印）。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { discoverDshSessionCookie } from '../../../src/dsh-client.js';
import { discoverDshBaseUrl } from '../../../src/dsh-port.js';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = Number(process.env.AUDIT_CDP_PORT || 9240);
const DSH = process.env.DSH_URL || await discoverDshBaseUrl() || 'http://127.0.0.1:10551';
const PROFILE = path.join(os.tmpdir(), `dsh-ui-settings-editable-${Date.now()}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitJson(url, ms = 20000) { const until = Date.now() + ms; while (Date.now() < until) { try { const r = await fetch(url); if (r.ok) return r.json(); } catch {} await sleep(300); } throw new Error('timeout ' + url); }

const TABS = [
  ['overview', '概览'], ['characters', '角色'], ['qq', 'QQ'], ['bili', 'B站'], ['tokens', 'Token 额度'],
  ['watch', '观看历史'], ['memory', '记忆'], ['align', '对齐'], ['extensions', '扩展'],
  ['advanced', '全部参数'], ['diag', '诊断'],
];

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--window-size=1440,1200', 'about:blank'], { stdio: 'ignore', windowsHide: true });
try {
  await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  let id = 1; const pending = new Map();
  ws.addEventListener('message', (e) => { const m = JSON.parse(String(e.data)); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } });
  const send = (method, params = {}) => new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return { exception: r.exceptionDetails.text, detail: r.exceptionDetails.exception?.description };
    return r.result?.value;
  };

  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1200, deviceScaleFactor: 1, mobile: false });
  const cookie = discoverDshSessionCookie(DSH);
  if (cookie) { const [name, ...rest] = cookie.split('='); await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' }); }
  await send('Page.navigate', { url: DSH }); await sleep(5000);
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='继续'); if(b)b.click(); })()`);
  await sleep(1000);
  await evaluate(`document.querySelector('[aria-label="账号菜单"]')?.click()`);
  await sleep(1000);
  await evaluate(`(() => { const l=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&(e.textContent||'').trim()==='设置'); (l?.closest('button,[role="menuitem"],a')||l?.parentElement)?.click(); })()`);
  await sleep(2000);
  await evaluate(`(() => {
    const nav=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='通用设置');
    const container=nav?.parentElement ?? document.body;
    const target=[...container.querySelectorAll('button,a,[role="button"],[role="tab"]')].find(e=>(e.innerText||'').trim()==='SurfCore');
    target?.click();
  })()`);
  await sleep(2500);

  const helpers = `
    window.__audit = (() => {
      const scope = () => document.querySelector('.qbw-app');
      const visible = (el) => {
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && el.offsetParent !== null;
      };
      const labelOf = (el) => {
        const row = el.closest('.qbw-row,.qbw-admin-field,.qbw-budget-field,.qbw-search,.qbw-budget-line,label,.qbw-item');
        return ((row?.innerText || el.getAttribute('aria-label') || el.placeholder || el.type || '') + '').replace(/\\s+/g, ' ').trim().slice(0, 140);
      };
      const all = () => scope() ? [...scope().querySelectorAll('input,select,textarea')].filter((el) => {
        if (el.type === 'file' || el.type === 'hidden') return false;
        return visible(el);
      }) : [];
      const keyOf = (el) => ({ tag: el.tagName, type: el.type || '', label: labelOf(el), placeholder: el.placeholder || '' });
      const find = (key) => {
        const list = all().filter((el) => {
          const k = keyOf(el);
          return k.tag === key.tag && k.type === key.type && k.label === key.label && k.placeholder === key.placeholder;
        });
        return list[key.occ] || null;
      };
      const snapshot = () => all().map((el, i) => {
        const k = keyOf(el);
        return { i, ...k, value: el.type === 'checkbox' || el.type === 'radio' ? null : el.value, checked: el.checked ?? null, disabled: el.disabled, readOnly: el.readOnly, occ: 0 };
      });
      const tagOccurrences = () => {
        const seen = new Map();
        for (const el of all()) {
          const k = keyOf(el);
          const base = k.tag + '|' + k.type + '|' + k.label + '|' + k.placeholder;
          el.setAttribute('data-audit-occ', String(seen.get(base) || 0));
          seen.set(base, (seen.get(base) || 0) + 1);
        }
      };
      const tagIds = () => all().forEach((el, i) => el.setAttribute('data-audit-id', String(i)));
      const byId = (i) => scope()?.querySelector('[data-audit-id="' + i + '"]') || null;
      const info = (el) => {
        const k = keyOf(el);
        return { ...k, occ: Number(el.getAttribute('data-audit-occ') || 0), value: el.type === 'checkbox' || el.type === 'radio' ? null : el.value, checked: el.checked ?? null, disabled: el.disabled, readOnly: el.readOnly };
      };
      return { all, find, snapshot, tagOccurrences, tagIds, byId, info, labelOf };
    })();
  `;

  const openAll = `(() => {
    let opened=0;
    for (const g of document.querySelectorAll('.qbw-group')) {
      if ((g.innerText||'').trim().startsWith('▸')) { g.click(); opened++; }
    }
    for (const d of document.querySelectorAll('details')) { if (!d.open) { d.open = true; opened++; } }
    return opened;
  })()`;

  const results = { summary: [], disabled: [], failures: [] };

  for (const [tabId, label] of TABS) {
    await evaluate(`(() => { const b=[...document.querySelectorAll('.qbw-tab')].find(e=>(e.innerText||'').trim()===${JSON.stringify(label)}); b?.click(); })()`);
    await sleep(900);
    // 展开式表单也要算“整页”：角色页的新建表单、记忆页的手动记一条。
    if (label === '角色') {
      await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='新建角色'); if(b) b.click(); })()`);
      await sleep(400);
    }
    if (label === '记忆') {
      await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='手动记一条'); if(b) b.click(); })()`);
      await sleep(400);
    }
    for (let i = 0; i < 8; i++) { const n = await evaluate(openAll); await sleep(250); if (!n) break; }
    await evaluate(helpers);

    const snap = await evaluate('window.__audit.snapshot()');
    if (!Array.isArray(snap)) { results.summary.push({ tab: label, error: JSON.stringify(snap) }); continue; }
    const disabled = snap.filter((c) => c.disabled || c.readOnly);
    const testable = snap.filter((c) => !c.disabled && !c.readOnly).filter((c) => {
      const text = `${c.label} ${c.placeholder}`;
      if (/搜索|搜标题|参数名/.test(text)) return false;
      if (c.tag === 'SELECT' && c.label.includes('运行模式')) return false;
      // 「全部参数」页第 0 个下拉是 QQ/B站/合体 切换器，切走会让整页控件换掉。
      if (c.tag === 'SELECT' && /QQ config\.json/.test(c.label)) return false;
      return true;
    });
    for (const d of disabled) results.disabled.push({ tab: label, ...d });

    let pass = 0, unverified = 0; const fail = [];
    for (const c of testable) {
      // 先撤销任何未保存配置
      await evaluate(`(() => { const b=[...document.querySelectorAll('.qbw-foot button')].find(x=>(x.innerText||'').trim()==='撤销改动'); if(b && !b.disabled) b.click(); })()`);
      await sleep(120);
      await evaluate('window.__audit.tagIds()');
      const found = await evaluate(`(() => { const el=window.__audit.byId(${c.i}); if(!el) return null; el.scrollIntoView({block:'center'}); el.focus(); return window.__audit.info(el); })()`);
      if (!found) { unverified += 1; continue; }
      // 真实输入
      if (c.tag === 'SELECT') {
        await evaluate(`(() => {
          const el=window.__audit.byId(${c.i});
          const opts=[...el.options].map(o=>o.value).filter(v=>v!==el.value);
          if(!opts.length) return;
          el.value=opts[0]; el.dispatchEvent(new Event('change',{bubbles:true}));
        })()`);
      } else if (c.type === 'checkbox' || c.type === 'radio') {
        await evaluate(`(() => { const el=window.__audit.byId(${c.i}); el.click(); })()`);
      } else if (c.type === 'range') {
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
      } else {
        await send('Input.insertText', { text: '7' });
      }
      await sleep(380);
      const after = await evaluate(`(() => { const el=window.__audit.byId(${c.i}); if(!el) return null; return window.__audit.info(el); })()`);
      let ok;
      if (c.type === 'checkbox' || c.type === 'radio') ok = after && after.checked === !found.checked;
      else if (c.type === 'range') ok = after && Number(after.value) !== Number(found.value);
      else if (c.tag === 'SELECT') ok = after && after.value !== found.value;
      else ok = after && after.value !== found.value;
      if (!after) unverified += 1;
      else if (ok) pass += 1;
      else fail.push({ ...c, before: c.type === 'checkbox' ? found.checked : found.value, after: c.type === 'checkbox' ? after.checked : after.value });
      // 还原
      await evaluate(`(() => { const b=[...document.querySelectorAll('.qbw-foot button')].find(x=>(x.innerText||'').trim()==='撤销改动'); if(b && !b.disabled) b.click(); })()`);
      await sleep(120);
      // 没有配置脏标记的本地控件：尽量反向操作一次
      if (c.type === 'checkbox' || c.type === 'radio') {
        const dirty = await evaluate(`(() => { const b=[...document.querySelectorAll('.qbw-foot button')].find(x=>(x.innerText||'').trim()==='撤销改动'); return b ? !b.disabled : false; })()`);
        if (!dirty) await evaluate(`(() => { const el=window.__audit.byId(${c.i}); if(el && el.checked === ${JSON.stringify(!found.checked)}) el.click(); })()`);
      }
    }
    results.summary.push({ tab: label, editable: testable.length, disabledOrReadOnly: disabled.length, pass, unverified, fail: fail.length });
    for (const f of fail) results.failures.push({ tab: label, ...f });
    console.log(`## ${label}: editable ${testable.length}, pass ${pass}, unverified ${unverified}, fail ${fail.length}, disabled/read-only ${disabled.length}`);
    for (const f of fail) console.log(`  FAIL ${f.tag}/${f.type} ${f.label} :: ${JSON.stringify(f.before)} -> ${JSON.stringify(f.after)}`);
    for (const d of disabled) console.log(`  READONLY/DISABLED ${d.tag}/${d.type} ${d.label}`);
  }

  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(results.summary, null, 2));
  console.log('\n=== FAILURES ===');
  console.log(JSON.stringify(results.failures, null, 2));
  if (results.failures.length) {
    console.error(`\n✗ 有 ${results.failures.length} 个非只读控件改不动；见上面的 FAIL 行。`);
    process.exitCode = 1;
  } else {
    console.log('\n✓ 所有非只读控件都能改动（只读项已单独列出，供人工确认）。');
  }
  ws.close();
} finally {
  try { edge.kill(); } catch {}
  await sleep(500);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
