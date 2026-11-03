// 走真实 bridge.js 的语音路由：text → voxd（本地假服务）→ record 段 → 网关（假）。
// 不连真 QQ、不碰真实 config；用来证明「AI 说一句」这条链路在代码层是通的。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';

import { bridgeHarness } from './audit-bridge-harness.mjs';

function wav(seconds = 0.1, sr = 16000) {
  const n = Math.round(sr * seconds);
  const data = Buffer.alloc(n * 2);
  const h = Buffer.alloc(44);
  h.write('RIFF', 0, 'ascii');
  h.writeUInt32LE(36 + data.length, 4);
  h.write('WAVE', 8, 'ascii');
  h.write('fmt ', 12, 'ascii');
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22);
  h.writeUInt32LE(sr, 24);
  h.writeUInt32LE(sr * 2, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write('data', 36, 'ascii');
  h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

const seen = [];
const tts = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    seen.push(JSON.parse(body || '{}'));
    if (!req.url.startsWith('/v1/speak/file')) {
      res.writeHead(404).end();
      return;
    }
    const buf = wav();
    res.writeHead(200, { 'content-type': 'audio/wav', 'x-duration-ms': '1500' });
    res.end(buf);
  });
});
await new Promise((r) => tts.listen(0, '127.0.0.1', r));
const baseUrl = `http://127.0.0.1:${tts.address().port}`;

const h = await bridgeHarness({
  config: {
    allow: { groups: ['456'], private: ['123'] },
    socialV2: {
      mode: 'reserved2',
      voice: {
        enabled: true,
        maxPerMinute: 5,
        tts: {
          enabled: true,
          // 桥接解析顺序是 endpoints[route] > endpoints[默认 route] > baseUrl；
          // 只给 baseUrl 会被默认 127.0.0.1:8765 覆盖（本机只跑云端 8767 时直接 fetch failed）。
          baseUrl,
          route: 'local',
          endpoints: { local: baseUrl, cloud: baseUrl },
          maxChars: 20,
          character: 'huayan'
        }
      },
      tools: { sendVoice: true }
    }
  }
});

try {
  // ① text → 合成 → 本地 wav
  const r = await h.synthesizeVoiceText('来了来了', {});
  assert.ok(fs.existsSync(r.path), '应该落成本地文件');
  assert.equal(r.via, 'tts');
  assert.equal(fs.readFileSync(r.path).subarray(0, 4).toString(), 'RIFF', '必须是 wav');
  assert.ok(seen.length, '应该请求 TTS 服务');
  assert.equal(seen[0].text, '来了来了');
  assert.equal(seen[0].format, 'wav');
  assert.equal(seen[0].character, 'huayan', 'character 应该来自 voice.tts.character');

  // ② 发出去的是 record 段，不是文本
  const sent = await h.sendVoiceForV2('group:456', null, { resolved: r, verify: false });
  assert.equal(sent.key, 'group:456');
  const onebot = h.calls.http.filter((c) => c.url.endsWith('send_group_msg')).pop();
  assert.ok(onebot, '应该调用 send_group_msg');
  assert.equal(onebot.body.message[0].type, 'record');
  assert.equal(onebot.body.group_id, 456);

  // ③ 超长：给可读错误，而不是让模型猜
  await assert.rejects(() => h.synthesizeVoiceText('字'.repeat(30), {}), /最多 20 字/);

  console.log('test-voice-route: ok');
} finally {
  await h.close();
  await new Promise((r) => tts.close(r));
}
