// 跨会话发送（2026-11-04）：默认允许任意活跃会话令牌发到白名单目标；
// 关掉 socialV2.crossSession.enabled 回到「令牌必须属于目标会话」。
// 纯 helper + 真 bridge.js（VM 夹具）/ HTTP 端点 + 源码接线三层验证，不连真 QQ。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {
  canonicalConversationKey, crossSessionEnabled, findLiveTokenKey,
  reachableTargets, resolveSendToken, sanitizeTargetName,
} from '../src/cross-session.js';
import { bridgeHarness } from './audit-bridge-harness.mjs';

// ── 1. 纯 helper ────────────────────────────────────────────────────────────
const conversations = new Map([
  ['private:123', { agentToken: 'tok-private' }],
  ['group:456', { agentToken: 'tok-group' }],
]);
const cfgOn = {};
const cfgOff = { socialV2: { crossSession: { enabled: false } } };

assert.equal(crossSessionEnabled(cfgOn), true, '默认开启');
assert.equal(crossSessionEnabled(cfgOff), false, '显式 false 才关闭');
assert.equal(canonicalConversationKey('group:00456'), 'group:456');
assert.equal(canonicalConversationKey('private:0'), '', '0 不是合法会话');
assert.equal(findLiveTokenKey(conversations, 'tok-private'), 'private:123');

const same = resolveSendToken({ targetKey: 'private:123', token: 'tok-private', conversations, cfg: cfgOff });
assert.equal(same.allowed, true, '本会话令牌始终可用');
assert.equal(same.crossSession, false);

const cross = resolveSendToken({ targetKey: 'group:456', token: 'tok-private', conversations, cfg: cfgOn });
assert.equal(cross.allowed, true, '默认允许跨会话发送');
assert.equal(cross.crossSession, true);
assert.equal(cross.sourceKey, 'private:123');

const crossOff = resolveSendToken({ targetKey: 'group:456', token: 'tok-private', conversations, cfg: cfgOff });
assert.equal(crossOff.allowed, false, '关掉开关后回退旧行为');
assert.equal(crossOff.reason, 'cross-session-disabled');

assert.equal(resolveSendToken({ targetKey: 'group:456', token: 'stale', conversations, cfg: cfgOn }).allowed, false, '未知/过期令牌拒绝');
assert.equal(resolveSendToken({ targetKey: 'group:456', token: '', conversations, cfg: cfgOn }).allowed, false, '缺令牌拒绝');
// 目标会话还没有 live state 也能跨会话发送（D3：目标不在醒着也能收）。
const toCold = resolveSendToken({ targetKey: 'group:999', token: 'tok-private', conversations, cfg: cfgOn });
assert.equal(toCold.allowed, true);
assert.equal(toCold.crossSession, true);
assert.equal(toCold.sourceKey, 'private:123');

// 可达目标：白名单群 + 主人私聊，最多 12 条，名字压成单行。
const manyGroups = Array.from({ length: 15 }, (_, i) => String(100 + i));
const targets = reachableTargets({
  cfg: { ownerQQ: 123, allow: { groups: manyGroups }, deny: { groups: ['100'] } },
  groupName: (gid) => (gid === '101' ? '第一行\n第二行\t群' : ''),
});
assert.equal(targets.length, 12, '最多 12 个目标');
assert.equal(targets[0].key, 'private:123', '主人私聊在列表里');
assert.ok(!targets.some((t) => t.key === 'group:100'), '黑名单群不列');
const named = targets.find((t) => t.key === 'group:101');
assert.ok(named && named.name === '第一行 第二行 群', '群名必须单行 sanitize');
assert.ok(!targets.some((t) => t.key === 'group:101' && /\n|\t/.test(t.name)), '不能有换行/制表符');
assert.equal(reachableTargets({ cfg: cfgOn, max: 99 }).length, 0, '没有白名单时不乱列');
assert.equal(sanitizeTargetName('a\r\nb', 10), 'a b');

