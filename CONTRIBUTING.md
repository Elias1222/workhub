# 参与贡献

欢迎 issue 与 PR。这个项目刻意保持「零依赖、单文件前端、能在本机直接跑」，改动前请先读
[docs/design.md](docs/design.md)，那里记录了若干看起来奇怪但**删掉就会复发**的实现。

## 本地开发

```bash
python -m pip install -e ".[dev]"
ruff check .
python -m unittest discover -s tests -t . -v
python -m workhub --open      # http://127.0.0.1:8770/
```

Windows 上改完代码重启：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart.ps1
```

> 直接起新进程而不结束旧的，端口会被占着，你看到的还是旧代码。

## 代码约定

- Python 3.10+，**不引入第三方运行时依赖**；标准库能做的事不要加依赖。
- 拿子进程输出时用 `util.run_hidden()`，不要直接 `subprocess.run(text=True)`（编码坑见 design.md 第 6 节）。
- 用户输入当不可信：目录名走 `resolve_outdir()`，文件路径必须 resolve 到 `OUT_ROOT` 内。
- 前端是单文件、无构建、无 CDN；新样式尽量复用现有 CSS 变量。
- 面向用户的文案默认中文，接口与代码注释用中文也行，但标识符一律英文。

## 加一个新目标

1. 在 `config.py` 的 `DEFAULTS` 里加该工具的路径（支持环境变量覆盖）；
2. 在 `targets.py` 实现 `target_state` 分支（`running` / `headline` / `detail` / `actions`）；
3. 在 `jobs.py` 写执行器并注册到 `JOB_RUNNERS`，必要时在 `server.py` 的 `/api/task` 白名单里加名字；
4. 在 `workhub/web/index.html` 的 `TARGETS` / `LABEL` / `HINT` 里加一条芯片；
5. 补测试，跑 `ruff` 与 `unittest`。

## 提交信息

```
feat: 一句话说明
fix: 修了什么、为什么
docs: 只动文档
test: 只动测试
```

## 行为准则

保持对使用者诚实：做不到的能力不要假装做到，UI 上要标出来（比如 WorkBuddy 的「半自动」）。
