# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Planned
- 任务串行编排（把上一个任务的产物喂给下一个）。
- WorkBuddy 的连接器任务（等官方放开本地接口）。

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
