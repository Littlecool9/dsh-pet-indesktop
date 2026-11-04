// 桌宠本地接口（lib/pet-api.js）的**行为**回归：不发网络、不碰 ~/.dsh。
//
// 为什么必须有一条真行为测试：`test-client-contract.mjs` 只做字符串包含检查
// （"index.js 里有 createPetApiService"），它能证明"路由注册了"，证明不了
// "没令牌真的会被拒 / 令牌对了真的能通"。而 2026-10-26 的重构把
// 回环/同源/令牌判据抽到了 lib/http-guard.js —— 这类改动一旦出错，
// 现象是「桌宠连不上」或「谁都能连」，两种都不会自己报错。
//
// 这里用假 chat / purpose 服务 + 假 req/res，把每一条分支都钉住。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createPetApiService } from '../lib/pet-api.js';

let failures = 0;
const ok = (cond, label) => {
  if (cond) console.log(`✅ ${label}`);
  else { failures += 1; console.error(`❌ ${label}`); }
};

const TOKEN = 'a'.repeat(48);
const BASE = 'http://127.0.0.1:57981';
const PREFIX = '/dsh-surfcore/pet-api';

const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pet-api-test-'));
let emitted = [];
let focusState = { enabled: false, updatedAt: '', source: '', phase: '', endsAt: 0 };
let selfTalkResult = null;
let budgetResult = null;
let usageResult = null;
let lastSelfTalkContext = null;
let lastUsageBody = null;
let lastFocusOptions = null;
let lastClaimBody = null;
let claimResult = null;

const chat = {
  token: () => TOKEN,
  publicConfig: () => ({ ok: true, chat: { enabled: true, modality: 'text' } }),
  history: (limit) => ({ ok: true, limit, messages: [] }),
  poll: async ({ since, waitMs, clientId }) => ({ ok: true, since, waitMs, clientId, events: [], nextSince: 7 }),
  chat: async ({ text, modality }) => ({ ok: true, reply: { id: 'm1', text: `reply:${text}`, modality, audio: { key: 'deadbeef' } } }),
  persona: () => ({
    ok: true,
    role: { id: 'demo', name: '小咪' },
    persona: '# 小咪\n温柔一点。',
    owner: { name: '主人' },
    hash: 'abcdef012345',
  }),
  selfTalk: async ({ context }) => {
    lastSelfTalkContext = context;
    return selfTalkResult || { ok: true, text: '今天也要慢慢来。', role: { name: '小咪' } };
  },
  budget: async () => budgetResult || {
    ok: true, available: true, scope: 'other', blocked: false, message: '',
    usage: { other: { cost: 1.5, tokens: 2000 } },
    limits: { other: { cny: 8, tokens: null } },
  },
  recordDirectUsage: ({ model, usage, label }) => {
    lastUsageBody = { model, usage, label };
    return usageResult || { ok: true, recorded: true, label: `桌宠直连：${label || ''}`, model: model || '' };
  },
  setFocus: (enabled, source, options) => {
    lastFocusOptions = options;
    focusState = {
      enabled,
      source,
      updatedAt: 'now',
      phase: enabled ? String(options?.phase || '') : '',
      endsAt: enabled ? Number(options?.endsAt || 0) : 0,
    };
    return focusState;
  },
  readAudio: (key) => (key === 'deadbeef' ? { bytes: Buffer.from('RIFFxxxxWAVE') } : null),
  emit: (event) => { emitted.push(event); },
  status: () => ({
    chat: { enabled: true }, role: { id: 'default' }, proactive: {}, presence: {},
    voice: { route: 'cloud' }, llm: {}, focus: focusState, events: {}, lastError: '',
  }),
};

const purpose = {
  // statusForPet 用的是 config()（载体设置），不是 status()（运行时状态）——两者别混。
  config: () => ({ carrier: 'pet', modality: 'text' }),
  status: () => ({ ok: true, carrier: 'pet', online: true }),
  preview: async () => ({ ok: true, preview: '说点什么' }),
  run: async () => ({ ok: true, sent: false }),
  claim: (body) => {
    lastClaimBody = body;
    return claimResult || { ok: true, granted: true, remainingToday: 3, nextAllowedAt: 1700000000000 };
  },
  online: true,
};

