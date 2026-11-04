// SurfCore QQ 会话过滤（D7）：DSH agentPreset 以 qq-chat 开头的会话不是真实 Agent。
//
// 契约：
// - presetOf 按 DSH 的权威顺序取 summary.agentPreset → session.header.agentPreset →
//   session.agentPreset → agent.agentPreset → agent.preset → agent.config.preset；
// - QQ 会话不参与忙/闲聚合（即使它随后又发 agent/status running），也不写任何
//   会话事件；只补一条带 agentPreset 的 session/meta 供桌宠侧识别；
// - 普通 Agent 的聚合与事件转发保持原样。
//
// 这里驱动真实的 apply() 注册器与写队列（不落盘、不起 DSH 宿主）。
import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const bridgeDir = path.resolve(here, "../integrations/dsh-pet-bridge");

let bridge;
let qq;
test.before(async () => {
  bridge = await import(pathToFileURL(path.join(bridgeDir, "index.js")).href);
  qq = bridge.__qqChatTest;
  assert.ok(qq, "bridge must export __qqChatTest");
});

function reset() {
  bridge.__instanceTest.resetQueue();
  qq.reset();
}

function makeAgent(id, session, name = "DSH") {
  const handlers = new Map();
  const agent = {
    id,
    session,
    name,
    ctx: {
      effect(fn) {
        return fn();
      },
      on(name_, fn) {
        handlers.set(name_, fn);
        return () => handlers.delete(name_);
      },
    },
  };
  return { agent, handlers };
}

function install(handlers) {
  bridge.apply({ on: (name, fn) => { handlers.set(name, fn); } });
}

function records() {
  return bridge.__instanceTest.queued().map((line) => JSON.parse(line));
}

test("presetOf follows DSH field authority and trims", () => {
  assert.equal(qq.presetOf({}, {}, { agentPreset: "qq-chat-v2" }), "qq-chat-v2",
    "summary 最新");
  assert.equal(
    qq.presetOf({ agentPreset: "agent" }, { header: { agentPreset: "header" } }, { agentPreset: "summary" }),
    "summary",
  );
  assert.equal(qq.presetOf({ agentPreset: "agent" }, { agentPreset: "session" }), "session");
  assert.equal(qq.presetOf({ agentPreset: "  standard  " }, {}), "standard", "首尾空白要去掉");
  assert.equal(qq.presetOf({ preset: "preset" }, {}), "preset");
  assert.equal(qq.presetOf({ config: { preset: "config" } }, {}), "config");
  assert.equal(qq.presetOf({}, {}), "");
});

test("isQqChatPreset only matches the qq-chat family", () => {
  assert.equal(qq.isQqChatPreset("qq-chat"), true);
  assert.equal(qq.isQqChatPreset("qq-chat-v2"), true);
  assert.equal(qq.isQqChatPreset("standard"), false);
  assert.equal(qq.isQqChatPreset("my-qq-chat"), false);
  assert.equal(qq.isQqChatPreset(""), false);
});

test("QQ agent never enters aggregate, never forwards events, still writes preset meta", () => {
  reset();
  const handlers = new Map();
  install(handlers);
  const onCreated = handlers.get("agent/created");
  const onSessionEvent = handlers.get("session/event");
  assert.equal(typeof onCreated, "function");
  assert.equal(typeof onSessionEvent, "function");
  bridge.__instanceTest.resetQueue();

  const real = makeAgent("a-real", { id: "s-real", header: { agentPreset: "standard" } }, "Real");
  onCreated({ agent: real.agent });
  real.handlers.get("agent/status")({ status: "running" });

  const chat = makeAgent("a-qq", { id: "s-qq", header: { agentPreset: "qq-chat-v2" } }, "QQ");
  onCreated({ agent: chat.agent });
  // preset 已知后，运行状态不得把 QQ agent 重新塞进聚合。
  chat.handlers.get("agent/status")({ status: "running" });
  onSessionEvent(chat.agent.session, { type: "tool/call", data: { name: "bash", callId: "q1" } });
  onSessionEvent(chat.agent.session, { type: "turn/end", data: { turn: 1, reason: { kind: "completed" } } });

  // 普通 Agent 收工：聚合必须能回到 idle（QQ 若还在聚合里就永远 working）。
  real.handlers.get("agent/status")({ status: "idle" });

  const rows = records();
  bridge.__instanceTest.resetQueue();

  assert.ok(qq.ignoredSessions.has("s-qq"), "QQ 会话必须进入忽略集合");
  assert.ok(!rows.some((r) => r.sessionId === "s-qq" && r.event === "tool/call"),
    "QQ 会话的工具事件不得落盘");
  assert.ok(!rows.some((r) => r.sessionId === "s-qq" && r.event === "turn/end"),
    "QQ 会话的回合事件不得落盘");
  const meta = rows.find((r) => r.type === "session/meta" && r.sessionId === "s-qq");
  assert.ok(meta, "QQ 会话仍需一条 session/meta 供桌宠识别");
  assert.equal(meta.agentPreset, "qq-chat-v2");
  assert.ok(!("text" in meta) && !("content" in meta), "meta 不写任何正文");

  const states = rows.filter((r) => r.state).map((r) => r.state);
  assert.deepEqual(states, ["working", "idle"], `聚合不得被 QQ 会话卡在忙: ${states}`);
});

test("metadata summary tags a live session as QQ and drops it from the aggregate", () => {
  reset();
  const handlers = new Map();
  install(handlers);
  const onCreated = handlers.get("agent/created");
  bridge.__instanceTest.resetQueue();

  const chat = makeAgent("a-qq2", { id: "s-late" }, "LateQQ");
  onCreated({ agent: chat.agent });
  chat.handlers.get("agent/status")({ status: "running" });
  assert.equal(bridge.__qqChatTest.agentStates.has(chat.agent), true, "preset 未知前按普通 agent 聚合");
  bridge.__instanceTest.resetQueue();

  // 与 refreshSessionMetadata 的 summary 通路同签名：summary.agentPreset 后到。
  qq.writeSessionMeta(chat.agent, chat.agent.session, { sessionId: "s-late", agentPreset: "qq-chat" });
  const rows = records();
  bridge.__instanceTest.resetQueue();

  assert.ok(qq.ignoredSessions.has("s-late"), "summary 发现 QQ preset 后必须登记忽略");
  assert.equal(qq.agentStates.has(chat.agent), false, "已聚合的 QQ agent 必须立刻移出");
  assert.equal(rows.filter((r) => r.state).at(-1)?.state, "idle",
    "移出后聚合应立即回 idle");
  const meta = rows.find((r) => r.type === "session/meta" && r.sessionId === "s-late");
  assert.equal(meta.agentPreset, "qq-chat");
});
