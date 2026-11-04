/**
 * 桌宠自言自语 / 人格卡 / 额度 / 直连用量 / 专注阶段的行为回归。
 *
 * 全程只写临时目录：先把 DSH_HOME / USERPROFILE / SURFCORE_ROOT 指到
 * mkdtemp 再动态 import pet-chat，避免碰到真实 ~/.dsh 或仓库配置。
 * 模型和额度都是假的，不发网络、不花钱。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pet-self-talk-'));
const dshHome = path.join(tmp, '.dsh');
const surfcore = path.join(dshHome, 'surfcore');
const home = path.join(tmp, 'home');
const repoRoot = path.join(tmp, 'surfcore-root');
const characterDir = path.join(surfcore, 'characters', 'demo');
const characterMemory = path.join(characterDir, 'memory');

function writeFile(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text, 'utf8');
}

fs.mkdirSync(home, { recursive: true });
fs.mkdirSync(path.join(repoRoot, 'src'), { recursive: true });
writeFile(path.join(repoRoot, 'config.json'), '{}\n');
writeFile(path.join(repoRoot, 'src', 'bridge.js'), '// fixture\n');
writeFile(path.join(surfcore, 'config.json'), `${JSON.stringify({ admin: { displayName: '阿主' } }, null, 2)}\n`);
writeFile(path.join(surfcore, 'characters', 'current.json'), `${JSON.stringify({
  version: 1, id: 'demo', name: '小咪', epoch: 1, switchedAt: '2026-11-04T00:00:00.000Z',
}, null, 2)}\n`);
writeFile(path.join(characterDir, 'character.json'), `${JSON.stringify({ version: 1, id: 'demo', name: '小咪' }, null, 2)}\n`);
writeFile(path.join(characterDir, 'persona.md'), '# 小咪\n你叫小咪，说话温柔一点。\n');
writeFile(path.join(characterDir, 'persona.daily.md'), '今天想安安静静陪着主人。\n');
writeFile(path.join(characterMemory, 'memory-card-prompt-qq.md'), '主人喜欢猫。\n');
writeFile(path.join(characterDir, 'purpose-outreach.json'), `${JSON.stringify({
  pending: [{ text: '想问问主人今天累不累' }],
  lastPurpose: '陪主人写代码',
  lastEmotionText: '安心',
}, null, 2)}\n`);

process.env.DSH_HOME = dshHome;
process.env.USERPROFILE = home;
process.env.SURFCORE_ROOT = repoRoot;
process.env.SURFCORE_QQBOT_ROOT = repoRoot;

const {
  createPetChatService,
  cleanSelfTalk,
  normalizeFocusPhase,
  normalizeFocusEndsAt,
} = await import('../lib/pet-chat.js');

let failures = 0;
const ok = (cond, label) => {
  if (cond) console.log(`✅ ${label}`);
  else { failures += 1; console.error(`❌ ${label}`); }
};

const agentDefaultModel = { currentSelection: () => ({ provider: 'test', model: 'test-model' }) };

function makeLlm({ response = '今天也要慢慢来。', usage = { inputTokens: 10, outputTokens: 5 }, fail = false, onStream = null } = {}) {
  const calls = [];
  return {
    calls,
    llm: {
      stream(options) {
        calls.push(options);
        return (async function* () {
          if (onStream) await onStream();
          if (fail) throw new Error('boom');
          if (response) yield { type: 'text-delta', text: response };
          if (usage) yield { type: 'usage', usage };
        })();
      },
    },
  };
}

function makeBudget({ blocked = false, statusThrows = false, recordThrows = false } = {}) {
  const recorded = [];
  const blockCalls = [];
  return {
    recorded,
    blockCalls,
    block: async (scope) => {
      blockCalls.push(scope);
      if (statusThrows) throw new Error('budget down');
      return { blocked, message: blocked ? '其他类已到上限' : '' };
    },
    status: async () => {
      if (statusThrows) throw new Error('budget down');
      return {
        day: '2026-11-04',
        usage: { other: { cost: 1.25, tokens: 345 } },
        limits: { other: { cny: 8, tokens: null } },
        ratios: { other: { cost: 0.1, tokens: 0 } },
        blocked: { other: blocked, total: blocked },
        alert: null,
        alertedToday: false,
      };
    },
    recordExternalUsage: (entry) => {
      if (recordThrows) throw new Error('disk full');
      recorded.push(entry);
      return true;
    },
  };
}

function makeService({ tokenBudget = null, llm = makeLlm().llm } = {}) {
  const ctx = {
    get: (name) => {
      if (name === 'llm') return llm;
      if (name === 'agentDefaultModel') return agentDefaultModel;
      return undefined;
    },
  };
  return createPetChatService({ ctx, stateDir: surfcore, pluginLog: () => {}, tokenBudget });
}

console.log('## 1. 纯函数：一句化 / 专注字段归一化');
{
  ok(cleanSelfTalk('**（笑）今天也要加油呀！后面还有一句。**') === '今天也要加油呀！', '去 Markdown/旁白，只留第一句');
  ok(cleanSelfTalk('`嗯`') === '嗯', '去反引号');
  ok(cleanSelfTalk('啊'.repeat(50)).length === 40, '超长自言自语硬截到 40 字');
  ok(cleanSelfTalk('') === '', '空回复保持空串');
  ok(normalizeFocusPhase('work') === 'work' && normalizeFocusPhase('short_break') === 'short_break', '合法专注阶段保留');
  ok(normalizeFocusPhase('bogus') === '' && normalizeFocusPhase(null) === '', '非法专注阶段 → 空串');
  ok(normalizeFocusEndsAt(1700000000000) === 1700000000000, 'epoch 毫秒数字原样保留');
  ok(normalizeFocusEndsAt('2026-11-04T10:00:00.000Z') === Date.parse('2026-11-04T10:00:00.000Z'), 'ISO 字符串归一化成 epoch 毫秒');
  ok(normalizeFocusEndsAt('not-a-date') === 0 && normalizeFocusEndsAt(null) === 0, '非法 endsAt → 0');
}

console.log('## 2. GET /persona 的数据源（只读，不调模型）');
{
  const budget = makeBudget();
  const { llm, calls } = makeLlm();
  const service = makeService({ tokenBudget: budget, llm });
  const payload = service.persona();
  ok(payload.ok === true, 'persona 返回 ok');
  ok(payload.role.id === 'demo' && payload.role.name === '小咪', 'persona 带当前角色 id/name');
  ok(payload.owner.name === '阿主', 'persona 带主人称呼');
  ok(payload.persona.includes('你叫小咪') && payload.persona.includes('今天想安安静静陪着主人'), 'persona 是合成后的人格卡文本');
  ok(/^[a-f0-9]{12}$/.test(payload.hash), 'hash 是 12 位短 sha1');
  ok(payload.hash === service.persona().hash, '同一份人格文本 hash 稳定');
  ok(calls.length === 0, 'persona 不调用模型');
}

console.log('## 3. POST /self-talk 成功路径：一句、带上下文、记账、不落历史/记忆/事件');
{
  const budget = makeBudget();
  const { llm, calls } = makeLlm({ response: '（伸个懒腰）今天也要慢慢来。' });
  const service = makeService({ tokenBudget: budget, llm });
  const endsAt = Date.parse('2026-11-04T10:00:00.000Z');
  const result = await service.selfTalk({
    context: { focus: { phase: 'work', endsAt }, recent: '刚写完代码' },
  });
  ok(result.ok === true, 'self-talk 成功');
  ok(result.text === '今天也要慢慢来。', '只返回一句、去掉动作旁白');
  ok(result.role.name === '小咪', 'self-talk 带角色名');
  ok(calls.length === 1, '一次请求只调一次模型');
  const system = String(calls[0]?.system || '');
  const user = String(calls[0]?.messages?.[0]?.content?.[0]?.text || '');
  ok(system.includes('你叫小咪'), '提示词带人格卡');
  ok(system.includes('主人喜欢猫'), '提示词带记忆卡');
  ok(system.includes('想问问主人今天累不累'), '提示词带目的事实');
  ok(system.includes('正在专注工作') && !system.includes('你正在专注'), '提示词带可选专注阶段，且专注的是主人不是桌宠');
  ok(system.includes('预计') && system.includes('结束'), '提示词带专注结束时间');
  ok(user.includes('刚写完代码'), '用户消息带 recent 上下文');
  ok(budget.recorded.length === 1, '记录一次用量');
  const entry = budget.recorded[0];
  ok(entry.category === 'other' && entry.sessionId === 'pet-chat', '用量归 other / pet-chat');
  ok(entry.label === '桌宠自言自语', '用量标签是「桌宠自言自语」');
  ok(entry.model === 'test-model' && entry.usage?.outputTokens === 5, '用量带模型与 usage');
  ok(!fs.existsSync(path.join(surfcore, 'pet', 'chat', 'history-demo.json')), '不写聊天历史');
  ok(!fs.existsSync(path.join(characterMemory, 'memory-inbox.jsonl')), '不写记忆卡 inbox');
  const polled = await service.poll({ since: 0, waitMs: 0 });
  ok(polled.events.length === 0, '不发桌宠事件');
}

console.log('## 4. POST /self-talk 失败路径：code + hint 非空');
{
  const budget = makeBudget({ blocked: true });
  const { llm, calls } = makeLlm();
  const blocked = await makeService({ tokenBudget: budget, llm }).selfTalk();
  ok(blocked.ok === false && blocked.code === 'budget-blocked', '额度拦截 → budget-blocked');
  ok(Boolean(blocked.error) && Boolean(blocked.hint), '额度拦截带 error + hint');
  ok(calls.length === 0 && budget.recorded.length === 0, '额度拦截不调模型、不记账');
  ok(budget.blockCalls.includes('other'), '先查 other 作用域额度');

  let release;
  let startedResolve;
  const started = new Promise((resolve) => { startedResolve = resolve; });
  const gate = new Promise((resolve) => { release = resolve; });
  const slow = makeLlm({ onStream: async () => { startedResolve(); await gate; } });
  const service = makeService({ tokenBudget: makeBudget(), llm: slow.llm });
  const first = service.selfTalk();
  await started;
  const second = await service.selfTalk();
  ok(second.ok === false && second.code === 'busy', '并发调用 → busy');
  ok(Boolean(second.error) && Boolean(second.hint), 'busy 带 error + hint');
  release();
  const firstResult = await first;
  ok(firstResult.ok === true, '并发结束后第一条正常返回');

  const noLlm = await makeService({ tokenBudget: makeBudget(), llm: null }).selfTalk();
  ok(noLlm.ok === false && noLlm.code === 'llm-unavailable', '模型未就绪 → llm-unavailable');
  ok(Boolean(noLlm.error) && Boolean(noLlm.hint), 'llm-unavailable 带 error + hint');

  const failed = makeLlm({ fail: true });
  const modelFailed = await makeService({ tokenBudget: makeBudget(), llm: failed.llm }).selfTalk();
  ok(modelFailed.ok === false && modelFailed.code === 'model-failed', '模型抛错 → model-failed');
  ok(Boolean(modelFailed.error) && Boolean(modelFailed.hint), 'model-failed 带 error + hint');

  const empty = makeLlm({ response: '', usage: null });
  const emptyResult = await makeService({ tokenBudget: makeBudget(), llm: empty.llm }).selfTalk();
  ok(emptyResult.ok === false && emptyResult.code === 'empty-reply', '空回复 → empty-reply');
  ok(Boolean(emptyResult.error) && Boolean(emptyResult.hint), 'empty-reply 带 error + hint');
}

console.log('## 5. GET /budget 快照与无服务兜底');
{
  const available = await makeService({ tokenBudget: makeBudget({ blocked: true }) }).budget();
  ok(available.ok === true && available.available === true, '有额度服务 → available');
  ok(available.scope === 'other' && available.blocked === true, '按 other 作用域报告拦截');
  ok(Boolean(available.message), '拦截时带 message');
  ok(available.usage?.other?.tokens === 345 && available.limits?.other?.cny === 8, '带 usage/limits 快照');

  const missing = await makeService({ tokenBudget: null }).budget();
  ok(missing.ok === true && missing.blocked === false && missing.available === false, '没接额度服务 → ok + available:false');

  const broken = await makeService({ tokenBudget: makeBudget({ statusThrows: true }) }).budget();
  ok(broken.ok === false && broken.code === 'budget-unavailable', '额度服务抛错 → budget-unavailable');
  ok(Boolean(broken.error) && Boolean(broken.hint), 'budget-unavailable 带 error + hint');
}

console.log('## 6. POST /usage 直连用量校验与记账');
{
  const budget = makeBudget();
  const service = makeService({ tokenBudget: budget });
  const longLabel = '看'.repeat(80);
  const result = service.recordDirectUsage({
    model: 'deepseek-flash',
    usage: { outputTokens: 12, inputTokens: 30, cacheReadTokens: 0 },
    label: longLabel,
  });
  ok(result.ok === true && result.recorded === true, '用法合法 → recorded');
  const entry = budget.recorded[0];
  ok(entry.category === 'other' && entry.sessionId === 'pet-direct', '归 other / pet-direct');
  ok(entry.model === 'deepseek-flash' && entry.usage?.outputTokens === 12, '透传 model / usage');
  ok(entry.label.startsWith('桌宠直连：'), '标签带「桌宠直连：」前缀');
  ok(entry.label.length <= '桌宠直连：'.length + 40, '标签截到 40 字以内');

  const before = budget.recorded.length;
  for (const usage of [null, [], { outputTokens: '12' }, { foo: 1 }]) {
    const bad = service.recordDirectUsage({ model: 'm', usage, label: 'x' });
    ok(bad.ok === false && bad.code === 'invalid-usage', `非法 usage（${JSON.stringify(usage)}）→ invalid-usage`);
    ok(Boolean(bad.error) && Boolean(bad.hint), '非法 usage 带 error + hint');
  }
  ok(budget.recorded.length === before, '非法 usage 不记账');

  const noBudget = makeService({ tokenBudget: null }).recordDirectUsage({ model: 'm', usage: { outputTokens: 1 } });
  ok(noBudget.ok === false && noBudget.code === 'budget-unavailable', '没额度服务 → budget-unavailable');
  ok(Boolean(noBudget.hint), 'budget-unavailable 带 hint');

  const throwing = makeService({ tokenBudget: makeBudget({ recordThrows: true }) })
    .recordDirectUsage({ model: 'm', usage: { outputTokens: 1 } });
  ok(throwing.ok === false && throwing.code === 'usage-record-failed', '记账抛错 → usage-record-failed');
  ok(Boolean(throwing.error) && Boolean(throwing.hint), 'usage-record-failed 带 error + hint');
}

console.log('## 7. POST /focus 扩展：phase / endsAt 持久化、事件透传、旧文件兼容');
{
  const service = makeService({ tokenBudget: null });
  const initial = service.readFocus();
  ok(initial.enabled === false && initial.phase === '' && initial.endsAt === 0, '默认专注状态无阶段字段');

  const iso = '2026-11-04T10:00:00.000Z';
  const state = service.setFocus(true, 'pet', { phase: 'work', endsAt: iso });
  ok(state.phase === 'work' && state.endsAt === Date.parse(iso), '合法 phase/ISO 归一化后持久化');
  const read = service.readFocus();
  ok(read.phase === 'work' && read.endsAt === Date.parse(iso), 'readFocus 返回 phase/endsAt');
  ok(service.publicConfig().focus.phase === 'work' && service.publicConfig().focus.endsAt === Date.parse(iso), 'publicConfig().focus 带 phase/endsAt');
  ok(service.status().focus.phase === 'work' && service.status().focus.endsAt === Date.parse(iso), 'status().focus 带 phase/endsAt');
  const event = (await service.poll({ since: 0, waitMs: 0 })).events[0];
  ok(event?.type === 'focus' && event.phase === 'work' && event.endsAt === Date.parse(iso), 'focus 事件透传 phase/endsAt');

  const bogus = service.setFocus(true, 'pet', { phase: 'bogus', endsAt: 'not-a-date' });
  ok(bogus.phase === '' && bogus.endsAt === 0, '非法 phase/endsAt 归一化成空值');

  const off = service.setFocus(false, 'pet', { phase: 'work', endsAt: Date.parse(iso) });
  ok(off.enabled === false && off.phase === '' && off.endsAt === 0, '关闭专注会清空 phase/endsAt');

  writeFile(path.join(surfcore, 'pet', 'focus.json'), `${JSON.stringify({
    enabled: true, updatedAt: '2026-10-01T00:00:00.000Z', source: 'old-client',
  }, null, 2)}\n`);
  const legacy = service.readFocus();
  ok(legacy.enabled === true && legacy.phase === '' && legacy.endsAt === 0, '旧 focus.json（无新字段）继续可用');
}

console.log('## 8. self-talk 没带专注上下文时退回 focus.json');
{
  const { llm, calls } = makeLlm({ response: '安静待着。' });
  const service = makeService({ tokenBudget: makeBudget(), llm });
  const endsAt = Date.parse('2026-11-04T10:00:00.000Z');
  service.setFocus(true, 'pet', { phase: 'work', endsAt });
  const result = await service.selfTalk({});
  ok(result.ok === true, '无上下文 self-talk 成功');
  const system = String(calls[0]?.system || '');
  ok(system.includes('正在专注工作') && system.includes('预计'), '提示词用 focus.json 的阶段与结束时间');
  service.setFocus(false, 'pet');
  await service.selfTalk({});
  const offSystem = String(calls[1]?.system || '');
  ok(!offSystem.includes('专注'), '专注关闭后提示词不再提专注');
}

fs.rmSync(tmp, { recursive: true, force: true });
console.log(failures === 0 ? '\n✅ pet-chat 自言自语/人格/额度回归通过' : `\n❌ ${failures} 项失败`);
process.exit(failures === 0 ? 0 : 1);
