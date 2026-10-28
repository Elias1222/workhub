# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.4.0] - 2026-10-29

### Added
- **人工节点也能进链**：Kimi 桌面端 / WorkBuddy 的步骤以「等人工交回」停住，链上后面的步骤
  保持「等上一步」；在应用里做完后点任务卡上的 **交回结果**，把内容粘回来，这一步转为已完成，
  并把这段文字传给下一步。`POST /api/job/<id>/handback`。
- 「放弃这一步」＝取消一个等人工交回的步骤，链上后面的步骤照旧自动跳过。

### Changed
- `handed_off` 不再算终点：`TERMINAL_STATUSES` 去掉它，`CHAIN_TARGETS` 扩到全部六个目标。

## [1.3.0] - 2026-10-29

### Added
- **每一步的改动看得见**：任务开始与结束时各对交付目录做一次快照，任务卡上写清
  「新 / 改（带字节增减）/ 删」了哪些文件，点一下就能打开产物。
- 接力传下去的改成**这一步自己的产物**（不再把同一目录里上几步留下的文件一并塞过去），
  `{files}` 同样只展开这些路径。

### Changed
- `/api/job` 与 `/api/state` 的任务对象新增 `touched` 字段（`[{path, change, size, delta}]`）。

## [1.2.0] - 2026-10-29

### Added
- **接力（任务串行编排）**：一条链 2–5 步，上一步成功才放下一步；产物绝对路径与上一步答复
  自动拼进下一步的提示词（也支持 `{files}` / `{prev}` 占位）；上一步失败/取消/中断，
  后面的步骤自动标「已跳过」并说明断在哪一步。新增 `POST /api/chain`，任务卡显示「接力 2/3」。
- 任务状态新增 `waiting`（等上一步）与 `skipped`（已跳过）；重启时等待中的步骤也标为中断。
- 接力只接受能回收结果的目标（Codex / DSH / Muse / Kimi 网页）——Kimi 桌面端与 WorkBuddy 是人工接力，
  提交时就拒绝；万一某个步骤仍以 `handed_off` 结束，链会停下并把余下步骤标「已跳过」。

### Fixed
- 多个任务同时落盘时 `jobs.json` 会被并发写坏（`PermissionError: WinError 32`）：
  改为各写各的临时文件 + 加锁替换，冲突时重试。

## [1.1.0] - 2026-10-28

第一个可以对外发布的版本：从「单文件脚本」整理成可安装的包，并补上测试、CI 与文档。

### Added
- **DSH（DeepSeek Harness）** 作为第五个目标：走无头 CLI 执行，任务结果回传网页；
  API key 从 `~/.dsh/.credentials.yaml` 读取后注入子进程，不落盘、不出现在接口里。
- **Kimi 网页任务（WebBridge）**：读正文 / 截图 / 导出 PDF，产物落 `out/kimiweb/`；
  「探测网页」给出中文结论（守护进程、扩展版本、版本不匹配时的升级命令）。
- **快捷模板与 `out/` 交付目录**：出图 / 文档 / PPT / 代码 / 视频五套模板，
  子进程的工作目录直接指向交付目录，产物统一收进 `out/<子目录>`，卡片上可点开文件。
- 任务卡「再来一次」（`POST /api/job/<id>/retry`）与「日志」（`GET /api/job/log`）。
- `WORKHUB_TOKEN` / `--token`：给非回环地址访问加口令；未设口令时拒绝绑定非回环地址。
- `GET /healthz` 轻量探活；`--data-dir` 指定数据目录；`/api/ping` 单实例守卫。
- 单元测试（配置 / 任务 / HTTP / 进程）与 GitHub Actions（三平台 × Python 3.10–3.13 + 构建 wheel）。
- `pyproject.toml`（`pip install -e .` 后可用 `workhub` 命令）、`examples/config.example.json`。

### Changed
- 单文件 `workhub.py` 拆成包：`config` / `procs` / `util` / `targets` / `jobs` / `server` / `cli`，
  前端移到 `workhub/web/index.html`，运行时数据移到仓库外的数据目录（`%LOCALAPPDATA%\WorkHub`）。
- 进程、剪贴板、信号改为跨平台实现（Windows / macOS / Linux），CI 在三个系统上真跑。
- 前端：五张卡一行（宽屏）、产物文件胶囊与图片预览、模板行、Kimi 探测的中文结论、
  「再来一次 / 日志」按钮，以及按目标能力渲染的启停按钮。

### Fixed
- `run_hidden` 按控制台编码（cp936）解码导致 `UnicodeDecodeError`，
  进而把「WebBridge 守护进程在跑」误报成没跑。
- 旧实例占用端口时静默失败：现在单实例守卫会报告已有实例的 PID。
- 剪贴板写入改按 UTF-8 传参，含 emoji 的提示词不再乱码。
- Muse 启动时把空字符串当成可执行文件路径（`Path("")` 等于 `.`）导致 `WinError 5`。
- `return` 写在 `finally` 里会静默吞掉异常；产物目录路径未做 `resolve` 越界检查。

## [1.0.0] - 2026-10-28

### Added
- 首个版本：四张状态卡（Codex / WorkBuddy / Kimi / Muse）、启停与日志、任务台并行分发。
- Codex 后台执行（`codex exec --json`）与最终答复回收；Muse 出片（提交 + 轮询 + 内嵌预览）。