const petService = { status: () => ({ installed: true, running: true, dir: 'D:/fake/pet', skins: ['fish'] }) };
const api = createPetApiService({
  chat, purpose, petService, stateDir,
  currentDshUrl: () => BASE,
  pluginLog: () => {},
  version: '0.1.0-test',
});

function makeReq({ method = 'GET', headers = {}, body = null } = {}) {
  const handlers = {};
  const req = {
    method,
    headers,
    on(evt, fn) { handlers[evt] = fn; return req; },
    destroy() {},
    flush() {
      if (body !== null) handlers.data?.(Buffer.from(body));
      handlers.end?.();
    },
  };
  return req;
}

function makeRes() {
  return {
    statusCode: 0,
    headers: {},
    raw: null,
    body: '',
    writeHead(code, headers) { this.statusCode = code; this.headers = headers || {}; },
    end(chunk) {
      if (chunk === undefined || chunk === null) { this.body = ''; return; }
      if (Buffer.isBuffer(chunk)) { this.raw = chunk; this.body = chunk.toString('utf8'); return; }
      this.body = String(chunk);
    },
  };
}

async function call({ method = 'GET', pathname = '/health', headers = {}, body = null, query = '' } = {}) {
  const req = makeReq({ method, headers, body });
  const res = makeRes();
  const url = new URL(`${BASE}${PREFIX}${pathname}${query}`);
  const pending = api.handle(req, res, url);
  req.flush();
  await pending;
  let data = null;
  try { data = JSON.parse(res.body); } catch {}
  return { res, data };
}

const loopback = { host: '127.0.0.1:57981', 'x-pet-token': TOKEN };
const jsonPost = (extra = {}) => ({ ...loopback, 'content-type': 'application/json', ...extra });

console.log('## 1. 令牌：没有 / 不对 / 空，一律 401（失败关闭）');
{
  const noToken = await call({ headers: { host: '127.0.0.1:57981' } });
  ok(noToken.res.statusCode === 401, '不带令牌 → 401');
  const wrong = await call({ headers: { host: '127.0.0.1:57981', 'x-pet-token': 'b'.repeat(48) } });
  ok(wrong.res.statusCode === 401, '令牌错误 → 401');
  const okHeader = await call({ headers: loopback });
  ok(okHeader.res.statusCode === 200 && okHeader.data?.ok === true, '令牌正确（header）→ 200');
  const okQuery = await call({ headers: { host: '127.0.0.1:57981' }, query: `?token=${TOKEN}` });
  ok(okQuery.res.statusCode === 200, '令牌正确（?token=，音频用这条）→ 200');
  const leak = JSON.stringify(wrong.data ?? {});
  ok(!leak.includes(TOKEN) && !leak.includes('57981'), '401 响应不回显令牌、不泄露主机配置');
}

console.log('## 2. 令牌还没生成时：空令牌不得通过');
{
  const emptyTokenApi = createPetApiService({
    chat: { ...chat, token: () => '' },
    purpose, petService, stateDir, currentDshUrl: () => BASE, pluginLog: () => {}, version: 't',
  });
  const req = makeReq({ headers: { host: '127.0.0.1:57981' }, });
  const res = makeRes();
  const pending = emptyTokenApi.handle(req, res, new URL(`${BASE}${PREFIX}/health`));
  req.flush();
  await pending;
  ok(res.statusCode === 401, 'chat.token() 为空时 → 401（不会把"空=空"当通过）');
}

console.log('## 3. 回环与同源');
{
  const remote = await call({ headers: { host: '192.168.1.5:57981', 'x-pet-token': TOKEN } });
  ok(remote.res.statusCode === 403, '非回环 Host → 403');
  const crossSite = await call({ method: 'POST', pathname: '/focus', headers: { ...jsonPost(), origin: 'http://evil.com' }, body: '{}' });
  ok(crossSite.res.statusCode === 403, '写操作跨站 Origin → 403');
  const noOrigin = await call({ method: 'POST', pathname: '/focus', headers: jsonPost(), body: '{"enabled":true}' });
  ok(noOrigin.res.statusCode === 200, '没带 Origin（桌宠主进程）→ 放行');
  const formType = await call({ method: 'POST', pathname: '/focus', headers: { ...loopback, 'content-type': 'application/x-www-form-urlencoded' }, body: 'enabled=1' });
  ok(formType.res.statusCode === 415, '写操作非 JSON content-type → 415');
}

