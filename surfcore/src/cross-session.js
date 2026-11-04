/**
 * 跨会话发送 / 可达会话列表的纯逻辑（2026-11-04）。
 *
 * 背景：reserved2 的每个会话各有自己的 agentToken，发送端点原先要求
 * 「令牌必须属于目标 key」。主人希望她在私聊里说「把那个故事也发到群里」时
 * 真的能发出去，所以发送侧改为：只要能证明这是**任意一个活跃二代会话**的令牌，
 * 就允许跨会话发送；读取端点仍然严格绑定本会话（见 bridge.js 的 x-agent-call 关卡）。
 *
 * 本模块不碰 IO、不读配置以外的全局状态，桥接和单测共用同一套判定，
 * 避免 16k 行的 bridge.js 里每个发送端点各写一份。
 */

/** 归一化会话 key：group:007 → group:7；格式不对返回 ''。 */
export function canonicalConversationKey(key) {
  const m = /^(group|private):(\d+)$/.exec(String(key ?? '').trim());
  if (!m) return '';
  const id = Number(m[2]);
  return Number.isSafeInteger(id) && id > 0 ? `${m[1]}:${id}` : '';
}

/** 配置开关默认开；只有显式 false 才关闭。 */
export function crossSessionEnabled(cfg) {
  return cfg?.socialV2?.crossSession?.enabled !== false;
}

/**
 * 找出令牌属于哪个会话。
 * @param {Iterable<[string, {agentToken?: string}]>} conversations
 * @param {string} token
 * @param {(a: string, b: string) => boolean} [eq] 桥接传入定长比较；单测可省略。
 * @returns {string} 会话 key；找不到返回 ''。
 */
export function findLiveTokenKey(conversations, token, eq) {
  if (typeof token !== 'string' || !token) return '';
  const compare = typeof eq === 'function' ? eq : (a, b) => a === b;
  for (const [key, st] of conversations || []) {
    if (!st?.agentToken) continue;
    if (!compare(token, st.agentToken)) continue;
    return canonicalConversationKey(key) || String(key);
  }
  return '';
}

/**
 * 发送端点的令牌判定。
 * @returns {{allowed:boolean, reason:string, sourceKey:string, crossSession:boolean}}
 *   sourceKey 是令牌所属会话（D3 的额度记账对象）；crossSession=true 表示目标不是它。
 */
export function resolveSendToken({ targetKey, token, conversations, cfg, eq } = {}) {
  const target = canonicalConversationKey(targetKey) || String(targetKey ?? '').trim();
  if (!target) return { allowed: false, reason: 'bad-target', sourceKey: '', crossSession: false };
  if (typeof token !== 'string' || !token) {
    return { allowed: false, reason: 'missing-token', sourceKey: '', crossSession: false };
  }
  const sourceKey = findLiveTokenKey(conversations, token, eq);
  if (!sourceKey) return { allowed: false, reason: 'invalid-token', sourceKey: '', crossSession: false };
  if (sourceKey === target) {
    return { allowed: true, reason: 'same-conversation', sourceKey, crossSession: false };
  }
  // 跨会话只在开关开着时放行；关掉后回退到原来的「令牌必须属于目标」。
  if (!crossSessionEnabled(cfg)) {
    return { allowed: false, reason: 'cross-session-disabled', sourceKey, crossSession: false };
  }
  return { allowed: true, reason: 'cross-session', sourceKey, crossSession: true };
}

/** 群名/私聊名是模型可见文本：压成单行、去掉控制字符、限长。 */
export function sanitizeTargetName(name, max = 24) {
  const limit = Math.max(1, Math.min(60, Math.round(Number(max) || 24)));
  return String(name ?? '')
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit);
}

/**
 * 唤醒提示 / qq_get_prompt 里能列出的跨会话目标。
 *
 * 只列白名单群 + 主人私聊，最多 12 条（D4）；不列任何令牌。
 * @param {{cfg:object, groupName?:(gid:string)=>string, isAllowed?:(key:string,kind:string,id:number)=>boolean, max?:number}} opts
 */
export function reachableTargets({ cfg, groupName, isAllowed, max = 12 } = {}) {
  const limit = Math.max(0, Math.min(12, Math.round(Number(max) || 12)));
  if (!limit) return [];
  const allowGroups = Array.isArray(cfg?.allow?.groups)
    ? cfg.allow.groups
    : (Array.isArray(cfg?.allow?.group) ? cfg.allow.group : []);
  const denyGroups = new Set((cfg?.deny?.groups ?? cfg?.deny?.group ?? []).map(String));
  const denyPrivate = new Set((cfg?.deny?.private ?? cfg?.deny?.privates ?? []).map(String));
  const allowed = typeof isAllowed === 'function' ? isAllowed : () => true;
  const out = [];
  const push = (entry) => {
    if (out.length >= limit) return;
    if (out.some((item) => item.key === entry.key)) return;
    out.push(entry);
  };
  const ownerQQ = String(cfg?.ownerQQ ?? '').trim();
  if (/^\d+$/.test(ownerQQ) && !denyPrivate.has(ownerQQ)) {
    const key = `private:${Number(ownerQQ)}`;
    if (allowed(key, 'private', Number(ownerQQ))) {
      push({ key, kind: 'private', name: sanitizeTargetName('主人私聊') });
    }
  }
  for (const raw of allowGroups) {
    if (out.length >= limit) break;
    const id = String(raw ?? '').trim().replace(/^group:/i, '');
    if (!/^\d+$/.test(id) || denyGroups.has(id)) continue;
    const key = `group:${Number(id)}`;
    if (!allowed(key, 'group', Number(id))) continue;
    const name = sanitizeTargetName(typeof groupName === 'function' ? groupName(id) : '');
    push({ key, kind: 'group', name });
  }
  return out;
}