// ── 2. 源码接线：每个发送端点都必须走 resolveSendAuth ──────────────────────
const bridgeSource = fs.readFileSync(path.join(import.meta.dirname, '..', 'src', 'bridge.js'), 'utf8');
function endpointBlock(token) {
  const marker = `url.pathname === '${token}'`;
  const start = bridgeSource.indexOf(marker);
  assert.ok(start >= 0, `找不到端点 ${token}`);
  const next = bridgeSource.indexOf('\n        if (', start + marker.length);
  return bridgeSource.slice(start, next > start ? next : start + 16000);
}
for (const endpoint of [
  '/api/socialV2/send-message',
  '/api/socialV2/send-burst',
  '/api/socialV2/send-sticker',
  '/api/socialV2/send-voice',
  '/api/socialV2/send-poke',
  '/api/send/group',
]) {
  assert.match(endpointBlock(endpoint), /resolveSendAuth\(/, `${endpoint} 必须使用跨会话令牌 helper`);
}
assert.ok(!/if \(token && !agentTokenOk\(key, token\)\)/.test(bridgeSource), '发送端点不能残留旧的严格绑定');
assert.match(bridgeSource, /agentTokenOk\(key, req\.headers\['x-agent-token'\]\)/, '读端点仍严格绑定本会话');
assert.match(bridgeSource, /crossSessionPromptLine\(\)/, '唤醒提示必须接跨会话可达目标');
assert.match(bridgeSource, /crossSession: crossSessionPromptInfo\(\)/, 'qq_get_prompt 必须返回跨会话目标');

// ── 3. 真 bridge.js + HTTP：跨会话发送 / 额度 / 闸门 ────────────────────────
function listen(server) {
  return new Promise((resolve, reject) => {
    if (server.listening) return resolve();
    server.once('listening', resolve);
    server.once('error', reject);
  });
}
function closeServer(server) {
  return new Promise((resolve) => server.close(resolve));
}
function request(port, method, p, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const req = http.request({
      host: '127.0.0.1', port, path: p, method,
      headers: {
        'content-type': 'application/json',
        'x-console-token': 'fixture-console-token',
        'x-agent-call': '1',
        ...headers,
      },
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        let parsed = null;
        try { parsed = JSON.parse(data); } catch {}
        resolve({ status: res.statusCode, body: parsed, raw: data });
      });
    });
    req.on('error', reject);
    req.setTimeout(5000, () => req.destroy(new Error('request hung')));
    req.end(payload);
  });
}

