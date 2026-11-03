#!/usr/bin/env node
/**
 * 自检：把"能不能装、装到哪一步"写成一份 诊断报告.txt，方便对方直接发回来。
 * 不修改任何东西；不读取 config.json 里的令牌明文（只报"有/没有"）。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const TARGET = path.join(HERE, 'surfcore');
const lines = [];
const add = (s = '') => lines.push(s);

function run(cmd, args, opts = {}) {
  try {
    const r = spawnSync(cmd, args, { encoding: 'utf8', windowsHide: true, shell: process.platform === 'win32', timeout: 20000, ...opts });
    return `${r.stdout ?? ''}${r.stderr ?? ''}`.trim();
  } catch (e) { return `(执行失败: ${e.message})`; }
}

add('=== SurfCore 诊断报告 ===');
add(`生成时间：${new Date().toLocaleString('zh-CN')}`);
add(`系统：${os.platform()} ${os.release()} (${os.arch()})`);
add(`Node：v${process.versions.node}`);
add(`DSH_HOME：${DSH_HOME}`);
add(`安装目录：${TARGET}`);

// 1) DSH
add('\n--- DSH ---');
const profilesDir = path.join(DSH_HOME, 'profiles');
let profiles = [];
try { profiles = fs.readdirSync(profilesDir).filter((n) => !n.includes('.') && fs.existsSync(path.join(profilesDir, n, 'package.json'))); } catch {}
add(`profiles：${profiles.length ? profiles.join('、') : '(没有找到)'}`);
for (const p of profiles) {
  const pkgFile = path.join(profilesDir, p, 'package.json');
  let bundles = [];
  try { bundles = JSON.parse(fs.readFileSync(pkgFile, 'utf8'))?.dsh?.profile?.bundles ?? []; } catch {}
  const hasSurfcore = bundles.includes('surfcore');
  const patch = path.join(profilesDir, p, 'cordis.patch.yml');
  const patchHit = fs.existsSync(patch) && /surfcore|mcp-snowluma/.test(fs.readFileSync(patch, 'utf8'));
  add(`  ${p}: bundle=${hasSurfcore ? 'surfcore' : '(无)'} / patch=${patchHit ? '有' : '无'}`);
}

// 2) SnowLuma
add('\n--- SnowLuma ---');
const ports = (run('powershell', ['-NoProfile', '-Command',
  "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 3000,3001,3010,3011 } | Select-Object -ExpandProperty LocalPort"]).match(/\d+/g) ?? []);
add(`监听端口：${ports.length ? ports.join('、') : '(没有：SnowLuma 没开或没登录)'}`);
try {
  const files = fs.readdirSync(path.join(HERE, 'surfcore'), { recursive: false }).filter((n) => /^onebot_\d+\.json$/.test(n));
  add(`onebot token 文件：${files.length ? files.join('、') : '(安装目录里没有，正常)'}`);
} catch {}
try {
  const homes = fs.readdirSync(os.homedir()).filter((n) => /^SnowLuma/i.test(n));
  add(`SnowLuma 安装目录：${homes.length ? homes.join('、') : '(家目录没找到，可能装在别处)'}`);
} catch {}

// 3) 依赖
add('\n--- 依赖 ---');
const nm = path.join(TARGET, 'node_modules');
add(`node_modules：${fs.existsSync(nm) ? `存在（${fs.readdirSync(nm).length} 项）` : '不存在'}`);
add(`express：${fs.existsSync(path.join(nm, 'express')) ? '有' : '没有'}`);
add(`@snowluma/sdk：${fs.existsSync(path.join(nm, '@snowluma', 'sdk')) ? '有' : '没有'}`);

// 4) 配置
add('\n--- 配置 ---');
const cfgFile = path.join(TARGET, 'config.json');
if (fs.existsSync(cfgFile)) {
  try {
    const c = JSON.parse(fs.readFileSync(cfgFile, 'utf8'));
    add(`config.json：存在（版本 ${c.version ?? '?'}）`);
    add(`ownerQQ：${c.ownerQQ ? '已设置' : '未设置'}`);
    add(`白名单群：${(c.allow?.groups ?? []).length} 个`);
    add(`白名单私聊：${(c.allow?.private ?? []).length} 个`);
    add(`snowluma.httpUrl：${c.snowluma?.httpUrl ?? '(空)'}`);
    add(`snowluma.wsUrl：${c.snowluma?.wsUrl ?? '(空)'}`);
    add(`snowluma.token：${c.snowluma?.accessToken ? '已填' : '未填'}`);
    add(`consoleToken：${c.consoleToken ? '已生成' : '未生成'}`);
  } catch (e) { add(`config.json：存在但解析失败（${e.message}）`); }
} else add('config.json：不存在');

// 5) 插件日志
add('\n--- 插件日志（最后 12 行）---');
try {
  const log = fs.readFileSync(path.join(DSH_HOME, 'surfcore', 'plugin.log'), 'utf8').trim().split(/\r?\n/);
  add(log.slice(-12).join('\n'));
} catch { add('(没有 plugin.log：插件还没加载过)'); }

const report = `${lines.join('\n')}\n`;
const outFile = path.join(HERE, '诊断报告.txt');
fs.writeFileSync(outFile, report, 'utf8');
console.log(report);
console.log(`\n已写入：${outFile}\n把这个文件发给对方即可（不含 QQ 号/令牌明文）。`);
