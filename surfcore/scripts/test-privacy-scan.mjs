// 隐私扫描判据的回归（纯函数，不读仓库、不联网）。
//
// 存在的理由（2026-10-26）：默认规则里有几条写了 `flags: ''`，扫描器当时用
// `new RegExp(pattern, rule.flags ?? 'g')` —— 空串不会 fallback，于是**没有 global**：
//   · 每条规则每个文件只看到**第一个**命中（漏报，fail-open）；
//   · 循环空转到迭代上限，被误报成"扫描不完整"。
// 结果就是发布闸长期报"0 命中"，而 docs 里躺着真的跟踪链接。
// 下面第 2 组断言专门钉这个行为：同一段文本里的**第二个**命中必须能看到。
import assert from 'node:assert/strict';
import { compileDenyRegex, isNoise } from './privacy-rules-lib.mjs';

let failures = 0;
const ok = (cond, label) => {
  if (cond) console.log(`✅ ${label}`);
  else { failures += 1; console.error(`❌ ${label}`); }
};

console.log('## 1. 编译出来的一定是全局正则');
{
  const a = compileDenyRegex({ pattern: 'foo', flags: '' });
  ok(a.global === true, 'flags 为空串 → 自动补 g');
  const b = compileDenyRegex({ pattern: 'foo' });
  ok(b.global === true, 'flags 缺失 → 自动补 g');
  const c = compileDenyRegex({ pattern: 'foo', flags: 'i' });
  ok(c.global === true && c.ignoreCase === true, 'flags 只有 i → 变成 gi（i 不丢）');
  const d = compileDenyRegex({ pattern: 'foo', flags: 'gi' });
  ok(d.flags === 'gi', '已有 g → 不重复追加');
  let threw = false;
  try { compileDenyRegex({ pattern: '' }); } catch { threw = true; }
  ok(threw, '空 pattern 抛错（不静默放行）');
}

console.log('## 2. 同一段文本里的第二个命中必须能看到（原 bug 的正面回归）');
{
  const text = 'firstTokenAAA111 and secondTokenBBB222';
  const re = compileDenyRegex({ pattern: '[A-Za-z]+[A-Za-z0-9]*', flags: '' });
  const found = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    found.push(m[0]);
    if (m.index === re.lastIndex) re.lastIndex += 1;
  }
  ok(found.length >= 2 && found[0] !== found[1], `至少拿到两个不同命中（实得 ${found.length}：${found.slice(0, 2).join(', ')}）`);

  // 非全局正则的对照：确实只会拿到同一个匹配（说明这条断言不是空转）
  const bad = new RegExp('[A-Za-z]+[A-Za-z0-9]*', '');
  const a = bad.exec(text)?.[0];
  const b = bad.exec(text)?.[0];
  ok(a === b, '（对照）非全局正则连续 exec 拿到的是同一个匹配 —— 这正是当初漏报的机制');
}

console.log('## 3. 噪音过滤');
{
  const rule = { requireNonHex: true };
  ok(isNoise('dea3ce8c408a0e1f2b3c4d5e6f7a8b9c', rule), '全 hex 长串（commit SHA）→ 噪音');
  ok(isNoise('PLAYWRIGHT_MODULE_PATH', {}), '环境变量名 → 噪音');
  ok(isNoise('bridge.js.bak-20260821-1722', {}), '文件名/路径片段 → 噪音');
  ok(isNoise('config-before-deny-users-2026-10-23T02-37-58-256Z', {}), '备份文件名（ISO 时间戳尾巴）→ 噪音');
  ok(!isNoise('3DhRVW5Ol4GrZw4vFB6t2Z2ueEDrYVVa64XoO8tOebS', {}), '混合大小写+数字+符号的真高熵串 → 不当作噪音');
  ok(isNoise('', {}), '空串 → 噪音（不产生空命中报告）');
}

console.log(failures === 0 ? '\n✅ 隐私扫描判据通过' : `\n❌ ${failures} 项失败`);
process.exit(failures === 0 ? 0 : 1);