const h = await bridgeHarness({ config: { socialV2: { tokenGuard: { enabled: true, maxOutboundPerTurn: 8 } } } });
let server = null;
try {
  h.setMode('reserved2');
  const sourceKey = 'private:123';
  const targetKey = 'group:456';
  const sourceToken = h.getSocialV2State(sourceKey).agentToken;
  const targetState = h.getSocialV2State(targetKey);
  assert.ok(sourceToken, '夹具有来源会话令牌');
  server = h.startConsoleServer();
  await listen(server);
  const port = server.address().port;

  const sent = await request(port, 'POST', '/api/socialV2/send-message', { key: targetKey, messages: '跨会话的测试消息' }, { 'x-agent-token': sourceToken });
  assert.equal(sent.status, 200, sent.raw);
  assert.equal(sent.body?.ok, true);
  const crossEntry = targetState.recentMessages.at(-1);
  assert.equal(crossEntry?.isSelf, true, '跨会话消息要进目标会话历史');
  assert.equal(crossEntry?.viaKey, sourceKey, '目标历史必须能看出是从哪个会话发的');
  assert.equal(crossEntry?.viaLabel, '主人私聊', '主人私聊不把 QQ 号原样给模型');
  assert.equal(crossEntry?.text, '跨会话的测试消息');
  assert.equal(h.getSocialV2State(sourceKey).tokenTurnSent, 1, '每回合额度记到来源会话');
  assert.equal(targetState.tokenTurnSent || 0, 0, '目标会话不背来源回合的额度');

  const burst = await request(port, 'POST', '/api/socialV2/send-burst', { key: targetKey, messages: ['第二条跨会话消息'] }, { 'x-agent-token': sourceToken });
  assert.equal(burst.status, 200, burst.raw);
  assert.equal(targetState.recentMessages.at(-1)?.viaKey, sourceKey);
  assert.equal(h.getSocialV2State(sourceKey).tokenTurnSent, 2);

  const stale = await request(port, 'POST', '/api/socialV2/send-message', { key: targetKey, messages: 'x' }, { 'x-agent-token': 'stale-token' });
  assert.equal(stale.status, 403, '未知/过期令牌必须拒绝');

  const outside = await request(port, 'POST', '/api/socialV2/send-message', { key: 'group:999', messages: 'x' }, { 'x-agent-token': sourceToken });
  assert.equal(outside.status, 403, '目标不在白名单必须拒绝');

  const read = await request(port, 'GET', `/api/socialV2/recent?key=${encodeURIComponent(targetKey)}&limit=5`, undefined, { 'x-agent-token': sourceToken });
  assert.equal(read.status, 403, '读端点仍必须令牌属于目标会话');

  // D3 的出处标记必须真的进模型可见上下文：唤醒快照 + recent 工具。
  const targetToken = targetState.agentToken;
  const recent = await request(port, 'GET', `/api/socialV2/recent?key=${encodeURIComponent(targetKey)}&limit=5`, undefined, { 'x-agent-token': targetToken });
  assert.equal(recent.status, 200, recent.raw);
  const recentCross = (recent.body?.messages ?? []).filter((m) => m.viaKey === sourceKey).at(-1);
  assert.ok(recentCross?.viaNote?.includes('主人私聊'), `recent 工具必须带出处标记：${JSON.stringify(recentCross)}`);
  assert.ok(!recentCross?.viaNote?.includes(sourceKey), '主人私聊不应把 raw key 给模型');
  const wakeSnap = h.buildWakeSnapshotV2(targetKey);
  const snapCross = (wakeSnap?.recent ?? []).find((m) => /主人私聊/.test(String(m?.viaNote ?? '')));
  assert.ok(snapCross?.viaNote?.includes('那边决定发到这里的'), '唤醒快照必须渲染 viaKey 出处');

  h.socialV2.paused = true;
  const groupToken = h.getSocialV2State(targetKey).agentToken;
  const paused = await request(port, 'POST', '/api/socialV2/send-poke', { key: sourceKey, targetUserId: '' }, { 'x-agent-token': groupToken });
  assert.equal(paused.status, 403, '暂停时跨会话发送也必须被拦');
  h.socialV2.paused = false;

  fs.writeFileSync(path.join(h.temp, 'state', 'current-role.json'), JSON.stringify({ role: null, mode: 'silent' }));
  const silent = await request(port, 'POST', '/api/socialV2/send-message', { key: targetKey, messages: 'x' }, { 'x-agent-token': sourceToken });
  assert.equal(silent.status, 403, '静默模式对跨会话发送同样生效');
  fs.writeFileSync(path.join(h.temp, 'state', 'current-role.json'), JSON.stringify({ role: null, mode: 'active' }));

  // D4：开启时唤醒提示/qq_get_prompt 列出可达目标。
  const info = h.crossSessionPromptInfo();
  assert.ok(info?.enabled, '默认开启时应有跨会话提示');
  assert.ok(info.targets.some((t) => t.key === sourceKey), '列表要含主人私聊');
  assert.ok(info.targets.some((t) => t.key === targetKey), '列表要含白名单群');
  assert.ok(info.targets.length <= 12, '最多 12 条');
  const prompt = h.buildWakePromptV2(targetKey, 'bootstrap');
  assert.ok(prompt.includes('【跨会话发送】'), '唤醒提示必须告诉模型可以跨会话发送');
  assert.ok(prompt.includes(targetKey) && prompt.includes(sourceKey), '唤醒提示要列出目标 key');
  assert.ok(!/\n.*\n.*\n/.test(info.targets.map((t) => t.name).join('\n')), '目标名不能带换行');
} finally {
  if (server) await closeServer(server);
  await h.close();
}

// 关闭开关：HTTP 回到 403，提示里也不再出现跨会话能力。
const hOff = await bridgeHarness({ config: { socialV2: { crossSession: { enabled: false } } } });
let serverOff = null;
try {
  hOff.setMode('reserved2');
  const sourceToken = hOff.getSocialV2State('private:123').agentToken;
  hOff.getSocialV2State('group:456');
  serverOff = hOff.startConsoleServer();
  await listen(serverOff);
  const port = serverOff.address().port;
  const denied = await request(port, 'POST', '/api/socialV2/send-message', { key: 'group:456', messages: 'x' }, { 'x-agent-token': sourceToken });
  assert.equal(denied.status, 403, '关闭后跨会话发送必须 403');
  assert.match(String(denied.body?.error ?? ''), /agent token 无效/);
  assert.equal(hOff.getSocialV2State('group:456').recentMessages.length, 0, '被拒绝时不能写目标历史');
  assert.equal(hOff.crossSessionPromptInfo(), null, '关闭时 qq_get_prompt 不返回跨会话提示');
  const prompt = hOff.buildWakePromptV2('group:456', 'bootstrap');
  assert.ok(!prompt.includes('【跨会话发送】'), '关闭时唤醒提示不能声称能跨会话发送');
} finally {
  if (serverOff) await closeServer(serverOff);
  await hOff.close();
}

console.log('✅ 跨会话发送 helper/端点/额度/闸门/提示测试通过');
