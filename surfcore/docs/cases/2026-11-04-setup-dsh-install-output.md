# 2026-11-04 setup-dsh：`dsh plugin install` 失败时只报退出码

## 现象
`node scripts/setup-dsh.mjs` 末尾报「dsh plugin --profile desktop install 返回退出码 1」，然后回滚；看不到任何原因。
补上输出后又是乱码（cmd.exe 的中文报错）。

## 根因
1. `installDshBundle` 用 `spawnSync` 捕获了 stdout/stderr，但失败分支从不打印。
2. 捕获按 UTF-8 解码；中文 Windows 上 cmd.exe 自己的报错走 OEM 代码页 936（GBK），按 UTF-8 解出来是乱码。
3. 这次的真实原因：DSH 桌面版（`<安装目录>\DeepSeek Harness.exe`）自带 CLI
   `<安装目录>\resources\runtime\cli\bin\dsh.cmd`，但不把它加进 PATH，于是 cmd 报「'dsh.cmd' 不是内部或外部命令」。

## 修法
- 失败时打印输出末尾 40 行；无输出时提示手动运行 `dsh plugin --profile <profile> install`。
- 输出先按 UTF-8 严格解码，不合法退回 GBK（Node 自带 ICU 支持 `TextDecoder('gbk')`）。
- 识别「不是内部或外部命令 / is not recognized」时给出下一步：把 `<安装目录>\resources\runtime\cli\bin` 加进 PATH 后重跑。

## 验证
- `node --check scripts/setup-dsh.mjs`。
- 解码：`cmd /c nosuch.cmd` 的 stderr 经同一逻辑显示为「'nosuch.cmd' 不是内部或外部命令……」。
- `scripts/test-setup-dsh-idempotent.mjs`：结果与改动前一致（该测试在本机临时 DSH_HOME 下原本就有 6 项失败，
  因为测试 PATH 里没有 dsh，安装步骤失败后回滚；与本次改动无关）。

## 回滚
`git revert` 本提交即可；只影响失败时的日志输出。
