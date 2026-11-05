// 记忆互通圈：默认隔离；同圈互看；每条带来源；
// 2026-11-04：私聊记忆默认进群（privateToGroups），群聊记忆也默认进私聊（groupsToPrivate）；
// 两个方向开关都能单独回到旧隔离。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  addMemoryRecord, createEmptyCard, normalizeMemoryCardConfig,
  renderMemoryCard, resolveMemoryCardPaths, saveMemoryCardOutputs,
} from '../src/memory-card.js';

const SHARING = { circles: [{ name: '熟人圈', groups: ['111', '222'] }] };
const CFG = normalizeMemoryCardConfig({ sharing: SHARING });
const CFG_OFF = normalizeMemoryCardConfig({ sharing: { ...SHARING, privateToGroups: false } });
const CFG_GROUPS_OFF = normalizeMemoryCardConfig({ sharing: { ...SHARING, groupsToPrivate: false } });
const T = Date.parse('2026-11-02T12:00:00+08:00');
const card = createEmptyCard(T);
const add = (input) => addMemoryRecord(card, { createdAt: T, lastSeenAt: T, ...input }, CFG, T);
add({ source: 'qq-group', speaker: '小明', text: 'A群的事', conversationKey: 'group:111', groupId: '111', groupName: 'A群' });
add({ source: 'qq-group', speaker: '小红', text: 'B群的事', conversationKey: 'group:222', groupId: '222', groupName: 'B群' });
add({ source: 'qq-group', speaker: '小刚', text: 'C群的事', conversationKey: 'group:333', groupId: '333', groupName: 'C群' });
add({ source: 'qq-owner', speaker: '主人', text: '私聊的事', conversationKey: 'private:999', private: true });
add({ source: 'qq-private', speaker: '路人', text: '别人的私聊', conversationKey: 'private:888', private: true });
add({ source: 'pet-owner', platform: 'pet', speaker: '主人', text: '桌宠的事', conversationKey: 'pet', private: true });
add({ source: 'manual', speaker: '管理员', text: '手动全局记忆', manual: true });

const render = (key, config = CFG) => renderMemoryCard(card, { config, platform: 'qq', conversationKey: key, maxChars: 8000 });
const a = render('group:111');
const b = render('group:222');
const c = render('group:333');
const priv = render('private:999');
assert.ok(a.includes('A群的事') && a.includes('B群的事'), '同圈 A 应看到 A/B');
assert.ok(!a.includes('C群的事'), 'A 不应看到圈外 C');
assert.ok(a.includes('群聊·A群 / group:111'), '记忆必须带来源群名+ID');
assert.ok(b.includes('A群的事') && b.includes('B群的事'), '同圈 B 应看到 A/B');
assert.ok(!c.includes('A群的事') && !c.includes('B群的事'), 'C 默认隔离');
assert.ok(c.includes('手动全局记忆'), '手动记忆可全局');
// 默认 privateToGroups=true：群里能看到私聊记忆，但仍保留原来的「谁（私聊）」来源和分寸提示。
assert.ok(a.includes('私聊的事'), '默认私聊记忆应进群（D5）');
assert.ok(a.includes('主人（私聊）：'), '私聊记录必须标出来自和谁的私聊');
assert.ok(a.includes('带「私聊」标记的是私下聊到的事'), '群里出现私聊记忆时必须带分寸提示');
assert.ok(!a.includes('桌宠的事'), '桌宠记录永不进群');
// 默认 groupsToPrivate=true：私聊能看到任意群聊记录 + 手动记忆，来源标签不变；别人的私聊和桌宠仍排除。
assert.ok(priv.includes('A群的事') && priv.includes('C群的事'), '私聊应能想起任意群聊记录（groupsToPrivate）');
assert.ok(priv.includes('群聊·A群 / group:111'), '群记录进私聊时保留「群聊·群名 / group:ID」来源');
assert.ok(priv.includes('手动全局记忆'), '私聊也要能看到手动全局记忆');
assert.ok(priv.includes('主人（私聊）：'), '自己的私聊记录仍带来源');
assert.ok(priv.includes('私聊的事'), '私聊仍能看到自己的私聊');
assert.ok(!priv.includes('别人的私聊'), '别人的私聊记录仍不进当前私聊');
assert.ok(!priv.includes('桌宠的事'), '私聊不掺桌宠记录');
assert.ok(priv.includes('带「群聊」标记的是群里发生的事'), '私聊里出现群聊记忆时必须带分寸提示');
assert.ok(!a.includes('来源未知'), '没有未知来源混入');

// privateToGroups=false 精确回到旧行为：私聊记忆不进群；同圈群互看不变。
const aOff = render('group:111', CFG_OFF);
assert.ok(!aOff.includes('私聊的事'), 'privateToGroups=false 时私聊记忆不得进群');
assert.ok(!aOff.includes('带「私聊」标记的是私下聊到的事'), '没有私聊记录时不该出现分寸提示');
assert.ok(aOff.includes('A群的事') && aOff.includes('B群的事'), '关掉私聊入群不影响同圈互通');
assert.ok(!aOff.includes('桌宠的事'), '桌宠记录始终不进群');