console.log('## 4. 只读接口');
{
  const health = await call({ headers: loopback });
  ok(health.data?.name === 'surfcore-pet' && health.data?.version === '0.1.0-test', '/health 返回名字与版本');
  const status = await call({ pathname: '/status', headers: loopback });
  ok(status.data?.pet?.installed === true && status.data?.purpose?.carrier === 'pet', '/status 带桌宠与目的载体状态');
  const config = await call({ pathname: '/config', headers: loopback });
  ok(config.data?.chat?.modality === 'text', '/config 返回对话参数');
  const history = await call({ pathname: '/history', headers: loopback, query: '?limit=5' });
  ok(history.data?.limit === 5, '/history 透传 limit');
  const events = await call({ pathname: '/events', headers: loopback, query: '?since=6&wait=100&client=pet' });
  ok(events.data?.since === 6 && events.data?.clientId === 'pet', '/events 透传 since/wait/client');
  const purposeStatus = await call({ pathname: '/purpose/status', headers: loopback });
  ok(purposeStatus.data?.carrier === 'pet', '/purpose/status 走目的服务');
  const unknown = await call({ pathname: '/nope', headers: loopback });
  ok(unknown.res.statusCode === 404, '未知路径 → 404');
}

console.log('## 5. 写接口（对话 / 专注 / 目的 / 测试气泡）');
{
  const chatRes = await call({ method: 'POST', pathname: '/chat', headers: jsonPost(), body: '{"text":"在吗","modality":"voice"}' });
  ok(chatRes.data?.reply?.text === 'reply:在吗', '/chat 把文本交给对话服务');
  ok(chatRes.data?.reply?.modality === 'voice', '/chat 透传 modality（语音对话）');

  const focusOn = await call({ method: 'POST', pathname: '/focus', headers: jsonPost(), body: '{"enabled":true,"source":"pet"}' });
  ok(focusOn.data?.focus?.enabled === true, '/focus 打开专注模式');
  const focusOff = await call({ method: 'POST', pathname: '/focus', headers: jsonPost(), body: '{"enabled":false}' });
  ok(focusOff.data?.focus?.enabled === false, '/focus 关闭专注模式');

  const preview = await call({ method: 'POST', pathname: '/purpose/preview', headers: jsonPost(), body: '{}' });
  ok(preview.data?.preview === '说点什么', '/purpose/preview 透传结果');
  const run = await call({ method: 'POST', pathname: '/purpose/run', headers: jsonPost(), body: '{}' });
  ok(run.res.statusCode === 200 && run.data?.ok === true, '/purpose/run 可用');

  emitted = [];
  const testBubble = await call({ method: 'POST', pathname: '/chat/test', headers: jsonPost(), body: '{"text":"嗨"}' });
  ok(testBubble.res.statusCode === 200, '/chat/test → 200');
  ok(emitted.length === 1 && emitted[0].type === 'reply' && emitted[0].text === 'reply:嗨', '/chat/test 会推一条 reply 事件给气泡');
}

console.log('## 6. 音频与发现文件');
{
  const audio = await call({ pathname: '/audio/deadbeef.wav', headers: { host: '127.0.0.1:57981' }, query: `?token=${TOKEN}` });
  ok(audio.res.statusCode === 200 && audio.res.headers['Content-Type'] === 'audio/wav', '/audio/<key>.wav 返回 wav');
  ok(Buffer.isBuffer(audio.res.raw) && audio.res.raw.toString('utf8').startsWith('RIFF'), '音频字节原样返回');
  const missing = await call({ pathname: '/audio/nosuch.wav', headers: loopback });
  ok(missing.res.statusCode === 404, '不存在的音频 → 404');

  const url = api.audioUrlFor('deadbeef');
  ok(url.includes(`?token=${TOKEN}`) && url.startsWith(`${PREFIX}/audio/`), 'audioUrlFor 带令牌');
  const dirty = api.audioUrlFor('../../etc/passwd');
  const dirtyName = dirty.slice(dirty.lastIndexOf('/audio/') + 7, dirty.indexOf('.wav'));
  ok(/^[a-f0-9]+$/i.test(dirtyName), `audioUrlFor 只保留 hex key（${JSON.stringify(dirtyName)}），不拼进路径穿越字符`);

  api.writeHostFile(true);
  const hostFile = path.join(stateDir, 'pet', 'host.json');
  const host = JSON.parse(fs.readFileSync(hostFile, 'utf8'));
  ok(host.baseUrl === BASE && host.token === TOKEN && host.api === PREFIX, 'host.json 含 baseUrl / token / api');
  ok(host.version === 1, 'host.json 带协议版本号（桌宠据此判断兼容）');
}

