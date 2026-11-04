# 2026-11-04 SurfCore 设置页整页空白：删自更新时误删了 OverviewTab 的状态声明

## 现象
DSH → 设置 → SurfCore 什么都不显示（连标签栏都没有）。插件本身正常运行（plugin.log「已激活」、pet-api 正常、桥接已启动）。

## 定位
无头 Edge 带 DSH 会话 cookie 打开设置页并收集前端异常（只读，不点其它按钮）：
`ReferenceError: gateData is not defined at OverviewTab` → `slot entry crashed in 'settings.section'`，
DSH 的插槽把整个 SurfCore 设置区卸载，所以整页空白。修掉一个后又出现 `snowImport is not defined`。

## 根因
提交 0eeab428（桌宠替代 surfpet、删除自更新）在 OverviewTab 里删「组件更新」状态块时，把同一块里与更新无关的
声明一起删了：`compat` / `compatError` / `gateData` / `gateAlert` / `dismissedGates` / `snowError` / `snowImport`。
`node --check` 只查语法，`test-client-contract.mjs` 是字符串契约，都发现不了渲染期才抛的 ReferenceError。

## 修法
- 在 OverviewTab 恢复这 7 个声明（只恢复仍被引用的；`updates` / `restartHint` / `tokenDraft` / `updateOpen` 已无引用，不恢复）。
- 新增 `plugins/surfcore/scripts/test-client-state-decls.mjs` 并挂进插件 `npm test`：每个被调用的 `setXxx(...)` 必须有声明。
  对 0eeab428 的 client.js 报出全部 6 个缺失 setter（红），修复后与导入时的原版都为绿。

## 验证
- 无头探测：13 个标签（概览 / 角色 / QQ / 语音 / 桌宠 / B站 / Token 额度 / 观看历史 / 记忆 / 对齐 / 扩展 / 全部参数 / 诊断）
  全部渲染，前端零异常；「桌宠」页显示客户端连接状态。
- `node scripts/test-client-state-decls.mjs`；插件 `npm test`；`run_surfcore.py`。

## 回滚
`git revert` 本提交（会重新出现空白页，不建议）。