// groupsToPrivate=false 精确回到旧行为：私聊只看自己的私聊，群记忆一条都不进。
const privGroupsOff = render('private:999', CFG_GROUPS_OFF);
assert.ok(!privGroupsOff.includes('A群的事') && !privGroupsOff.includes('C群的事'), 'groupsToPrivate=false 时群记忆不得进私聊');
assert.ok(!privGroupsOff.includes('带「群聊」标记的是群里发生的事'), '没有群记录时不该出现群聊分寸提示');
assert.ok(privGroupsOff.includes('私聊的事'), '关掉群记忆入私聊不影响自己的私聊');
assert.ok(!privGroupsOff.includes('别人的私聊') && !privGroupsOff.includes('桌宠的事'), '别人的私聊/桌宠始终排除');

// 同文本不同群不能被去重合并
const before = card.records.length;
add({ source: 'qq-owner', speaker: '主人', text: '同一句话', conversationKey: 'group:111', groupId: '111', groupName: 'A群' });
add({ source: 'qq-owner', speaker: '主人', text: '同一句话', conversationKey: 'group:222', groupId: '222', groupName: 'B群' });
assert.equal(card.records.length, before + 2, '跨群同文本不能合并');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'memory-sharing-'));
try {
  const paths = resolveMemoryCardPaths(tmp);
  saveMemoryCardOutputs(paths, card, CFG, T);
  const map = JSON.parse(fs.readFileSync(path.join(tmp, 'memory-card-prompt-qq-groups.json'), 'utf8'));
  assert.ok(map.blocks['group:111'].includes('A群的事'));
  assert.ok(map.blocks['group:111'].includes('私聊的事'), '按会话 map 必须反映私聊进群');
  assert.ok(map.blocks['group:111'].includes('主人（私聊）：'));
  assert.ok(map.blocks['private:999'].includes('私聊的事'));
  assert.ok(map.blocks['private:999'].includes('A群的事'), '按会话 map 必须反映群记忆进私聊');
  assert.ok(!map.blocks['private:999'].includes('别人的私聊'), '按会话 map 不能把别人的私聊带进来');
  // 没有自己记录的群也要能拿到默认块（私聊+手动，不含别的群）。
  assert.ok(map.blocks['group:*'], '必须写默认群记忆块');
  assert.ok(map.blocks['group:*'].includes('私聊的事'), '默认群块应含私聊记录');
  assert.ok(map.blocks['group:*'].includes('手动全局记忆'), '默认群块应含手动全局记忆');
  assert.ok(!map.blocks['group:*'].includes('A群的事'), '默认群块不能混入具体群记录');
  // 没有自己记录的私聊也要能拿到默认块（群聊+手动，不含任何真实私聊）。
  assert.ok(map.blocks['private:*'], '必须写默认私聊记忆块');
  assert.ok(map.blocks['private:*'].includes('A群的事') && map.blocks['private:*'].includes('C群的事'), '默认私聊块应含任意群记录');
  assert.ok(map.blocks['private:*'].includes('手动全局记忆'), '默认私聊块应含手动全局记忆');
  assert.ok(!map.blocks['private:*'].includes('私聊的事') && !map.blocks['private:*'].includes('别人的私聊'), '默认私聊块不能混入真实私聊');
  assert.ok(!map.blocks['private:*'].includes('桌宠的事'), '默认私聊块不能混入桌宠记录');
  saveMemoryCardOutputs(paths, card, CFG_OFF, T);
  const mapOff = JSON.parse(fs.readFileSync(path.join(tmp, 'memory-card-prompt-qq-groups.json'), 'utf8'));
  assert.ok(!mapOff.blocks['group:111'].includes('私聊的事'), 'privateToGroups=false 时 map 里群块不得含私聊');
  assert.equal(mapOff.blocks['group:*'], undefined, '关闭私聊进群时不写默认群块');
  saveMemoryCardOutputs(paths, card, CFG_GROUPS_OFF, T);
  const mapGroupsOff = JSON.parse(fs.readFileSync(path.join(tmp, 'memory-card-prompt-qq-groups.json'), 'utf8'));
  assert.ok(!mapGroupsOff.blocks['private:999'].includes('A群的事'), 'groupsToPrivate=false 时 map 里私聊块不得含群记录');
  assert.equal(mapGroupsOff.blocks['private:*'], undefined, '关闭群记忆进私聊时不写默认私聊块');
  console.log('✅ 记忆互通圈/来源标签/私聊进群/群记忆进私聊测试通过');
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}

const bridgeSource = fs.readFileSync('src/bridge.js', 'utf8');
assert.ok(bridgeSource.includes('conversationIdentityLineV2(key)'), '唤醒 prompt 必须带当前群/私聊身份');
assert.ok(bridgeSource.includes('memoryCardPromptBlock(key)'), '记忆注入必须按当前会话取块');
assert.ok(bridgeSource.includes('MEMORY_CARD_GROUP_PROMPTS'), '桥接必须读按会话记忆块');
assert.ok(bridgeSource.includes("if (currentMode === 'reserved2') return '';"), 'v2 没有按会话块时必须 fail closed');
assert.ok(bridgeSource.includes('groupNameForMemory'), '落库时必须带群名');