console.log('## 7. 桌宠客户端扩展接口（人格 / 自言自语 / 额度 / 直连用量 / 专注阶段）');
{
  const noToken = await call({ pathname: '/persona', headers: { host: '127.0.0.1:57981' } });
  ok(noToken.res.statusCode === 401, '/persona 没有令牌 → 401（和旧接口同一把锁）');

  const persona = await call({ pathname: '/persona', headers: loopback });
  ok(persona.res.statusCode === 200 && persona.data?.ok === true, '/persona → 200');
  ok(persona.data?.role?.id === 'demo' && persona.data?.role?.name === '小咪', '/persona 带角色 id/name');
  ok(persona.data?.owner?.name === '主人', '/persona 带主人称呼');
  ok(persona.data?.persona?.includes('# 小咪'), '/persona 返回完整人格卡文本');
  ok(/^[a-f0-9]{12}$/.test(persona.data?.hash || ''), '/persona 的 hash 是 12 位短 sha1');
  ok(Object.keys(persona.data ?? {}).sort().join(',') === 'hash,ok,owner,persona,role', '/persona 字段集合稳定');

  const selfTalk = await call({
    method: 'POST', pathname: '/self-talk', headers: jsonPost(),
    body: '{"context":{"focus":{"phase":"work","endsAt":1700000000000},"recent":"刚写完代码"}}',
  });
  ok(selfTalk.res.statusCode === 200 && selfTalk.data?.text === '今天也要慢慢来。', '/self-talk → 200 + 文本');
  ok(selfTalk.data?.role?.name === '小咪', '/self-talk 带角色名');
  ok(lastSelfTalkContext?.recent === '刚写完代码', '/self-talk 把 context.recent 透传给对话服务');
  ok(lastSelfTalkContext?.focus?.phase === 'work', '/self-talk 把 context.focus 透传给对话服务');

  selfTalkResult = { ok: false, code: 'busy', error: '还在生成', hint: '等这次返回后再试' };
  const busy = await call({ method: 'POST', pathname: '/self-talk', headers: jsonPost(), body: '{}' });
  ok(busy.res.statusCode === 409 && busy.data?.code === 'busy', '并发自言自语 → 409 + code=busy');
  ok(Boolean(busy.data?.hint), 'busy 失败带 hint');

  selfTalkResult = { ok: false, code: 'budget-blocked', error: '额度用完', hint: '明天再试' };
  const blocked = await call({ method: 'POST', pathname: '/self-talk', headers: jsonPost(), body: '{}' });
  ok(blocked.res.statusCode === 429 && blocked.data?.code === 'budget-blocked', '额度拦截 → 429 + code=budget-blocked');
  ok(Boolean(blocked.data?.hint), '额度拦截失败带 hint');
  selfTalkResult = null;

  const badJson = await call({ method: 'POST', pathname: '/self-talk', headers: jsonPost(), body: '{oops' });
  ok(badJson.res.statusCode === 400 && badJson.data?.code === 'invalid-json', '/self-talk 非法 JSON → 400 + code=invalid-json');
  ok(Boolean(badJson.data?.hint), '非法 JSON 失败带 hint');

  const budget = await call({ pathname: '/budget', headers: loopback });
  ok(budget.res.statusCode === 200 && budget.data?.available === true, '/budget → 200 + available');
  ok(budget.data?.scope === 'other' && budget.data?.blocked === false, '/budget 用 other 作用域且未拦截');
  ok(budget.data?.usage?.other?.tokens === 2000 && budget.data?.limits?.other?.cny === 8, '/budget 带 usage/limits 快照');

  budgetResult = { ok: false, code: 'budget-unavailable', error: '读不到', hint: '检查插件日志' };
  const budgetFail = await call({ pathname: '/budget', headers: loopback });
  ok(budgetFail.res.statusCode === 503 && budgetFail.data?.code === 'budget-unavailable', '额度服务不可用 → 503 + code');
  ok(Boolean(budgetFail.data?.hint), '额度服务失败带 hint');
  budgetResult = null;

  const usage = await call({
    method: 'POST', pathname: '/usage', headers: jsonPost(),
    body: '{"model":"deepseek-flash","usage":{"outputTokens":12,"inputTokens":30},"label":"看图"}',
  });
  ok(usage.res.statusCode === 200 && usage.data?.recorded === true, '/usage → 200 + recorded');
  ok(lastUsageBody?.model === 'deepseek-flash' && lastUsageBody?.usage?.outputTokens === 12, '/usage 透传 model/usage');
  ok(lastUsageBody?.label === '看图', '/usage 透传 label');

  usageResult = { ok: false, code: 'invalid-usage', error: 'usage 不合法', hint: '至少带一个数字 token 字段' };
  const usageFail = await call({ method: 'POST', pathname: '/usage', headers: jsonPost(), body: '{"usage":{}}' });
  ok(usageFail.res.statusCode === 400 && usageFail.data?.code === 'invalid-usage', '非法 usage → 400 + code=invalid-usage');
  ok(Boolean(usageFail.data?.hint), '非法 usage 失败带 hint');
  usageResult = null;

  const focus = await call({
    method: 'POST', pathname: '/focus', headers: jsonPost(),
    body: '{"enabled":true,"source":"pet","phase":"short_break","endsAt":"2026-11-04T10:00:00.000Z"}',
  });
  ok(focus.res.statusCode === 200 && focus.data?.focus?.phase === 'short_break', '/focus 接收 phase');
  ok(lastFocusOptions?.endsAt === '2026-11-04T10:00:00.000Z', '/focus 把 endsAt 原样交给对话服务归一化');
}

