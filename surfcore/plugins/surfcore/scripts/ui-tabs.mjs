/** 打开合并设置页，逐个标签截图（本地验收）。 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { discoverDshSessionCookie } from '../../../src/dsh-client.js';
import { discoverDshBaseUrl } from '../../../src/dsh-port.js';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9226;
// 端口会漂移（PITFALLS #5）：优先 DSH_URL，其次自动发现，最后才用旧默认值。
const DSH = process.env.DSH_URL || await discoverDshBaseUrl() || 'http://127.0.0.1:3080';
const PROFILE = path.join(os.tmpdir(), `dsh-ui-tabs-${Date.now()}`);
const OUT_DIR = path.join(import.meta.dirname, '..', 'docs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitJson(url, ms = 20000) { const until = Date.now() + ms; while (Date.now() < until) { try { const r = await fetch(url); if (r.ok) return r.json(); } catch {} await sleep(300); } throw new Error('timeout'); }

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore', windowsHide: true });
try {
  await waitJson(`http://127.0.0.1:${PORT}/json/version`);
  const tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  let id = 1; const pending = new Map();
  ws.addEventListener('message', (e) => { const m = JSON.parse(String(e.data)); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } });
  const send = (method, params = {}) => new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;
  // 2026-10-24 起 QQ/B站 的鱼群/目的/收尾/口味都收进「高级设置」；截图前先展开。
  const openAdvanced = async () => {
    const r = await evaluate(`(() => {
      const g=[...document.querySelectorAll('.qbw-group')].find(e=>{
        const t=(e.innerText||'').replace(/\\s+/g,'');
        return t.includes('▸高级设置');
      });
      if(!g) return 'already-open-or-missing';
      g.click(); return 'opened';
    })()`);
    await sleep(600);
    return r;
  };

  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  const cookie = discoverDshSessionCookie(DSH); const [name, ...rest] = cookie.split('=');
  await send('Network.setCookie', { name, value: rest.join('='), domain: '127.0.0.1', path: '/' });
  await send('Page.navigate', { url: DSH }); await sleep(5000);

  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='继续'); if(b)b.click(); })()`);
  await sleep(1000);
  await evaluate(`document.querySelector('[aria-label="账号菜单"]')?.click()`);
  await sleep(1000);
  await evaluate(`(() => { const l=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&(e.textContent||'').trim()==='设置'); (l?.closest('button,[role="menuitem"],a')||l?.parentElement)?.click(); })()`);
  await sleep(2000);
  // 在「设置」对话框内找 SurfCore 入口。
  // 不能全局找文本 = 'SurfCore'：左侧工作区列表里也有一个同名工作区（2026-10-23 踩到，
  // 旧写法点中了工作区，于是每张截图都是「账号与余额」）。这里以「通用设置」为锚点，
  // 在同一个导航容器里找 SurfCore。
  const sec = await evaluate(`(() => {
    const nav=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='通用设置');
    const container=nav?.parentElement ?? document.body;
    const target=[...container.querySelectorAll('button,a,[role="button"],[role="tab"]')].find(e=>(e.innerText||'').trim()==='SurfCore');
    if(!target) return 'not found';
    target.click(); return target.tagName;
  })()`);
  console.log('section click', sec);
  await sleep(2500);

  fs.mkdirSync(OUT_DIR, { recursive: true });
  const tabs = [
    ['overview', '概览'], ['characters', '角色'], ['qq', 'QQ'], ['bili', 'B站'], ['tokens', 'Token 额度'], ['watch', '观看历史'],
    ['memory', '记忆'], ['align', '对齐'], ['extensions', '扩展'],
    ['advanced', '全部参数'], ['diag', '诊断'],
  ];
  for (const [id, label] of tabs) {
    const clicked = await evaluate(`(() => {
      const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()===${JSON.stringify(label)});
      if(!b) return 'not found';
      b.click(); return 'clicked';
    })()`);
    await sleep(1200);
    // 每个标签页都从顶部截图：切 tab 时滚动位置会保留，否则截到的是上一页的中间。
    await evaluate(`(() => {
      window.scrollTo(0, 0);
      let el=document.querySelector('.qbw-tabs')?.parentElement;
      while(el && el.scrollHeight<=el.clientHeight+2) el=el.parentElement;
      if(el) el.scrollTop=0;
    })()`);
    await sleep(400);
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(OUT_DIR, `ui-${id}.png`);
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log(id, clicked, fs.statSync(file).size);
  }
  // 概览「启动」卡（2026-10-24）：三个按钮 + 两边开关状态；单独截一张，顶部截图看不到它。
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='概览'); b?.click(); })()`);
  await sleep(1200);
  const overviewStart = await evaluate(`(() => {
    const h4=[...document.querySelectorAll('h4')].find(e=>(e.innerText||'').trim()==='启动');
    const texts=[...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim());
    h4?.scrollIntoView({ block: 'start' });
    return {
      card: Boolean(h4),
      buttons: ['一键启动','启动QQ','启动B站'].filter(t => texts.includes(t)),
      oldTitleGone: !document.body.innerText.includes('启动与人格卡'),
      personaCardGone: ![...document.querySelectorAll('h4')].some(e => (e.innerText||'').trim()==='人设卡'),
    };
  })()`);
  console.log('overview-start', JSON.stringify(overviewStart));
  await sleep(500);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(OUT_DIR, 'ui-overview-start.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('overview-start-shot', fs.statSync(file).size);
  }
  // 角色页的新建表单单独截一张（新建角色时的文件导入/路径是这一轮的主要交互）。
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='角色'); b?.click(); })()`);
  await sleep(1200);
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='新建角色'); b?.click(); })()`);
  await sleep(800);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(OUT_DIR, 'ui-character-create.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('character-create', fs.statSync(file).size);
  }
  // QQ 鱼群触发记录卡单独截一张：它在白名单下面，默认首屏看不到。
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='QQ'); b?.click(); })()`);
  await sleep(1000);
  console.log('qq-advanced', await openAdvanced());
  const qqStartFound = await evaluate(`(() => {
    const card=[...document.querySelectorAll('h4')].some(e=>(e.innerText||'').trim()==='QQ 启动');
    const sw=[...document.querySelectorAll('input[type=checkbox]')].length > 0;
    return card && sw && document.body.innerText.includes('是否启动');
  })()`);
  console.log('qq-start-card', qqStartFound);
  const qqCardFound = await evaluate(`(() => [...document.querySelectorAll('h4')].some(e=>(e.innerText||'').includes('QQ 鱼群保护')))()`);
  console.log('qq-fishguard-card', qqCardFound);
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('h4')].find(e=>(e.innerText||'').includes('QQ 鱼群保护'));
    if(!el) return 'no-card';
    let sc=el.parentElement;
    while(sc){ const cs=getComputedStyle(sc); if(/(auto|scroll)/.test(cs.overflowY)&&sc.scrollHeight>sc.clientHeight+2) break; sc=sc.parentElement; }
    if(sc){ sc.scrollTop += el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 24; return 'scrolled'; }
    el.scrollIntoView({ block: 'center' }); return 'into-view';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    const file = path.join(OUT_DIR, 'ui-qq-fishguard.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('qq-fishguard', fs.statSync(file).size);
  }
  // 目的机制卡片单独截一张（2026-10-24 新增，位置在鱼群卡下面）。
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='QQ'); b?.click(); })()`);
  await sleep(1000);
  console.log('qq-purpose-advanced', await openAdvanced());
  const purposeCardFound = await evaluate(`(() => [...document.querySelectorAll('h4')].some(e=>(e.innerText||'').includes('主动找主人')))()`);
  console.log('qq-purpose-card', purposeCardFound);
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('h4')].find(e=>(e.innerText||'').includes('主动找主人'));
    if(!el) return 'no-card';
    el.scrollIntoView({ block: 'center' });
    return 'into-view';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    const file = path.join(OUT_DIR, 'ui-qq-purpose.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('qq-purpose', fs.statSync(file).size);
  }
  const purposeSettingsFound = await evaluate(`(() => {
    const text = document.body.innerText || '';
    return ['节奏与安静', '素材与目标', '重试 / 上限 / 目标', '节奏预设'].every((t) => text.includes(t));
  })()`);
  console.log('qq-purpose-settings', purposeSettingsFound);
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('summary')].find(e=>(e.innerText||'').includes('节奏与安静'));
    if (el) { el.scrollIntoView({ block: 'start' }); return 'scrolled'; }
    return 'no-settings';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    const file = path.join(OUT_DIR, 'ui-qq-purpose-settings.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('qq-purpose-settings-shot', fs.statSync(file).size);
  }
  // 对话收尾判断卡片（2026-10-24 新增，位置在目的机制卡下面）。
  const closureCardFound = await evaluate(`(() => [...document.querySelectorAll('h4')].some(e=>(e.innerText||'').includes('对话收尾判断')))()`);
  console.log('qq-closure-card', closureCardFound);
  const closureCopyFound = await evaluate(`(() => {
    const text = document.body.innerText || '';
    return ['收尾规则', '不是潜水', '和潜水的区别', 'qq_close_conversation'].every((t) => text.includes(t));
  })()`);
  console.log('qq-closure-copy', closureCopyFound);
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('h4')].find(e=>(e.innerText||'').includes('对话收尾判断'));
    if (!el) return 'no-card';
    el.scrollIntoView({ block: 'center' });
    return 'into-view';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    const file = path.join(OUT_DIR, 'ui-qq-closure.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('qq-closure', fs.statSync(file).size);
  }
  // B站 鱼群检查记录单独截一张（状态卡下半段）。
  await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='B站'); b?.click(); })()`);
  await sleep(1000);
  console.log('bili-advanced', await openAdvanced());
  const biliStartFound = await evaluate(`(() => {
    const card=[...document.querySelectorAll('h4')].some(e=>(e.innerText||'').trim()==='B站 启动');
    return card && document.body.innerText.includes('是否启动');
  })()`);
  console.log('bili-start-card', biliStartFound);
  const nameRuleField = await evaluate(`(() => document.body.textContent.includes('鱼名开头词'))()`);
  console.log('bili-name-rule-field', nameRuleField);
  const inputInfo = await evaluate(`(() => [...document.querySelectorAll('input')].filter(i => i.value === '肥鱼' || i.value.includes('fish, 鱼') || i.placeholder === '逗号分隔').slice(0, 12).map(i => ({
    value: i.value, placeholder: i.placeholder, readOnly: i.readOnly, disabled: i.disabled,
    pointerEvents: getComputedStyle(i).pointerEvents, display: getComputedStyle(i).display,
    closest: (i.closest('.qbw-row, .qbw-field, label, div')?.textContent || '').slice(0, 80),
  })))()`);
  console.log('bili-inputs', JSON.stringify(inputInfo));
  if (process.env.UI_TYPE_TEST === '1') {
    const focusInfo = await evaluate(`(() => {
      const i=[...document.querySelectorAll('input')].find(i => {
        let p=i.parentElement;
        for(let n=0;n<5&&p;n++,p=p.parentElement) if((p.textContent||'').trim().startsWith('鱼名开头词')) return true;
        return false;
      });
      if(!i) return 'no-input';
      i.focus();
      return { active: document.activeElement === i, before: i.value };
    })()`);
    await send('Input.insertText', { text: 'DSH,吃白饭' });
    await sleep(400);
    const afterType = await evaluate(`(() => {
      const i=[...document.querySelectorAll('input')].find(i => {
        let p=i.parentElement;
        for(let n=0;n<5&&p;n++,p=p.parentElement) if((p.textContent||'').trim().startsWith('鱼名开头词')) return true;
        return false;
      });
      return i ? { value: i.value, readOnly: i.readOnly, disabled: i.disabled } : 'no-input';
    })()`);
    console.log('bili-type-test', JSON.stringify(focusInfo), JSON.stringify(afterType));
  }
  // 单独截「鱼群判定关键词」：用户就是在这里填开头/中间/结尾。
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('.qbw-group')].find(e => (e.textContent||'').includes('鱼群判定关键词（B站）'));
    if(!el) return 'no-keyword-group';
    let sc=el.parentElement;
    while(sc){ const cs=getComputedStyle(sc); if(/(auto|scroll)/.test(cs.overflowY)&&sc.scrollHeight>sc.clientHeight+2) break; sc=sc.parentElement; }
    if(sc){ sc.scrollTop += el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 24; return 'scrolled'; }
    el.scrollIntoView({ block: 'center' }); return 'into-view';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(OUT_DIR, 'ui-bili-keywords.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('bili-keywords', fs.statSync(file).size);
  }
  const biliCheckFound = await evaluate(`(() => [...document.querySelectorAll('.qbw-group')].some(e => (e.textContent||'').includes('点赞历史')))()`);
  console.log('bili-fishguard-check', biliCheckFound);
  await evaluate(`(() => {
    const el=[...document.querySelectorAll('.qbw-group')].find(e => (e.textContent||'').includes('点赞历史'));
    if(!el) return 'no-like-history';
    let sc=el.parentElement;
    while(sc){ const cs=getComputedStyle(sc); if(/(auto|scroll)/.test(cs.overflowY)&&sc.scrollHeight>sc.clientHeight+2) break; sc=sc.parentElement; }
    if(sc){ sc.scrollTop += el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 24; return 'scrolled'; }
    el.scrollIntoView({ block: 'center' }); return 'into-view';
  })()`);
  await sleep(600);
  {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(OUT_DIR, 'ui-bili-fishguard.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('bili-fishguard', fs.statSync(file).size);
  }
  const body = await evaluate('document.body.innerText');
  console.log('body head:', String(body ?? '').slice(0, 1200));
  ws.close();
} finally {
  try { edge.kill(); } catch {}
  await sleep(500);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
