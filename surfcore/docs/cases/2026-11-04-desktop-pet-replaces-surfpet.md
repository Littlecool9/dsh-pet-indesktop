# 桌面桌宠替代 surfpet：移除安装/更新，桌宠页改显示客户端在线状态

## 现象

- 旧「桌宠」页提供安装包地址、Electron 路径、启动/停止/卸载，以及 SurfCore 本体的 git/zip 自更新。
- 桌面桌宠改为 desktop-pet 仓库根目录的 PySide6 程序后，这些入口已经指向不存在的东西：
  页面仍让人装 Electron，`/pet/status` 仍读 `petService`，更新器还会对 SurfCore 根执行 `git fetch/merge`。
- 由于 `surfcore/` 已并入 desktop-pet git 仓库，SurfCore 的 git 自更新会作用到整个桌宠仓库，风险不可接受。

## 环境

| 项 | 值 |
| --- | --- |
| 系统 / DSH 版本 | Windows / DSH 0.2.x |
| SurfCore 版本 | v0.8.8（不 bump） |
| 安装方式 | worktree（`modular/p3-surfcore-drop-surfpet`） |

## 根因

- `plugins/surfcore/lib/pet.js` 是 surfpet（Electron）的安装/启动/更新服务；
  `plugins/surfcore/lib/updates.js` 是 SurfCore 自更新服务（git fast-forward + Release zip）。
- 桌面端换成 PySide6 后，桌面桌宠**自己**读 `~/.dsh/surfcore/pet/host.json` 连 pet-api 并长轮询 `/events`，
  不需要插件安装/拉起；在线状态已经由 `petChat.online()` 统一记录。
- 因此这两份服务和它们的路由/界面都成为死代码，且更新器在合并仓库里会误伤整个 desktop-pet。

## 完整逻辑

- **链路**：设置页 `client.js` → `/dsh-surfcore/api/pet/status` → `petChat.status()`/`petChat.online()`；
  桌面桌宠 → `/dsh-surfcore/pet-api/*` → `pet-chat.js` / `pet-purpose.js`。
  `/pet/status` 与 `/pet-api/status` 都只报 `client.{online,lastSeenAt}`，不再读 `petService`。
- **机制**：是「谁拥有桌面进程」的契约变化。以前插件拥有 Electron 子进程，所以能 start/stop/update；
  现在桌面端是独立应用，插件只提供回环 API 与发现文件，连接由桌宠主动发起。
- **爆炸半径**：删除 `pet.js`/`updates.js` 与对应路由/UI；保留 `pet-chat.js`、`pet-purpose.js`、`pet-api.js`
  的全部业务端点（`/persona`、`/self-talk`、`/budget`、`/usage`、`/focus`、`/proactive/claim`、`/chat`、`/events` 等）。
  不碰用户配置与密钥。
- **取舍**：A（保留安装器并兼容两种桌宠）会让两套所有权长期并存；B（直接删除）更符合合并仓库的边界。
  选 B，回滚成本低（`git revert`）。

## 修法

- 删除 `plugins/surfcore/lib/pet.js`、`plugins/surfcore/lib/updates.js` 与 `scripts/apply-update.mjs`。
- `lib/index.js`：移除 pet/updates import、`createPetService`、`createUpdatesService`、`resumePendingApply`、
  `/pet/{config,install,remove,clean,start,stop,electron-*}`、`/updates` 路由与启动自动检查；
  一键启动/停止不再包含桌宠；`/pet/status` 改为返回 `client`。
- `lib/pet-api.js`：`statusForPet()` 不再接收 `petService`，改报 `chat.online()`。
- `lib/store.js`：删除 `updates` 默认配置块。
- `lib/client.js`：「桌宠」页改为显示 PySide6 客户端在线/离线与最近连接，说明它通过
  `~/.dsh/surfcore/pet/host.json` 自己连接、没有安装按钮；保留对话/专注设置。移除更新弹窗、
  通道/令牌、下载进度与重启提示。
- `plugins/surfcore/README.md`、`plugins/surfcore/docs/PET.md` 同步新口径。

## 验证

- 自动化：`run_surfcore.py`（见任务检查）必须 `run_surfcore: rc=0`。
  其中 audit 的已知环境失败之外不得出现新失败；`plugins/surfcore` 的 `npm test` 必须全绿。
- 新增/更新的回归：
  - `test-pet-api.mjs`：`/status` 返回 `client.online/lastSeenAt`，在线/离线两态，且不再有旧的 `pet` 字段。
  - `test-client-contract.mjs`：「桌宠」页读 `/pet/status`、显示 `st.client.online` 与在线/离线徽章，
    不再出现 `/pet/install|start|stop`、Electron 路径或 `/updates`。
  - `test-host-smoke.mjs`：设置页 `/pet/status` 返回 `ok` + `client.{online,lastSeenAt}`。
- 失败路径：状态读不到时桌宠页显示红字错误（现有 `err` 分支）；在线但长时间无轮询会自然变离线。
- 手工：启动 desktop-pet 的桌宠 → 设置 → SurfCore → 桌宠显示「桌宠在线」；关闭桌宠后变「桌宠离线」。

## 遗留 / 后续

- 桌面桌宠自身的安装/启动/更新由 desktop-pet 仓库负责，SurfCore 不再提供。
- `surfcore/docs/PITFALLS.md` 等历史文档仍保留旧桌宠事故记录，只作历史参考。

## 回滚

`git revert <本次提交>`。回滚后 surfpet 安装/更新代码与路由恢复，但桌面端仍是 PySide6，不会自动变回 Electron。