console.log('## 8. 共享主动说话额度 /proactive/claim');
{
  const noToken = await call({ method: 'POST', pathname: '/proactive/claim', headers: { host: '127.0.0.1:57981', 'content-type': 'application/json' }, body: '{"source":"vision"}' });
  ok(noToken.res.statusCode === 401, '/proactive/claim 没有令牌 → 401');

  const granted = await call({ method: 'POST', pathname: '/proactive/claim', headers: jsonPost(), body: '{"source":"vision"}' });
  ok(granted.res.statusCode === 200 && granted.data?.granted === true, '领到额度 → 200 + granted=true');
  ok(granted.data?.remainingToday === 3 && granted.data?.nextAllowedAt === 1700000000000, 'granted 带 remainingToday / nextAllowedAt');
  ok(lastClaimBody?.source === 'vision', 'source 原样交给目的服务');

  claimResult = { ok: true, granted: false, reason: 'quiet', retryAt: 1700000001000, hint: '现在是安静时段' };
  const denied = await call({ method: 'POST', pathname: '/proactive/claim', headers: jsonPost(), body: '{"source":"self-talk"}' });
  ok(denied.res.statusCode === 200 && denied.data?.granted === false, '额度被拒也是 200 + granted=false');
  ok(denied.data?.reason === 'quiet' && denied.data?.retryAt === 1700000001000, '拒绝带 reason / retryAt');
  ok(Boolean(denied.data?.hint), '拒绝带 hint 下一步');
  claimResult = null;

  const badJson = await call({ method: 'POST', pathname: '/proactive/claim', headers: jsonPost(), body: '{oops' });
  ok(badJson.res.statusCode === 400 && badJson.data?.code === 'invalid-json', '非法 JSON → 400 + code=invalid-json');
  ok(Boolean(badJson.data?.hint), '非法 JSON 带 hint');

  const noSource = await call({ method: 'POST', pathname: '/proactive/claim', headers: jsonPost(), body: '{}' });
  ok(noSource.res.statusCode === 400 && noSource.data?.code === 'invalid-source', '缺 source → 400 + code=invalid-source');
  ok(Boolean(noSource.data?.hint), '缺 source 带 hint');

  const emptySource = await call({ method: 'POST', pathname: '/proactive/claim', headers: jsonPost(), body: '{"source":"   "}' });
  ok(emptySource.res.statusCode === 400 && emptySource.data?.code === 'invalid-source', '空白 source → 400');
}

fs.rmSync(stateDir, { recursive: true, force: true });
console.log(failures === 0 ? '\n✅ pet-api 行为回归通过' : `\n❌ ${failures} 项失败`);
process.exit(failures === 0 ? 0 : 1);
