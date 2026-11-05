// 记忆卡「接线」静态回归：核心模块单测通过，不代表桥接/调度器/控制台真的用上了它。
// 这里只读源码断言关键接线，不启动服务、不写真实数据。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

const bridge = read('src/bridge.js');
const scheduler = read('plugins/surfcore/lib/scheduler.js');
const index = read('plugins/surfcore/lib/index.js');
const client = read('plugins/surfcore/lib/client.js');
const paths = read('plugins/surfcore/lib/paths.js');
const store = read('plugins/surfcore/lib/store.js');

// 1) 桥接：消息进来写 inbox；QQ 提示词两条路径都注入记忆卡；有容量告警私聊端点。
assert.match(bridge, /appendMemoryInboxEvent\(MEMORY_CARD_PATHS/, '桥接没有把消息写入记忆卡 inbox');
assert.match(bridge, /recordMemoryInboxEvent\(\{ key, kind, event, plainContent, textContent, isOwner, quoteTargetIsSelf \}\)/, '桥接没有在 handleIncoming 里记录记忆');
assert.match(bridge, /recordSelfMemoryEvent\(key, sent\.join\('\\n'\)\)/, 'v2 发送没有记录她自己的发言');
assert.match(bridge, /recordSelfMemoryEvent\(key, text\)/, 'v1 发送没有记录她自己的发言');
assert.match(bridge, /isSelf: true/, '桥接 inbox 自发言没有 isSelf 标记');
assert.match(bridge, /const memoryBlock = memoryCardPromptBlock\(/, 'v1/chat 角色提示没有注入记忆卡');
assert.match(bridge, /const memoryCardText = memoryCardPromptBlock\(/, 'v2 唤醒提示没有注入记忆卡');
assert.match(bridge, /\/api\/memory-card\/notify/, '桥接缺少记忆卡容量告警端点');
assert.match(bridge, /memoryCard: memoryCardPromptBlock\(/, 'qq_get_prompt 没有返回记忆卡');

// 2) B站 调度器：每次醒来的统一上下文里有记忆卡（仅 B站 公开 scope）。
assert.match(scheduler, /memoryCardPromptBlock\('bili'\)/, 'B站调度器没有注入记忆卡');
assert.match(scheduler, /memoryCardBlockForBili\(\)/, 'B站记忆卡块没有接进 identityContextLines');

// 3) 插件：定时维护 + 控制台 API + 生命周期清理。
assert.match(index, /startMemoryCardTimer\(\{ log: pluginLog, callBridge \}\)/, '插件没有启动记忆卡定时维护');
assert.match(index, /\/memory-card/, '插件缺少记忆卡 API 路由');
assert.match(index, /handleMemoryCard/, '插件缺少记忆卡处理器');
assert.match(index, /memoryCard: memoryCardStatusNow\(\)/, '概览没有记忆卡状态');
assert.match(index, /memoryCardTimer\?\.stop/, '插件销毁时没有停记忆卡定时器');

// 4) 控制台：容量条 / 弹窗 / 规则面板。
assert.match(client, /function MemoryCardPanel/, '控制台缺少记忆卡面板');
assert.match(client, /qbw-modal-backdrop/, '控制台缺少容量弹窗');
assert.match(client, /记忆卡快满了/, '弹窗文案缺失');
assert.match(client, /压缩到 80%/, '控制台缺少压缩按钮');

// 5) 路径与默认配置：QQ/B站 注入块是文件契约，默认值与核心模块同源。
assert.match(paths, /MEMORY_CARD_PROMPT_QQ/, 'paths.js 缺少 QQ 注入块路径');
assert.match(paths, /MEMORY_CARD_PROMPT_BILI/, 'paths.js 缺少 B站 注入块路径');
assert.match(paths, /MEMORY_CARD_FULL_JSONL/, 'paths.js 缺少全量卡 JSONL 路径');
assert.match(paths, /MEMORY_CARD_FULL_STATS/, 'paths.js 缺少全量卡 stats 路径');
assert.match(store, /DEFAULT_MEMORY_CARD_CONFIG/, '合体层默认配置没有引用记忆卡默认值');

// 5b) 全量卡只存档：桥接/调度器**不能**读它，否则「平时只加载衰减卡」就失效了。
assert.equal(bridge.includes('MEMORY_CARD_FULL'), false, '桥接不应读取全量卡');
assert.equal(scheduler.includes('MEMORY_CARD_FULL'), false, 'B站调度器不应读取全量卡');
assert.match(index, /\/memory-card\/full/, '插件缺少全量卡只读路由');
assert.match(index, /fullMemoryCardSnapshot/, '插件缺少全量卡快照');
assert.match(client, /function FullMemoryCardPanel/, '控制台缺少全量记忆卡面板');
assert.match(client, /当前提示词加载：/, '控制台没有明确标出当前加载的是哪张卡');
assert.match(client, /全量记忆卡（只存档）/, '控制台没有全量卡标识');
assert.match(client, /衰减卡字数上限/, '控制台没有衰减卡字数上限输入（用户可改）');
assert.match(client, /全量卡上限（GB）/, '控制台没有全量卡 GB 上限输入');
assert.match(client, /设为初次相遇/, '控制台没有“设为初次相遇”入口');
assert.match(client, /合并为一个事件/, '控制台没有“合并为一个事件”入口');
assert.match(client, /合并后置顶/, '控制台没有合并后置顶选项');
assert.match(index, /merge-memories/, '插件动作白名单没有 merge-memories');
assert.match(client, /初次相遇：/, '控制台没有显示当前初次相遇');
assert.match(index, /set-first-meet/, '插件动作白名单没有 set-first-meet');
assert.match(client, /最初/, '控制台没有「最初」说明/标记');

// 6) 真实 bridge.js（VM fixture）：注入块能读、主人消息能进 inbox、不会写真实 ~/.dsh。
const { bridgeHarness } = await import('./audit-bridge-harness.mjs');
const harness = await bridgeHarness({ config: { ownerQQ: 123, allow: { private: ['123'], groups: ['456'] } } });
try {
  const memoryDir = path.join(harness.temp, 'dsh', 'surfcore', 'memory');
  fs.mkdirSync(memoryDir, { recursive: true });
  fs.writeFileSync(path.join(memoryDir, 'memory-card-prompt-qq.md'), '【测试记忆卡】主人第一次对角色说话，要永远记得。');
  assert.match(harness.memoryCardPromptBlock(), /测试记忆卡/, '桥接没有读到记忆卡注入块');
  assert.match(harness.currentRoleHint(), /测试记忆卡/, 'v1/chat 角色提示没有拼上记忆卡');

  // 按会话 map：具体群块优先；没有自己记录的群回退到 group:*；没有 group:* 时保持旧隔离（空）。
  const groupMapPath = path.join(memoryDir, 'memory-card-prompt-qq-groups.json');
  fs.writeFileSync(groupMapPath, JSON.stringify({
    version: 1,
    blocks: {
      'group:*': '【默认群记忆】私聊·主人：私下说过的事',
      'group:456': '【456自己的记忆】',
      'private:*': '【默认私聊记忆】群聊·A群 / group:111：群里说过的事',
      'private:123': '【123自己的私聊记忆】',
    },
  }));
  assert.match(harness.memoryCardPromptBlock('group:456'), /456自己的记忆/, '具体群块应优先');
  assert.match(harness.memoryCardPromptBlock('group:444'), /默认群记忆/, '没有自己记录的群应回退到 group:*');
  assert.match(harness.memoryCardPromptBlock('group:444'), /私聊/, '默认块里应有私聊记录');
  assert.match(harness.memoryCardPromptBlock('private:123'), /123自己的私聊记忆/, '具体私聊块应优先');
  assert.match(harness.memoryCardPromptBlock('private:888'), /默认私聊记忆/, '没有自己记录的私聊应回退到 private:*');
  assert.match(harness.memoryCardPromptBlock('private:888'), /群聊/, '默认私聊块里应有群聊记录');
  fs.writeFileSync(groupMapPath, JSON.stringify({ version: 1, blocks: { 'group:456': '【456自己的记忆】' } }));
  assert.equal(harness.memoryCardPromptBlock('group:444'), '', '没有 group:* 时保持旧隔离（空块）');
  assert.equal(harness.memoryCardPromptBlock('private:888'), '', '没有 private:* 时保持旧隔离（空块）');
  harness.recordMemoryInboxEvent({
    key: 'private:123',
    kind: 'private',
    event: { user_id: '123', sender: { nickname: '主人' }, self_id: '999' },
    plainContent: '今天想你了',
    textContent: '今天想你了',
    isOwner: true,
    quoteTargetIsSelf: false,
  });
  harness.recordSelfMemoryEvent('private:123', '测试她的回复');
  const inboxLines = fs.readFileSync(path.join(memoryDir, 'memory-inbox.jsonl'), 'utf8').trim().split('\n');
  assert.equal(inboxLines.length, 2, '主人消息 + 她自己的发言没有都写进 fixture inbox');
  assert.match(inboxLines[0], /今天想你了/);
  assert.match(inboxLines[1], /测试她的回复/);
  assert.match(inboxLines[1], /"isSelf":true/);
  assert.equal(inboxLines[0].includes('sk-'), false);
} finally {
  await harness.close();
}

console.log('memory-card wiring: OK');
