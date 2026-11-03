// 扫码登录的「账号归属」纯逻辑回归：鱼号/主人号不能互相覆盖。
// 不启动 Edge、不联网。
import assert from 'node:assert/strict';
import { validateQrAccount } from '../plugins/surfcore/lib/bili-qr-login.mjs';

const fish = { mid: '1483638708', name: '卡哇伊的小肥鱼' };
const owner = { mid: '37634003', name: '玛露Marrow' };
const other = { mid: '99999999', name: '路人' };
const base = { selfMid: fish.mid, ownerMid: owner.mid };

// 主人目标：鱼号不能当主人；配置的 owner.mid 必须一致
assert.equal(validateQrAccount({ ...base, target: 'owner', account: fish }).ok, false, '鱼号不能当主人');
assert.match(validateQrAccount({ ...base, target: 'owner', account: fish }).error, /小肥鱼/);
assert.equal(validateQrAccount({ ...base, target: 'owner', account: owner }).ok, true, '主人号应通过');
assert.equal(validateQrAccount({ ...base, target: 'owner', account: other, expectedMid: owner.mid, expectedName: owner.name }).ok, false, '扫错主人号应拒绝');
assert.match(validateQrAccount({ ...base, target: 'owner', account: other, expectedMid: owner.mid }).error, /不是配置里的主人/);

// 鱼目标：主人号不能当鱼；已有 self.mid 时不能静默换号
assert.equal(validateQrAccount({ ...base, target: 'fish', account: owner }).ok, false, '主人号不能当鱼');
assert.match(validateQrAccount({ ...base, target: 'fish', account: owner }).error, /主人账号/);
assert.equal(validateQrAccount({ ...base, target: 'fish', account: fish }).ok, true, '现有鱼号应通过');
assert.equal(validateQrAccount({ ...base, target: 'fish', account: other }).ok, false, '已有 self 时换号应拒绝');
assert.match(validateQrAccount({ ...base, target: 'fish', account: other }).error, /不是当前小肥鱼/);

// 新用户：self.mid 为空时，扫任何非主人号都可以当鱼
assert.equal(validateQrAccount({ selfMid: '', ownerMid: owner.mid, target: 'fish', account: other }).ok, true, '新用户应能绑定账号');
assert.equal(validateQrAccount({ selfMid: '', ownerMid: owner.mid, target: 'fish', account: owner }).ok, false, '新用户也不能把主人号当鱼');
// 只有一个 B站 号的用户：显式勾选后才允许主人号 == 鱼号
assert.equal(validateQrAccount({ selfMid: '', ownerMid: owner.mid, target: 'fish', account: owner, allowSameAsOwner: true }).ok, true, '单账号用户勾选后应放行');
// 已有 self.mid 时：
//   · 扫成"主人号"且有勾选 → 允许（单账号用户换到自己的号，2026-10-27 修）
//   · 扫成任意第三个号 → 仍然拒绝（防被换人）
assert.equal(validateQrAccount({ ...base, target: 'fish', account: owner, allowSameAsOwner: true }).ok, true, '勾选后应能换成本人同一个号');
assert.equal(validateQrAccount({ ...base, target: 'fish', account: other, allowSameAsOwner: true }).ok, false, '勾选也不能换成无关的第三个号');
// 配置本身就写成同一个号（self.mid == owner.mid）时视为单账号，不需要勾选
assert.equal(validateQrAccount({ selfMid: owner.mid, ownerMid: owner.mid, target: 'fish', account: owner }).ok, true, '配置为同一个号时放行');

// 没读到 mid 直接失败
assert.equal(validateQrAccount({ target: 'fish', account: {} }).ok, false);

console.log('OK test-bili-qr-login');
