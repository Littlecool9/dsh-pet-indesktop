// dev 通道发布链路（2026-11-01 用户定）：设计契约测试，不联网、不发版。
// SurfCore 的自更新已随本仓库并入 desktop-pet 下线，这里只保留发布/版本规则。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const read = (p) => fs.readFileSync(path.resolve(p), 'utf8');
const publishDev = read('scripts/publish-dev.mjs');
const version = read('scripts/version.mjs');

// 1) 版本规则：dev 版本合法、且比较上低于同号正式版
assert.ok(/\(rc\|beta\|alpha\|dev\)/.test(version), 'version.mjs 允许 -dev.N 版本');
assert.ok(version.includes("split('-')"), '版本比较要分开处理预发布后缀');

// 2) 发布脚本：只发 dev、只发 Pre-release、不碰 main
assert.ok(publishDev.includes("rev-parse', '--abbrev-ref', 'HEAD') !== 'dev'"), '只允许在 dev 分支发布');
assert.ok(publishDev.includes('prerelease: true'), '发布为 Pre-release');
assert.ok(publishDev.includes('refs/heads/dev'), '推 dev 分支（tag 需要可达 commit）');
assert.ok(!/PATCH', `\/repos\/\$\{repoArg\}\/git\/refs\/heads\/main/.test(publishDev), '发布 dev 不得改 main');
assert.ok(publishDev.includes('verify-ref') && publishDev.includes('问题 0 个'), 'dev 构建也要过清单门禁');

console.log('\n✅ dev 通道发布链路通过');
