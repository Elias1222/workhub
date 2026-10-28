# 安全说明

## 设计边界

WorkHub 是**本机编排器**：它不代理任何模型的网络请求，也不保存账号密码。

- 默认只监听 `127.0.0.1`。`--host` 指定非回环地址而没有 `--token` 时，程序**拒绝启动**。
- 设置 token 后，`/api/*` 与 `/artifact` 需要 `X-WorkHub-Token` 头或 `?token=`；首页与 `/healthz` 保持公开。
- `/artifact` 将路径 resolve 后强制限制在产物目录内，`../` 越界返回 403。
- 任务提示词与输出会落盘到数据目录（`jobs.json`、`logs/`），那是本机的普通文件。

## 凭据处理

- **DSH**：API key 从 `~/.dsh/.credentials.yaml` 的 `refs:` 段读取，仅注入子进程环境变量；
  不写入 `config.json`、不落 `jobs.json`、不出现在 `/api/config` 与日志里。
- **Codex / Kimi / WorkBuddy / Muse**：使用各应用自己的登录态，WorkHub 不接触其凭据。

## 已知风险

- 任务提示词会交给第三方 CLI/API 处理，**不要在里面放密钥**；`jobs.json` 是明文。
- `/api/task` 能启动子进程（Codex / DSH）。默认只绑回环地址，但如果你设了 `--host 0.0.0.0`
  又没有 token（会被拒绝启动），或把 token 贴在公网页面里，等于把本机执行权限交出去。
- 任务取消是尽力而为：`terminate()` 之后仍可能在子进程里留下孙进程（例如 Codex 自己拉起的命令）。

## 报告问题

发现安全问题请开 issue 并标注 `security`，或在 issue 里只描述影响、不贴利用细节，维护者会跟进。
