// 设置页状态声明守卫：client.js 里每个被调用的 setXxx(...) 都必须有对应的声明
// （`const [xxx, setXxx] = useState(...)`、`const setXxx = ...` 或 `function setXxx`）。
//
// 2026-11-04 事故：删除自更新时连带删掉了 OverviewTab 里 gateData / compat / snowImport 等
// 状态声明，`node --check` 照样通过，但设置页一渲染就抛 ReferenceError，整个 SurfCore 设置页空白。
// 没有 JS 解析器依赖，这里用正则做保守检查：只管「调用了 setter 却找不到声明」这一类。
import fs from 'node:fs';
import path from 'node:path';

const file = process.argv[2] || path.join(import.meta.dirname, '..', 'lib', 'client.js');
const src = fs.readFileSync(file, 'utf8');

// 浏览器全局函数，不是组件状态。
const declared = new Set(['setTimeout', 'setInterval', 'setImmediate']);
for (const m of src.matchAll(/\[\s*[A-Za-z_$][\w$]*\s*,\s*(set[A-Z][\w$]*)\s*\]\s*=/g)) declared.add(m[1]);
for (const m of src.matchAll(/\b(?:const|let|var)\s+(set[A-Z][\w$]*)\s*=/g)) declared.add(m[1]);
for (const m of src.matchAll(/\bfunction\s+(set[A-Z][\w$]*)\s*\(/g)) declared.add(m[1]);
// 解构参数 / 形参里的 setter（如 `function QQTab({ set, setAdmin })`）也算声明。
for (const m of src.matchAll(/\(\s*\{([^}]*)\}\s*\)/g)) {
  for (const n of m[1].matchAll(/\b(set[A-Z][\w$]*)\b/g)) declared.add(n[1]);
}

const called = new Map();
for (const m of src.matchAll(/(?<![\w$.])(set[A-Z][\w$]*)\s*\(/g)) {
  const line = src.slice(0, m.index).split('\n').length;
  if (!called.has(m[1])) called.set(m[1], line);
}

const missing = [...called].filter(([name]) => !declared.has(name));
if (missing.length) {
  console.error('❌ 调用了 setter 却找不到声明（设置页渲染会抛 ReferenceError，整页空白）：');
  for (const [name, line] of missing) console.error(`   ${name}（首次调用在第 ${line} 行）`);
  process.exit(1);
}
console.log(`✅ client.js 状态声明完整：${called.size} 个 setter 均有声明`);
