// 「一键抓取偏好关键词」纯逻辑回归：抽词 / 停用词 / 标签直取 / 包含合并 / 已有偏好排除。
// 不联网、不碰真实 ~/.dsh 状态。
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { extractTerms, rankPreferenceCandidates, scanPreferences } from '../plugins/surfcore/tools/lib/pref-scan.mjs';

const keys = (terms) => terms.map((term) => term.key);
const keywords = (list) => list.map((item) => item.keyword);

// ── 抽词：虚词边界 / 停用词 / 英文大小写 ─────────────────────────────────
{
  const terms = keys(extractTerms('我用大肥鱼做了个肉鸽，AI 和 DeepSeek 都好看'));
  assert.ok(terms.includes('大肥鱼'), `应保留「大肥鱼」，实际 ${terms.join(',')}`);
  assert.ok(terms.includes('肉鸽'), `应保留「肉鸽」，实际 ${terms.join(',')}`);
  assert.equal(terms.includes('我用'), false, '「我用」是半句话，不是偏好词');
  assert.equal(terms.includes('做了个'), false, '含「了」的片段应丢弃');
  assert.equal(terms.includes('视频'), false, '停用词应丢弃');
  assert.ok(terms.includes('deepseek'), '英文统一小写做键');
  assert.ok(terms.includes('ai'), 'AI 这种短词在白名单里');
}

// ── 标签/收藏夹名：整词直取，不拆出假词 ───────────────────────────────────
{
  const terms = keys(extractTerms('手机游戏', { strong: true, direct: true }));
  assert.deepEqual(terms, ['手机游戏'], 'direct 只保留整词');
  assert.equal(terms.includes('机游戏'), false);

  const ai = keys(extractTerms('AI应用', { strong: true, direct: true }));
  assert.deepEqual(ai, ['ai应用']);
}

// ── 包含关系合并：高频短词不会被低频长词挤掉 ──────────────────────────────
{
  const inputs = [
    ...Array.from({ length: 4 }, (_, i) => ({ text: `大肥鱼第${i}集`, source: 'history', weight: 3 })),
    ...Array.from({ length: 4 }, (_, i) => ({ text: `AI 工具第${i}期`, source: 'history', weight: 3 })),
    { text: 'AI应用', source: 'history-tag', weight: 2.5, strong: true, direct: true },
    { text: '稀有词只出现一次', source: 'history', weight: 3 },
  ];
  const result = keywords(rankPreferenceCandidates(inputs, { limit: 20 }));
  assert.ok(result.includes('大肥鱼'), '高频长词保留');
  assert.equal(result.includes('肥鱼'), false, '被「大肥鱼」覆盖的碎片应删掉');
  assert.ok(result.includes('AI'), 'AI 比「AI应用」高频得多，不能被包含关系删掉');
  assert.ok(result.includes('AI应用'), '标签直取的词保留');
  assert.equal(result.includes('稀有词只'), false, '只出现一次的词达不到门槛');
}

// ── 权重 / 来源 / 计数：同一个词由多个源提到会累加分数 ────────────────────
{
  const inputs = [
    { text: '异环 新版本', source: 'history', weight: 3 },
    { text: '异环 二创', source: 'history', weight: 3 },
    { text: '异环 攻略', source: 'favorites', weight: 2.5 },
    { text: 'Alpha 和 Beta', source: 'local', weight: 1 },
    { text: 'Alpha 和 Beta 2', source: 'local', weight: 1 },
  ];
  const result = rankPreferenceCandidates(inputs, { limit: 10 });
  const map = Object.fromEntries(result.map((item) => [item.keyword, item]));
  assert.equal(map['异环'].count, 3);
  assert.deepEqual(map['异环'].sources.sort(), ['favorites', 'history']);
  assert.ok(map['异环'].score > map['Alpha'].score, '多次出现 + 高权重的词应排前面');
  assert.equal(map['Alpha'].count, 2);
}

// ── 已有偏好排除：大小写与包含关系都算 ───────────────────────────────────
{
  const inputs = [
    { text: 'DeepSeek 插件', source: 'history', weight: 3 },
    { text: 'DeepSeek 教程', source: 'history', weight: 3 },
    { text: '蓝色大肥鱼 视频', source: 'history', weight: 3 },
    { text: '蓝色大肥鱼 合集', source: 'history', weight: 3 },
    { text: '猫咪 日常', source: 'history', weight: 3 },
    { text: '猫咪 合集', source: 'history', weight: 3 },
    { text: '猫咪 视频', source: 'history', weight: 3 },
  ];
  const result = keywords(rankPreferenceCandidates(inputs, { existing: ['DeepSeek', '蓝色大肥鱼'], limit: 20 }));
  assert.equal(result.some((word) => word.toLowerCase() === 'deepseek'), false, '已有偏好不应重复推荐');
  assert.equal(result.includes('大肥鱼'), false, '被已有长词覆盖的短词也不再推荐');
  assert.ok(result.includes('猫咪'), '不在已有列表里的词照常推荐');
}

// ── 数量上限与空输入 ──────────────────────────────────────────────────────
{
  const inputs = Array.from({ length: 40 }, (_, i) => ({ text: `关键词${String.fromCharCode(0x4e00 + i)}测试`, source: 'history', weight: 3 }));
  const result = rankPreferenceCandidates(inputs, { limit: 5 });
  assert.equal(result.length <= 5, true);
  assert.deepEqual(rankPreferenceCandidates([], { limit: 10 }), []);
}

// ── 抓取目标：主人口令没登录时不能偷偷抓鱼的账号 ──────────────────────────
{
  const previous = process.env.SURFCORE_OWNER_CREDENTIALS;
  process.env.SURFCORE_OWNER_CREDENTIALS = path.join(os.tmpdir(), `surfcore-no-owner-${Date.now()}.json`);
  try {
    const result = await scanPreferences({ target: 'owner', sources: ['history'], limit: 5 });
    assert.equal(result.target, 'owner');
    assert.equal(result.ownerLoginRequired, true, '主人没登录时应提示扫码');
    assert.equal(result.accounts.length, 0, '不能把鱼的账号当成主人');
    assert.ok(result.sources.some((item) => item.name === 'owner-credential' && item.ok === false));
  } finally {
    if (previous === undefined) delete process.env.SURFCORE_OWNER_CREDENTIALS;
    else process.env.SURFCORE_OWNER_CREDENTIALS = previous;
  }
}

console.log('OK test-pref-scan');
