# WorkHub

**一个本地网页控制台，把 Codex、WorkBuddy、DSH、Kimi、Muse 放在同一张桌子上。**

同一句话发给多个 agent 并行干活，产物统一收进 `out/`，谁在跑、谁挂了、花了多少钱，一屏看完。
零第三方依赖，只监听 `127.0.0.1`，任务在你的机器上后台执行。

[![CI](https://github.com/Elias1222/workhub/actions/workflows/ci.yml/badge.svg)](https://github.com/Elias1222/workhub/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

![WorkHub 界面](docs/preview.png)

---

## 为什么

手上同时开着几个「AI 工作台」的人都会遇到同一组麻烦：

- 每个工具一个窗口，问同一件事要说五遍；
- 谁在用哪份配额、哪个按秒计费，心里没数；
- 成品散落在各个工具的下载目录里，回头找不到；
- 想写脚本串起来，发现一半工具只有 GUI，没有可调用的接口。

WorkHub 把这些收敛成一个页面：**状态卡**管进程，**任务台**管分发，**产物目录**管交付。

## 能做什么

| | 状态 / 启停 | 并行接活 | 交付形态 |
| --- | --- | --- | --- |
| **Codex** | 进程 + CLI 版本 | ✅ 真后台 `codex exec`，回收最终答复 | 文件写进 `out/<目录>`，卡片上可点 |
| **WorkBuddy** | 进程 + 版本 | ⚠️ 半自动：复制提示词 + 唤起应用 | 你在应用里保存 |
| **DSH** | 进程 + 无头 CLI | ✅ 真后台 `dsh headless`，回收答复 | 文件写进 `out/<目录>` |
| **Kimi** | 进程 + WebBridge 守护进程 | ✅ 网页任务：读正文 / 截图 / 导 PDF | 截图与 PDF 落 `out/kimiweb/` |
| **Muse** | 本地服务 8765 | ✅ 真出片（按输出秒计费） | 视频内嵌预览 + mp4 链接 |

> 没有 CLI 的工具不硬凹：WorkBuddy 走「复制提示词 → 唤起应用」，页面会明确标注这是半自动。
> Kimi 的桌面端本身没有任务接口，网页任务走的是它的本地 WebBridge（见下文）。

## 快速开始

需要 **Python 3.10+**，无第三方依赖。

```bash
git clone https://github.com/Elias1222/workhub.git
cd workhub
python -m workhub --open          # 打开 http://127.0.0.1:8770/
```

装成命令也可以用：

```bash
python -m pip install -e .
workhub --open
```

Windows 想双击启动：`scripts\workhub.cmd`（前台带日志）或 `scripts\launch.vbs`（静默，无黑窗）。

## 用法

1. **点一个模板**（出图 / 文档 / PPT / 代码 / 视频）——它会把提示词和交付目录 `out/<prefix>-MMDD-HHMM` 一起填好；
2. **勾工具**——同一句话可以同时发给 Codex 和 DSH，谁先出结果看谁的；
3. **Ctrl+Enter 分发**——每个工具一张任务卡，实时状态、耗时、可取消；完成后结果、文件胶囊、图片或视频预览都在这张卡上；
4. **产物统一在 `out/`**——网页里点开就是原文件，也可以直接开目录。

失败的任务卡上点「再来一次」会原样重跑；「日志」看这次调用的原始输出。

### 几个细节

- **交付目录**：勾了 Codex / DSH 并填了 `out/` 子目录时，子进程的**工作目录就是该目录**，
  提示词里也会写明「成品写这里、参考文件用绝对路径读原工作区」——这是实测唯一可靠的做法，
  只加一句提示词、cwd 不动的话，模型会把文件写回原工作区。
- **模板的 `code` 不指定目录**：改代码就该改在原仓库，硬塞进 `out/` 反而别扭。
- **Muse 按秒计费**：卡片上会写「768P · 4s · 4 秒计费」，避免手滑出长片。

### Kimi 网页任务的前置条件

Kimi 桌面端没有通用任务接口，网页任务走 [Kimi WebBridge](https://www.kimi.com/products/kimi-webbridge)：

1. 装 WebBridge 守护进程（`kimi-webbridge start`，WorkHub 发任务时也会自动尝试拉起）；
2. 在浏览器装 Kimi 扩展，并在 Kimi 侧边栏 → 设置 → 本地远程控制 里连上 `ws://127.0.0.1:10086/ws`；
3. 回 WorkHub 点 Kimi 卡片的「探测网页」，看到 `ready` 就能用了。

提示词**首行写网址**，再选模式（正文+截图 / 只读正文 / 导 PDF / 只截图）。
没接扩展时探测会直接告诉你缺哪一步，而不是丢一个 `502`。

### DSH 卡片

DSH 是 DeepSeek Harness 自己：卡片显示它的进程与无头 CLI，任务走 `dsh headless "<任务>"`。
它需要 API key，WorkHub 会从 `~/.dsh/.credentials.yaml` 的 `refs:` 段读取 `DEEPSEEK_API_KEY`
**仅注入子进程环境变量**——不落盘、不回前端、不写进日志。

## 配置

所有路径都有默认值（猜一个大概率存在的位置），猜不到不影响启动——卡片会显示「未找到」，
改配置就行。优先级：**环境变量 > `<数据目录>/config.json` > 内置默认值**。

```bash
# 数据目录（任务历史、日志、产物），默认 Windows %LOCALAPPDATA%\WorkHub，其它 ~/.workhub
WORKHUB_DATA=...
WORKHUB_WORKDIR=...            # Codex / DSH 的默认工作目录，默认当前目录
WORKHUB_OUT=...                # 产物根目录，默认 <数据目录>/out
WORKHUB_PORT=8770
WORKHUB_HOST=127.0.0.1
WORKHUB_TOKEN=...              # 设置后 /api 与 /artifact 需要口令

WORKHUB_CODEX_CLI=... WORKHUB_CODEX_NODE_DIR=...
WORKHUB_WORKBUDDY_EXE=...
WORKHUB_KIMI_EXE=... WORKHUB_KIMI_BRIDGE=... WORKHUB_KIMI_WEB=...
WORKHUB_MUSE_DIR=... WORKHUB_MUSE_PORT=...
WORKHUB_DSH_CLI=... WORKHUB_DSH_EXE=... WORKHUB_DSH_JS=... WORKHUB_DSH_CREDS=... WORKHUB_DSH_GUI=...
```

`config.json` 只要写想覆盖的键（深合并），完整样例见 [examples/config.example.json](examples/config.example.json)。

### 命令行

```text
python -m workhub [--host 127.0.0.1] [--port 8770] [--open] [--token 口令] [--data-dir 目录] [--debug]
python -m workhub --version
```

同端口重复启动会被拦下并告诉你已有实例的 PID——不然旧进程占着端口，新代码永远不生效。

## HTTP API

全部在 `127.0.0.1` 上，返回 JSON。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | `ok`（探活用，不查子进程） |
| GET | `/api/state` | 五张卡的状态 + 最近任务 |
| GET | `/api/config` | 生效中的配置（不含密钥） |
| GET | `/api/templates` | 快捷模板 + 产物根目录 |
| GET | `/api/jobs` | 任务列表 |
| GET | `/api/job?id=` | 单个任务 |
| GET | `/api/job/log?id=&lines=` | 该次执行的日志尾部 |
| GET | `/api/logs?target=&lines=` | 各家自己的日志（codex / workbuddy / kimi / muse） |
| GET | `/api/kimi/probe` | WebBridge 探测：守护进程、扩展、版本提示 |
| GET | `/artifact?path=` | 取 `out/` 下的产物（越界 403） |
| POST | `/api/task` | `{prompt, targets, muse, codex, kimiweb, dsh}` 分发 |
| POST | `/api/action` | `{target, action}` 启停/打开/启停桥 |
| POST | `/api/job/<id>/cancel` | 取消 |
| POST | `/api/job/<id>/retry` | 原样重跑 |
| GET | `/api/ping` | 名字、版本、PID、启动时间 |

```bash
curl -s -X POST http://127.0.0.1:8770/api/task \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"写一份 5 行的 README.md","targets":["codex"],"codex":{"outdir":"doc-1028"}}'
```

## 安全

- **默认只监听回环地址**，不对外；想在局域网用就 `--host 0.0.0.0 --token <口令>`，否则启动会直接拒绝。
- 设了 token 后，`/api/*` 与 `/artifact` 需要 `X-WorkHub-Token` 头或 `?token=`；首页与 `/healthz` 保持公开便于探活。
- `/artifact` 会把路径 resolve 后强制限制在 `out/` 内，`../` 一律 403。
- 不保存任何账号密码；DSH 的 key 只在子进程环境变量里存在一次。
- 任务提示词会落盘在数据目录的 `jobs.json`，介意的话把 `WORKHUB_DATA` 指到加密盘。

## 架构

```
workhub/
├── workhub/
│   ├── config.py    默认值、数据目录、config.json 合并、模板
│   ├── procs.py     跨平台进程/端口/剪贴板（Windows ctypes，POSIX ps/signals）
│   ├── util.py      HTTP JSON、日志尾部、TTL 缓存、subprocess 封装（UTF-8/GBK 兜底）
│   ├── targets.py   五家的探测、启停、打开、WebBridge 探测
│   ├── jobs.py      任务生命周期与各执行器（codex / dsh / muse / kimiweb / handoff）
│   ├── server.py    ThreadingHTTPServer 路由、产物服务、token 校验
│   ├── cli.py       argparse、单实例守卫
│   └── web/index.html   单文件前端（无构建、无 CDN）
├── tests/          unittest，覆盖配置/任务/HTTP/进程
└── scripts/        Windows 启动与开发重启脚本
```

设计取舍写在 [docs/design.md](docs/design.md)：为什么用 `http.server`、为什么产物走 `out/`、
为什么 Kimi 走 WebBridge 而不是模拟点击。

## 开发

```bash
python -m pip install -e ".[dev]"
ruff check .
python -m unittest discover -s tests -t . -v
```

CI 在 Linux / macOS / Windows × Python 3.10–3.13 上跑 lint 与测试，另外构建一个 wheel 作为产物。

修改后重启（Windows）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart.ps1
```

## 平台支持

| | 状态 |
| --- | --- |
| Windows | 主要开发平台，五张卡全部实测 |
| macOS / Linux | 代码已跨平台（进程、剪贴板、spawn 都有 POSIX 分支），但没有对应桌面应用可测，卡片会显示「未找到」 |

## 路线图

- [ ] 任务队列与并发上限（现在每个请求直接起进程）
- [ ] 产物目录打包下载、按日期归档
- [ ] 更多目标：只要给 `cli` 一行命令，就能接进 `jobs.py`
- [ ] 深色/浅色主题切换

## 许可

[MIT](LICENSE)。用到的各家应用与接口归各自厂商所有，本项目只是本机编排，不代管账号。
