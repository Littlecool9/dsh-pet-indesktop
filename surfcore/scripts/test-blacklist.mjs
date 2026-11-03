/**
 * 人的黑名单（config.json → deny.users）回归。
 *
 * 用户 2026-10-23 原话：「设置里 QQ 白名单那里底下加一个黑名单功能，
 * 不响应黑名单中的人的消息，无论什么群」。
 *
 * 为什么必须单独钉一遍：
 *   · 现有的 allow/deny.private、allow/deny.groups 判的是**会话**（群号 / 私聊对象）。
 *     群本身在白名单里时，同群的黑名单用户照样能把消息送进上下文、触发唤醒 ——
 *     光改 allowed() 完全拦不住他。
 *   · 拦截点必须早于所有副作用（入库、记忆、鱼群、唤醒）。放在 handleIncoming 中途，
 *     表现就是「拉黑了但半夜还是被他的消息叫醒」。
 *   · 拉黑还要压过 allowAllWhenEmpty（全放行）和管理员白名单里的私聊，否则语义自相矛盾。
 *
 * 全部在 fixture 里跑（虚拟网关 + 临时目录），不连真实 QQ / DSH。
 * 运行：node scripts/test-blacklist.mjs
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { bridgeHarness } from './audit-bridge-harness.mjs';

let failures = 0;
async function test(name, run, options) {
  const h = await bridgeHarness(options);
  try { await run(h); console.log('PASS', name); }
  catch (error) { failures++; console.error('FAIL', name, error.message); }
  finally { await h.close(); }
}

const groupEvent = (userId, text = '你好') => ({
  post_type: 'message',
  message_type: 'group',
  group_id: 456,
  user_id: userId,
  self_id: 1,
  message_id: 1000 + (Number(userId) % 900),
  sender: { user_id: userId, nickname: `fixture-${userId}` },
  message: [{ type: 'text', data: { text } }],
});

const privateEvent = (userId, text = '在吗') => ({
  post_type: 'message',
  message_type: 'private',
  user_id: userId,
  self_id: 1,
  message_id: 2000 + (Number(userId) % 900),
  sender: { user_id: userId, nickname: `fixture-${userId}` },
  message: [{ type: 'text', data: { text } }],
});

// ── 配置口径 ────────────────────────────────────────────────────────────────
await test('deny.users 从 config.json 读进来后被收敛成字符串，比较时容忍数字 / 空格', async (h) => {
  assert.deepEqual([...h.cfg.deny.users], ['999', '888'], '数字与字符串都要收进列表，非法项丢弃，重复项去重');
  assert.equal(h.senderBlocked(999, h.cfg.deny.users), true, '数字发送者要能命中');
  assert.equal(h.senderBlocked('999', h.cfg.deny.users), true, '字符串发送者要能命中');
  assert.equal(h.senderBlocked(' 999 ', h.cfg.deny.users), true, '带空格的写法也必须命中（否则用户填了不生效）');
  assert.equal(h.senderBlocked(777, h.cfg.deny.users), false);
  assert.equal(h.senderBlocked('', h.cfg.deny.users), false, '没有发送者时不在这里拦');
  assert.equal(h.senderBlocked(999, undefined), false, '没配 deny.users 时不能误伤');
}, { config: { deny: { users: [999, '999', ' 888 ', 'abc'] } } });

await test('没配 deny.users（旧配置）时一切照旧', async (h) => {
  assert.equal(h.cfg.deny.users.length, 0);
}, {});

// ── 入站拦截：reserved2（二代仿真主模式）────────────────────────────────────
await test('reserved2：黑名单的人发群消息不入未读、不建会话、不触发唤醒', async (h) => {
  h.setMode('reserved2');
  const key = 'group:456';
  const unreadCount = () => (h.getSocialV2State(key).unread ?? []).length;
  const before = unreadCount();
  await h.handleIncoming('group', '456', groupEvent(999), h.cfg);
  assert.equal(unreadCount(), before, '黑名单消息不能进未读（进了就会被下一次唤醒看见）');
  assert.equal(h.calls.created.length, 0, '不能为黑名单消息建 DSH 会话');
  assert.equal(h.calls.prompts.length, 0, '不能给 agent 发提示词');
  // 对照：同一个群里别人说话照常入库 —— 拦的是「人」，不是「群」。
  await h.handleIncoming('group', '456', groupEvent(777), h.cfg);
  assert.equal(unreadCount(), before + 1, '同群其他人不受影响');
}, { config: { deny: { users: ['999'] } } });

// ── 入站拦截：chat（一代）─────────────────────────────────────────────────
await test('chat：黑名单的人发群消息不建会话、不回话', async (h) => {
  h.setMode('chat');
  await h.handleIncoming('group', '456', groupEvent(999), h.cfg);
  assert.equal(h.calls.created.length, 0, '不能建会话');
  assert.equal(h.calls.prompts.length, 0, '不能把消息投给 agent');
  assert.equal(h.state.sessions['group:456'], undefined);
}, { config: { deny: { users: ['999'] }, chat: { presence: { enabled: false } } } });

// ── 私聊：拉黑压过私聊白名单 ────────────────────────────────────────────────
await test('私聊：人同时在 allow.private 里，只要进了黑名单就不响应', async (h) => {
  h.setMode('chat');
  await h.handleIncoming('private', '999', privateEvent(999), h.cfg);
  assert.equal(h.calls.created.length, 0, '黑名单优先于白名单：不建会话');
  assert.equal(h.calls.prompts.length, 0);
  assert.equal(h.state.sessions['private:999'], undefined);
}, { config: { allow: { private: ['999', '123'], groups: ['456'] }, deny: { users: ['999'] }, chat: { presence: { enabled: false } } } });

// ── 全放行也拦得住 ──────────────────────────────────────────────────────────
await test('allowAllWhenEmpty 全放行时，黑名单里的人仍然被拦', async (h) => {
  const before = (h.getSocialV2State('group:456').unread ?? []).length;
  h.setMode('reserved2');
  await h.handleIncoming('group', '456', groupEvent(999), h.cfg);
  assert.equal((h.getSocialV2State('group:456').unread ?? []).length, before, '全放行不等于放行黑名单');
  await h.handleIncoming('group', '456', groupEvent(777), h.cfg);
  assert.equal((h.getSocialV2State('group:456').unread ?? []).length, before + 1, '非黑名单仍然全放行');
}, { config: { allow: { private: [], groups: [] }, allowAllWhenEmpty: true, deny: { users: ['999'] } } });

// ── 私聊黑名单不拦群聊（2026-10-23 真实踩坑的固化断言）──────────────────────
// 用户把想「彻底拉黑」的人填进了「仅拦私聊（deny.private）」，然后在群里实测发现还在回。
// 这不是 bug 而是设计：deny.private 只拦私聊。把它写成断言，防止以后有人
// 「顺手」把 deny.private 也接进群消息的入站拦截，反而把语义搞混。
await test('deny.private 只拦私聊：同一个人在群里照常入库', async (h) => {
  h.setMode('reserved2');
  const gBefore = (h.getSocialV2State('group:456').unread ?? []).length;
  await h.handleIncoming('group', '456', groupEvent(999), h.cfg);
  assert.equal((h.getSocialV2State('group:456').unread ?? []).length, gBefore + 1, 'deny.private 不该影响群聊');
  const pBefore = (h.getSocialV2State('private:999').unread ?? []).length;
  await h.handleIncoming('private', '999', privateEvent(999), h.cfg);
  assert.equal((h.getSocialV2State('private:999').unread ?? []).length, pBefore, 'deny.private 要拦住私聊');
}, { config: { allow: { private: ['999'], groups: ['456'] }, deny: { private: ['999'] } } });

// ── 拉黑前的积压也不能再喂给模型 ────────────────────────────────────────────
// 场景：把人拉黑之前，他的消息已经堆在未读里。重启后如果不清，下一次唤醒
//（哪怕是被别人触发的）会把这些旧消息当成新消息回一遍 —— 看起来就是「黑名单没生效」。
await test('启动时清掉黑名单用户在未读/最近上下文里的积压，别人的保留', async (h) => {
  const st = h.getSocialV2State('group:456');
  assert.deepEqual([...(st.unread ?? [])].map((m) => String(m.userId ?? '')), ['777'], '黑名单用户的未读必须在启动时清掉');
  assert.deepEqual([...(st.recentMessages ?? [])].map((m) => String(m.userId ?? '')), ['777'], '最近上下文里的也要清掉');
  assert.equal(h.calls.created.length, 0, '清理本身不能触发会话');
}, {
  config: { deny: { users: ['999'] } },
  files: {
    'state/social-v2.json': {
      conversations: {
        'group:456': {
          unread: [
            { sender: '黑名单', userId: '999', text: 'a', time: 1000 },
            { sender: '正常人', userId: '777', text: 'b', time: 2000 },
          ],
          recentMessages: [
            { sender: '黑名单', userId: '999', text: 'a', time: 1000 },
            { sender: '正常人', userId: '777', text: 'b', time: 2000 },
          ],
        },
      },
    },
  },
});

// ── 拍一拍不能成为绕过通道 ──────────────────────────────────────────────────
await test('reserved2：黑名单的人拍一拍不入库、不触发唤醒', async (h) => {
  h.setMode('reserved2');
  const key = 'group:456';
  const before = (h.getSocialV2State(key).unread ?? []).length;
  await h.handlePokeNotice({
    post_type: 'notice', notice_type: 'notify', sub_type: 'poke',
    group_id: 456, user_id: 999, sender_id: 999, target_id: 1, self_id: 1,
  });
  assert.equal((h.getSocialV2State(key).unread ?? []).length, before, '拍一拍也不能把黑名单用户送进未读');
  assert.equal(h.calls.created.length, 0, '拍一拍不能建会话');
}, { config: { deny: { users: ['999'] } } });

// ── 控制台：旧页面保存不能把黑名单抹掉 ──────────────────────────────────────
{
  const h = await bridgeHarness({ config: { deny: { users: ['999'] } } });
  const server = h.startConsoleServer();
  try {
    if (!server.listening) await new Promise((resolve) => server.once('listening', resolve));
    const port = server.address().port;
    const call = (method, p, body) => new Promise((resolve, reject) => {
      const request = http.request(
        { host: '127.0.0.1', port, path: p, method, headers: { 'content-type': 'application/json', 'x-console-token': 'fixture-console-token' } },
        (response) => {
          let data = '';
          response.on('data', (chunk) => { data += chunk; });
          response.on('end', () => resolve({ status: response.statusCode, body: data }));
        },
      );
      request.on('error', reject);
      request.setTimeout(3000, () => request.destroy(new Error('request hung')));
      request.end(body === undefined ? undefined : JSON.stringify(body));
    });
    const viaGet = await call('GET', '/api/whitelist');
    assert.equal(viaGet.status, 200);
    assert.deepEqual(JSON.parse(viaGet.body).deny.users, ['999'], 'GET 要能读出人的黑名单');
    // public/console.html 的白名单表单只提交 private/groups（它是旧界面）：
    // 这次保存绝不能把 deny.users 清空。
    const saved = await call('POST', '/api/whitelist', {
      allow: { private: ['123'], groups: ['456'] },
      deny: { private: [], groups: [] },
      ownerQQ: '123',
    });
    assert.equal(saved.status, 200);
    const onDisk = JSON.parse(fs.readFileSync(path.join(h.temp, 'config.json'), 'utf8'));
    assert.deepEqual(onDisk.deny.users, ['999'], '旧控制台保存必须保留 deny.users');
    assert.deepEqual(JSON.parse(saved.body).deny.users.map(String), ['999'], '响应里也要带回黑名单');
    // 显式改黑名单（设置页走的就是这个接口语义）
    const changed = await call('POST', '/api/whitelist', {
      allow: { private: ['123'], groups: ['456'] },
      deny: { users: ['777'], private: [], groups: [] },
      ownerQQ: '123',
    });
    assert.deepEqual(JSON.parse(changed.body).deny.users.map(String), ['777'], '带了 users 就以请求为准');
    console.log('PASS 旧控制台保存白名单不会清空 deny.users，显式提交则以请求为准');
  } catch (error) { failures++; console.error('FAIL 控制台白名单接口保留 deny.users:', error.message); }
  finally { await new Promise((resolve) => server.close(resolve)); await h.close(); }
}

if (failures) process.exitCode = 1;
console.log(failures ? `\n${failures} 项失败` : '\nblacklist tests OK');
