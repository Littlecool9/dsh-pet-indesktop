/**
 * 桌宠专注 → QQ 提示词上下文：纯函数 + 接线源码检查。
 *
 * 这里不启动桥接（bridge.js 有网络/定时器副作用），只钉住两件容易悄悄坏掉的事：
 *   1. focusContextLine 只说「专注/休息 + 结束时间」，不在时间无效时乱报；
 *   2. bridge.js 的 withSlangContext 真的把这一行接在【当前时间】后面，
 *      且目的 tick 判定前真的把磁盘上的 countToday/lastSentAt 合并进内存。
 *
 * 运行：node scripts/test-pet-focus-context.mjs
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { focusContextLine, readPetFocus } from '../src/pet-focus-context.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const bridgeSource = fs.readFileSync(path.join(here, '..', 'src', 'bridge.js'), 'utf8');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pet-focus-context-'));

function pad(n) { return String(n).padStart(2, '0'); }
function clock(at) {
  const d = new Date(at);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function writeFocus(value) {
  const file = path.join(tmp, 'focus.json');
  fs.writeFileSync(file, typeof value === 'string' ? value : JSON.stringify(value));
  return file;
}

try {
  // ── readPetFocus ───────────────────────────────────────────────────────
  assert.deepEqual(readPetFocus(path.join(tmp, 'missing.json')), { enabled: false, phase: '', endsAt: 0 }, '文件不存在 → 关闭');
  assert.deepEqual(readPetFocus(writeFocus('{oops')), { enabled: false, phase: '', endsAt: 0 }, '坏 JSON → 关闭');
  assert.deepEqual(readPetFocus(writeFocus({ enabled: false, phase: 'work', endsAt: 1700000000000 })), { enabled: false, phase: '', endsAt: 0 }, 'enabled=false 不带阶段');
  assert.deepEqual(readPetFocus(writeFocus({ enabled: true, phase: 'dance', endsAt: 1700000000000 })), { enabled: true, phase: '', endsAt: 1700000000000 }, '未知 phase 归一成空');
  assert.deepEqual(readPetFocus(writeFocus({ enabled: true, phase: 'short_break', endsAt: '2026-11-04T10:00:00.000Z' })), {
    enabled: true,
    phase: 'short_break',
    endsAt: Date.parse('2026-11-04T10:00:00.000Z'),
  }, 'endsAt 接受 ISO 字符串并归一成毫秒');
  assert.deepEqual(readPetFocus(writeFocus({ enabled: true, phase: 'work', endsAt: -5 })), { enabled: true, phase: 'work', endsAt: 0 }, '负数 endsAt → 0');

  // ── focusContextLine ───────────────────────────────────────────────────
  const now = Date.parse('2026-11-04T06:30:00.000Z'); // 本地时区由机器决定，下面用同一个 Date 算 HH:MM
  const future = Date.parse('2026-11-04T07:30:00.000Z');
  const futureClock = clock(future);

  assert.equal(focusContextLine({ enabled: false, phase: 'work', endsAt: future }, now), '', '专注关 → 不注入');
  assert.equal(focusContextLine(null, now), '', '没有 focus 对象 → 不注入');

  const work = focusContextLine({ enabled: true, phase: 'work', endsAt: future }, now);
  assert.ok(work.includes('【主人状态】'), '带【主人状态】前缀');
  assert.ok(work.includes('主人正在专注'), 'work 说明正在专注');
  assert.ok(work.includes(futureClock), `work 带本地结束时间 ${futureClock}`);
  assert.ok(work.includes('别打听'), '明确不许打听工作内容');
  assert.ok(!work.includes('工作内容') && !work.includes('在做什么具体'), '不包含任何工作内容占位');

  const workNoTime = focusContextLine({ enabled: true, phase: 'work', endsAt: 0 }, now);
  assert.ok(workNoTime.includes('主人正在专注') && !workNoTime.includes('预计'), 'endsAt=0 时省略预计时间');
  const workPast = focusContextLine({ enabled: true, phase: 'work', endsAt: now - 1000 }, now);
  assert.ok(!workPast.includes('预计'), '结束时间已过时省略预计时间');

  const shortBreak = focusContextLine({ enabled: true, phase: 'short_break', endsAt: future }, now);
  assert.ok(shortBreak.includes('专注间隙休息'), 'short_break 说明在休息');
  assert.ok(shortBreak.includes(futureClock) && shortBreak.includes('回到专注'), 'short_break 带回到专注时间');
  assert.ok(!shortBreak.includes('正在专注'), '休息阶段不能冒充正在专注');

  const longBreak = focusContextLine({ enabled: true, phase: 'long_break', endsAt: 0 }, now);
  assert.ok(longBreak.includes('专注间隙休息') && !longBreak.includes('预计'), 'long_break 无结束时间时省略时间');

  const unknownPhase = focusContextLine({ enabled: true, phase: '', endsAt: future }, now);
  assert.ok(unknownPhase.includes('主人正在专注'), 'enabled 但没 phase → 仍按正在专注处理');

  // ── 源码接线：withSlangContext + 目的计数合并 ───────────────────────────
  assert.ok(bridgeSource.includes("from './pet-focus-context.js'"), 'bridge.js 必须 import 专注上下文模块');
  assert.ok(/function\s+petFocusEnabled\s*\([^)]*\)\s*\{\s*return\s+readPetFocusCached\(\)\.enabled\s*===\s*true;/.test(bridgeSource),
    'petFocusEnabled 复用 readPetFocus 的 10 秒缓存（不再自己解析 focus.json）');

  const slangStart = bridgeSource.indexOf('function withSlangContext');
  assert.ok(slangStart > 0, '找到 withSlangContext');
  const slangBody = bridgeSource.slice(slangStart, bridgeSource.indexOf('\n  function ', slangStart + 10));
  const focusIdx = slangBody.indexOf('focusContextLine');
  const slangBlockIdx = slangBody.indexOf('buildSlangContext');
  assert.ok(focusIdx > 0, 'withSlangContext 调用 focusContextLine');
  assert.ok(slangBlockIdx > focusIdx, '专注行必须排在黑话块之前（紧跟【当前时间】）');
  assert.ok(slangBody.indexOf('timeLine') < focusIdx, '专注行排在时间行之后');

  const mergeStart = bridgeSource.indexOf('function mergePurposeCountersFromDisk');
  assert.ok(mergeStart > 0, '找到目的计数合并函数');
  const mergeBody = bridgeSource.slice(mergeStart, bridgeSource.indexOf('\n  function ', mergeStart + 10));
  assert.ok(/Math\.max\([^)]*countToday/.test(mergeBody), '合并 countToday 取 max');
  assert.ok(/Math\.max\([^)]*lastSentAt/.test(mergeBody), '合并 lastSentAt 取 max');
  assert.ok(mergeBody.includes('ensurePurposeDay'), '合并前按当天归零');

  const runStart = bridgeSource.indexOf('async function runPurposeOnce');
  const runBody = bridgeSource.slice(runStart, bridgeSource.indexOf('async function runPurpose(', runStart));
  const mergeCallIdx = runBody.indexOf('mergePurposeCountersFromDisk()');
  const evaluateIdx = runBody.indexOf('evaluatePurposeTick({');
  assert.ok(mergeCallIdx > 0, 'runPurposeOnce 调用 mergePurposeCountersFromDisk');
  assert.ok(evaluateIdx > mergeCallIdx, '合并必须发生在目的 tick 判定之前');

  console.log('pet-focus-context tests OK');
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
