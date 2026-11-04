/**
 * 桌宠专注模式 → QQ 提示词的一行上下文（纯逻辑 + 一个只读文件入口）。
 *
 * 单一真相是 ~/.dsh/surfcore/pet/focus.json（插件 pet-chat.setFocus 写）：
 *   { enabled, phase: 'work'|'short_break'|'long_break'|'', endsAt: epoch ms }
 *
 * 隐私边界（用户决策 D11）：QQ 里的小肥鱼只知道「主人正在专注 / 在休息」和
 * 「大概什么时候结束」，**永远不知道主人在专注什么**。所以这里不读任何工作内容，
 * 也不接受调用方传入工作内容。
 */

import fs from 'node:fs';

const FOCUS_PHASES = new Set(['work', 'short_break', 'long_break']);

function normalizePhase(value) {
  const phase = String(value ?? '').trim();
  return FOCUS_PHASES.has(phase) ? phase : '';
}

function normalizeEndsAt(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.round(value));
  if (typeof value === 'string' && value.trim()) {
    const at = Date.parse(value);
    if (Number.isFinite(at)) return Math.max(0, Math.round(at));
  }
  return 0;
}

function emptyFocus() {
  return { enabled: false, phase: '', endsAt: 0 };
}

/** 读 focus.json；缺失 / 损坏 / 非法形状一律当「没开专注」，绝不抛异常。 */
export function readPetFocus(file) {
  let raw = null;
  try {
    const text = fs.readFileSync(file, 'utf8');
    if (!text.trim()) return emptyFocus();
    raw = JSON.parse(text);
  } catch {
    return emptyFocus();
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return emptyFocus();
  if (raw.enabled !== true) return emptyFocus();
  return {
    enabled: true,
    phase: normalizePhase(raw.phase),
    endsAt: normalizeEndsAt(raw.endsAt),
  };
}

function clockText(at) {
  const d = new Date(at);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * 生成 QQ 提示词里的「主人状态」一行；专注没开时返回空串（调用方直接不注入）。
 * endsAt 为 0 或已经过去时省略时间，避免说「预计 08:30 结束」但已经 09:00。
 */
export function focusContextLine(focus, now = Date.now()) {
  if (!focus || focus.enabled !== true) return '';
  const phase = normalizePhase(focus.phase);
  const endsAt = normalizeEndsAt(focus.endsAt);
  const endText = endsAt > 0 && endsAt > now ? clockText(endsAt) : '';

  if (phase === 'short_break' || phase === 'long_break') {
    return endText
      ? `【主人状态】主人在专注间隙休息，预计 ${endText} 回到专注`
      : '【主人状态】主人在专注间隙休息';
  }
  // work 或旧客户端没带 phase：都按「正在专注」说，只报结束时间，不打听内容。
  return endText
    ? `【主人状态】主人正在专注，预计 ${endText} 结束（不知道他在做什么，别打听）`
    : '【主人状态】主人正在专注（不知道他在做什么，别打听）';
}
