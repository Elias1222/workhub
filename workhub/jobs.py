"""任务模型与执行器：排队、后台执行、日志、产物、取消。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import traceback
import urllib.parse
import uuid
from pathlib import Path

from .config import CFG, HOME, JOBS_FILE, LOG_DIR, OUT_ROOT
from .procs import CREATE_NO_WINDOW, set_clipboard
from .targets import (
    action_bridge,
    action_start,
    kimi_command,
    kimi_web_status,
    muse_base,
    muse_ping,
)
from .util import http_json, now_ts

# ------------------------------------------------------------------ jobs

JOBS: list[dict] = []
JOBS_LOCK = threading.Lock()
SAVE_LOCK = threading.Lock()
MAX_JOBS = 120

# 接力：一条链最多几步；这些状态表示一条任务已经有确定结局
CHAIN_MAX_STEPS = 5
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "interrupted", "skipped")


def load_jobs() -> None:
    global JOBS
    if JOBS_FILE.exists():
        try:
            data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            JOBS = data.get("jobs", []) if isinstance(data, dict) else []
        except Exception:
            JOBS = []
    changed = False
    for job in JOBS:
        if job.get("status") in ("running", "queued", "waiting"):
            job["status"] = "interrupted"
            job["error"] = "工作台重启，任务中断"
            changed = True
    if changed:
        save_jobs()


def save_jobs() -> None:
    with JOBS_LOCK:
        clean = []
        for job in JOBS[:MAX_JOBS]:
            clean.append({k: v for k, v in job.items() if not k.startswith("_")})
        payload = {"jobs": clean}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # 多个任务线程可能同时落盘：各写各的临时文件，再加锁替换
    with SAVE_LOCK:
        tmp = JOBS_FILE.with_name(f"{JOBS_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            for attempt in range(4):
                try:
                    os.replace(tmp, JOBS_FILE)
                    return
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05)
        except Exception:
            traceback.print_exc()
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def job_public(job: dict) -> dict:
    out = {k: job.get(k) for k in (
        "id", "target", "name", "color", "prompt", "status", "error", "output", "file",
        "media_url", "started", "ended", "elapsed", "note", "params", "outdir", "files",
        "chain_id", "chain_title", "step", "steps_total", "depends_on",
    )}
    if out.get("elapsed") is None and job.get("status") in ("running", "queued"):
        out["elapsed"] = round(now_ts() - (job.get("started") or now_ts()), 1)
    return out


def list_jobs() -> list[dict]:
    with JOBS_LOCK:
        return [job_public(j) for j in JOBS[:60]]


def get_job(job_id: str) -> dict | None:
    with JOBS_LOCK:
        for job in JOBS:
            if job["id"] == job_id:
                return job
    return None


def update_job(job: dict, **fields) -> None:
    with JOBS_LOCK:
        job.update(fields)
    save_jobs()


def new_job(target: str, prompt: str, params: dict | None = None) -> dict:
    job = {
        "id": "j" + uuid.uuid4().hex[:10],
        "target": target,
        "name": {"codex": "Codex", "workbuddy": "WorkBuddy", "kimi": "Kimi", "muse": "Muse",
                 "kimiweb": "Kimi 网页", "dsh": "DSH"}.get(target, target),
        "color": {"codex": "#2ecc8f", "workbuddy": "#f0a12e", "kimi": "#4c8dff",
                  "muse": "#a67cff", "kimiweb": "#4c8dff", "dsh": "#c94dff"}.get(target, "#5b9dff"),
        "prompt": prompt,
        "status": "queued",
        "error": None,
        "output": "",
        "file": None,
        "media_url": None,
        "started": now_ts(),
        "ended": None,
        "elapsed": None,
        "params": params or {},
        "_cancel": False,
        "_proc": None,
    }
    with JOBS_LOCK:
        JOBS.insert(0, job)
    save_jobs()
    return job


def job_log_path(job: dict) -> Path:
    return LOG_DIR / f"{job['id']}.log"


def resolve_outdir(name: str) -> Path | None:
    """把用户给的目录名收敛成 OUT_ROOT 下的安全子目录。"""
    raw = (name or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return None
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", raw)[:60].strip("-")
    if not safe:
        return None
    path = OUT_ROOT / safe
    try:
        path.resolve().relative_to(OUT_ROOT.resolve())
    except Exception:
        return None
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        traceback.print_exc()
        return None
    return path


def run_codex_job(job: dict) -> None:
    prompt = job["prompt"]
    cfg = CFG["codex"]
    cli = Path(cfg["cli"])
    if not cli.exists():
        update_job(job, status="failed", error=f"未找到 codex CLI: {cli}", ended=now_ts())
        return
    outdir = resolve_outdir((job.get("params") or {}).get("outdir"))
    workdir = cfg["cwd"]
    if outdir is not None:
        update_job(job, outdir=str(outdir.relative_to(OUT_ROOT).as_posix()))
        workdir = str(outdir)
        prompt = (
            f"{prompt}\n\n"
            f"【交付目录】你当前的工作目录就是交付目录：{outdir}\n"
            "所有成品文件都直接写在这里（用相对路径即可）。"
            f"如果需要参考原工作区里的文件，用绝对路径去读：{cfg['cwd']}\n"
            "完成后用 Get-ChildItem 列出该目录，确认文件确实落在里面，再简要说明每个文件是什么。"
        )
    last_file = LOG_DIR / f"{job['id']}.last.md"
    args = [
        "cmd", "/c", str(cli), "exec",
        "--skip-git-repo-check",
        "--color", "never",
        "--json",
        "-C", workdir,
        "-s", "workspace-write",
        "-o", str(last_file),
        prompt,
    ]
    env = dict(os.environ)
    env["PATH"] = cfg["node_dir"] + os.pathsep + env.get("PATH", "")
    log_fh = open(job_log_path(job), "w", encoding="utf-8")
    proc = subprocess.Popen(
        args, cwd=workdir, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
        encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        bufsize=1,
    )
    update_job(job, status="running", _proc=proc)
    agent_msgs: list[str] = []
    commands: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_fh.write(line)
            log_fh.flush()
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            item = ev.get("item") or {}
            if ev.get("type") == "item.completed":
                itype = item.get("type")
                if itype == "agent_message" and item.get("text"):
                    agent_msgs.append(item["text"])
                elif itype == "command_execution" and item.get("command"):
                    commands.append(item["command"])
                elif itype == "reasoning" and item.get("text"):
                    pass
        proc.wait(timeout=30)
    except Exception as exc:  # noqa: BLE001
        update_job(job, status="failed", error=f"执行异常: {exc}")
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        log_fh.close()
        last = ""
        try:
            if last_file.exists():
                last = last_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
        # 去掉与最终答复重复的过程消息，并合并连续重复
        deduped: list[str] = []
        for m in agent_msgs:
            m = (m or "").strip()
            if not m or m == last or (deduped and deduped[-1] == m):
                continue
            deduped.append(m)
        if last:
            output = "\n\n".join(deduped + [last])
        elif deduped:
            output = "\n\n".join(deduped)
        else:
            output = ("已执行命令:\n" + "\n".join(commands[-10:])) if commands else ""
        if job.get("_cancel"):
            update_job(job, status="cancelled", output=output, ended=now_ts(),
                       elapsed=round(now_ts() - job["started"], 1))
        else:
            code = proc.returncode
            files = list_outdir_files(outdir)
            note = "交付目录里还没发现文件" if (outdir is not None and not files) else ""
            update_job(
                job,
                status="succeeded" if code == 0 else "failed",
                output=output.strip(),
                files=files,
                note=note or None,
                error=None if code == 0 else f"codex 退出码 {code}（详见 logs/{job['id']}.log）",
                ended=now_ts(), elapsed=round(now_ts() - job["started"], 1),
            )


def list_outdir_files(outdir: Path | None) -> list[str]:
    if outdir is None or not outdir.exists():
        return []
    found = []
    try:
        for p in sorted(outdir.rglob("*")):
            if p.is_file():
                found.append(p.relative_to(OUT_ROOT).as_posix())
            if len(found) >= 60:
                break
    except Exception:
        return found
    return found


def dsh_credentials() -> dict:
    """从 DSH 的凭据库（~/.dsh/.credentials.yaml 的 refs 段）取出 API key。

    `dsh headless` 不自己去读这个库（只认环境变量），所以无头跑之前把它喂进 env。
    只在本机内存里用：不写日志、不回传前端、不出现在任务卡上。
    """
    out: dict[str, str] = {}
    path = Path(CFG["dsh"].get("creds") or (HOME / ".dsh" / ".credentials.yaml"))
    if not path.exists():
        return out
    try:
        in_refs = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "refs:":
                in_refs = True
                continue
            if not line.startswith(" ") or not in_refs:
                continue
            name, _, value = stripped.partition(":")
            value = value.strip().strip("'\"")
            if name.strip() and value:
                out[name.strip()] = value
    except Exception:
        traceback.print_exc()
    return out


def dsh_env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # 直接跑 Electron 二进制当 Node 用（dsh.cmd 里也是这么干的）
    env["ELECTRON_RUN_AS_NODE"] = "1"
    if not env.get("DEEPSEEK_API_KEY"):
        key = dsh_credentials().get("DEEPSEEK_API_KEY")
        if key:
            env["DEEPSEEK_API_KEY"] = key
    return env


def dsh_argv(cfg: dict, prompt: str) -> list:
    """直接调 Electron 可执行文件跑 dsh CLI 的 JS 入口。

    不走 `cmd /c dsh.cmd`：那条路径里有空格（"DeepSeek Harness"），
    cmd 在带引号时会把路径截断成 `'C:\\...\\DeepSeek' 不是内部或外部命令`。
    注意 cli.js 在 app.asar 归档里（不是真目录，Path.exists() 为 False），
    但 Electron 自己能透明读取 asar 内的路径，所以不检查它是否存在。
    """
    exe = Path(cfg.get("exe") or "")
    js = cfg.get("js") or ""
    if exe.exists() and js:
        return [str(exe), "--expose-internals", str(js), "headless", prompt]
    return ["cmd", "/c", str(cfg["cli"]), "headless", prompt]


def run_dsh_job(job: dict) -> None:
    """我自己：走 `dsh headless "<任务>"` 真跑一遍，答案回传到任务卡。"""
    cfg = CFG["dsh"]
    cli = Path(cfg["cli"])
    if not cli.exists():
        update_job(job, status="failed", error=f"未找到 dsh CLI: {cli}", ended=now_ts())
        return
    prompt = job["prompt"]
    outdir = resolve_outdir((job.get("params") or {}).get("outdir"))
    workdir = cfg["cwd"]
    if outdir is not None:
        update_job(job, outdir=str(outdir.relative_to(OUT_ROOT).as_posix()))
        workdir = str(outdir)
        prompt = (
            f"{prompt}\n\n"
            f"【交付目录】你当前的工作目录就是交付目录：{outdir}\n"
            "成品文件直接写在这里（相对路径即可）。"
            f"需要参考原工作区里的文件，用绝对路径去读：{cfg['cwd']}\n"
            "完成后列一下该目录里的文件，再简要收尾。"
        )
    log_path = job_log_path(job)
    err_path = LOG_DIR / f"{job['id']}.stderr.log"
    env = dsh_env()
    out_fh = open(log_path, "w", encoding="utf-8")
    err_fh = open(err_path, "w", encoding="utf-8")
    cmd = dsh_argv(cfg, prompt)
    proc = subprocess.Popen(
        cmd, cwd=workdir, env=env,
        stdout=out_fh, stderr=err_fh, stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    update_job(job, status="running", _proc=proc)
    try:
        while proc.poll() is None:
            if job.get("_cancel"):
                proc.terminate()
                break
            time.sleep(0.8)
        code = proc.wait(timeout=60)
    except Exception as exc:  # noqa: BLE001
        update_job(job, status="failed", error=f"执行异常: {exc}", ended=now_ts())
        try:
            proc.kill()
        except Exception:
            pass
        code = -1
    finally:
        out_fh.close()
        err_fh.close()
    try:
        output = log_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        output = ""
    try:
        err_text = err_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        err_text = ""
    if job.get("_cancel"):
        update_job(job, status="cancelled", output=output, ended=now_ts(),
                   elapsed=round(now_ts() - job["started"], 1))
        return
    files = list_outdir_files(outdir)
    note = "交付目录里还没发现文件" if (outdir is not None and not files) else ""
    tail_err = "\n".join(err_text.splitlines()[-8:]) if (code != 0 and err_text) else ""
    update_job(
        job,
        status="succeeded" if code == 0 else "failed",
        output=output,
        files=files,
        note=note or None,
        error=None if code == 0 else (f"dsh 退出码 {code}：{tail_err}" if tail_err else f"dsh 退出码 {code}"),
        ended=now_ts(), elapsed=round(now_ts() - job["started"], 1),
    )


def run_muse_job(job: dict) -> None:
    p = job.get("params") or {}
    prompt = job["prompt"]
    if not muse_ping().get("ok"):
        ok, msg = action_start("muse")
        if not ok:
            update_job(job, status="failed", error=msg, ended=now_ts())
            return
    payload = {
        "prompt": prompt,
        "model": p.get("model") or "MiniMax-H3",
        "resolution": p.get("resolution") or "768P",
        "duration": int(p.get("duration") or 4),
        "ratio": p.get("ratio") or None,
        "region": p.get("region") or "cn",
    }
    try:
        r = http_json("POST", muse_base() + "/api/generate", payload, timeout=15)
        local_id = r.get("id")
    except Exception as exc:  # noqa: BLE001
        update_job(job, status="failed", error=f"提交失败: {exc}", ended=now_ts())
        return
    update_job(job, status="running", note=f"排队中 · {local_id}")
    deadline = time.time() + 1800
    while time.time() < deadline:
        if job.get("_cancel"):
            try:
                http_json("POST", muse_base() + f"/api/cancel/{local_id}", {}, timeout=5)
            except Exception:
                pass
            update_job(job, status="cancelled", ended=now_ts(),
                       elapsed=round(now_ts() - job["started"], 1))
            return
        time.sleep(3)
        try:
            task = http_json("GET", muse_base() + f"/api/task/{local_id}", timeout=10)
        except Exception:
            continue
        status = task.get("status")
        if status == "succeeded":
            rel = (task.get("file") or "").replace("\\", "/")
            # muse 的 /media/ 按项目目录下的相对路径取文件，形如 /media/out/<id>.mp4
            media = f"{muse_base()}/media/{rel.lstrip('/')}" if rel else None
            file_path = str(Path(CFG["muse"]["dir"]) / rel) if rel else None
            usage = task.get("usage") or {}
            note = f"{task.get('resolution')} · {task.get('duration')}s · {usage.get('output_seconds', '?')} 秒计费"
            update_job(job, status="succeeded", file=file_path,
                       media_url=media, note=note, ended=now_ts(),
                       elapsed=round(now_ts() - job["started"], 1))
            return
        if status in ("failed", "cancelled"):
            update_job(job, status=status, error=task.get("error"), ended=now_ts(),
                       elapsed=round(now_ts() - job["started"], 1))
            return
        update_job(job, note=f"{status} · 已等待 {int(time.time() - job['started'])}s")
    update_job(job, status="failed", error="等待超时（30 分钟）", ended=now_ts())


def run_handoff_job(job: dict) -> None:
    target = job["target"]
    copied = set_clipboard(job["prompt"])
    ok, msg = action_start(target)
    if not ok:
        update_job(job, status="failed", error=msg, ended=now_ts())
        return
    note = "提示词已复制到剪贴板，切到应用里 Ctrl+V 即可"
    if not copied:
        note = "应用已打开；剪贴板写入失败，请手动复制提示词"
    update_job(job, status="handed_off", note=note, ended=now_ts(),
               elapsed=round(now_ts() - job["started"], 1))


def kimi_web_artifact(job_id: str, suffix: str) -> Path:
    folder = OUT_ROOT / "kimiweb"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{job_id}{suffix}"


def run_kimi_web_job(job: dict) -> None:
    """通过 Kimi 浏览器扩展的 /command 直接下发网页任务（navigate/snapshot/screenshot/pdf）。"""
    p = job.get("params") or {}
    mode = (p.get("mode") or "page").strip().lower()
    prompt = (job.get("prompt") or "").strip()
    st = kimi_web_status()
    if not st.get("daemon"):
        # 按官方文档：daemon 没起时自己拉起是安全的（已在跑会 no-op）
        update_job(job, status="running", note="唤醒 WebBridge 守护进程…")
        action_bridge("kimi", True)
        time.sleep(1.0)
        st = kimi_web_status()
    if not st.get("daemon"):
        update_job(job, status="failed", note=None,
                   error=st.get("error") or "WebBridge 守护进程未运行（先在 Kimi 卡片点「启桥」）",
                   ended=now_ts())
        return
    session = "wh" + job["id"][-8:]

    if mode == "raw":
        try:
            spec = json.loads(prompt)
            action = str(spec.get("action") or "").strip()
            args = spec.get("args") or {}
            if not action:
                raise ValueError("缺少 action 字段")
        except Exception as exc:  # noqa: BLE001
            update_job(job, status="failed", note=None,
                       error='raw 模式需要 {"action": ..., "args": {...}} 的 JSON：' + str(exc),
                       ended=now_ts())
            return
        update_job(job, status="running", note=f"执行 {action}")
        ok, data = kimi_command(action, args, session=session, timeout=90)
        if not ok:
            update_job(job, status="failed", note=None, error=kimi_error_text(data), ended=now_ts())
            return
        update_job(job, status="succeeded", output=json.dumps(data, ensure_ascii=False, indent=2)[:20000],
                   ended=now_ts(), elapsed=round(now_ts() - job["started"], 1))
        return

    url = prompt.splitlines()[0].strip() if prompt else ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        url = "https://" + url.lstrip("/")
    try:
        host = urllib.parse.urlparse(url).netloc or url
    except Exception:
        host = url
    group = ("WorkHub · " + host)[:40]

    update_job(job, status="running", note="打开页面…")
    ok, data = kimi_command("navigate", {"url": url, "newTab": True, "group_title": group},
                            session=session)
    if not ok:
        update_job(job, status="failed", note=None, error=kimi_error_text(data), ended=now_ts(),
                   elapsed=round(now_ts() - job["started"], 1))
        return
    page_url = (data or {}).get("url") or url
    files: list[str] = []
    output = ""
    media = None

    if mode in ("page", "text"):
        time.sleep(1.0)
        ok2, snap = kimi_command("snapshot", {"format": "aria", "max_chars": 12000},
                                 session=session, timeout=90)
        if ok2 and isinstance(snap, dict):
            title = snap.get("title") or ""
            text = snap.get("tree_text") or ""
            output = f"{title}\n{page_url}\n\n{text}".strip()[:20000]
            if snap.get("truncated"):
                output += "\n\n（正文较长，已截断；需要全文可用 raw 模式传 cursor 继续）"
        else:
            output = f"{page_url}\n（读取正文失败：{kimi_error_text(snap)}）"

    if mode in ("page", "screenshot"):
        target = kimi_web_artifact(job["id"], ".png")
        ok3, shot = kimi_command("screenshot", {"path": str(target), "format": "png"},
                                 session=session, timeout=90)
        if ok3 and isinstance(shot, dict) and shot.get("path"):
            try:
                rel = Path(shot["path"]).resolve().relative_to(OUT_ROOT.resolve()).as_posix()
                files.append(rel)
                media = f"/artifact?path={urllib.parse.quote(rel)}"
            except Exception:
                output += f"\n\n截图已存到：{shot.get('path')}"

    if mode == "pdf":
        target = kimi_web_artifact(job["id"], ".pdf")
        ok4, pdf = kimi_command("save_as_pdf", {"path": str(target)}, session=session, timeout=120)
        if ok4 and isinstance(pdf, dict) and pdf.get("path"):
            try:
                rel = Path(pdf["path"]).resolve().relative_to(OUT_ROOT.resolve()).as_posix()
                files.append(rel)
                media = f"/artifact?path={urllib.parse.quote(rel)}"
                output = f"{pdf.get('pageTitle') or ''}\n{page_url}\n\nPDF：{rel}"
            except Exception:
                output = f"PDF 已存到：{pdf.get('path')}"
        else:
            update_job(job, status="failed", error=kimi_error_text(pdf), ended=now_ts(),
                       elapsed=round(now_ts() - job["started"], 1))
            return

    note = {"screenshot": "已截图", "pdf": "已导出 PDF", "text": "只读取正文",
            "page": "正文 + 截图"}.get(mode, mode)
    update_job(job, status="succeeded", output=output.strip(), files=files,
               media_url=media, note=note, ended=now_ts(),
               elapsed=round(now_ts() - job["started"], 1))


def kimi_error_text(data) -> str:
    if isinstance(data, dict):
        code = data.get("code") or ""
        msg = data.get("message") or ""
        base = f"{msg}" if msg else json.dumps(data, ensure_ascii=False)[:300]
        if code in ("extension_not_connected", "tool_error") or "no extension connected" in base:
            base += ("。需要：Kimi 侧边栏 → 设置 → 本地远程控制 打开连接"
                     "（ws://127.0.0.1:10086/ws），且 Chrome/Edge 已安装 Kimi 扩展")
        return f"{base}（{code}）" if code else base
    return str(data)[:300]


JOB_RUNNERS = {
    "codex": run_codex_job,
    "muse": run_muse_job,
    "kimi": run_handoff_job,
    "workbuddy": run_handoff_job,
    "kimiweb": run_kimi_web_job,
    "dsh": run_dsh_job,
}


def _chain_context(done: dict) -> str:
    """把上一步的产物与答复整理成交给下一步的上下文。"""
    lines: list[str] = []
    files = done.get("files") or []
    if files:
        lines.append("上一步产出的文件（本机绝对路径，可以直接读）：")
        lines.extend(f"- {OUT_ROOT / rel}" for rel in files[:20])
        if len(files) > 20:
            lines.append(f"- ……共 {len(files)} 个文件")
    else:
        lines.append("上一步没有产出文件。")
    text = (done.get("output") or "").strip()
    if text:
        lines += ["", "上一步的答复（节选）：", text[:1200] + ("…" if len(text) > 1200 else "")]
    return "\n".join(lines)


def chain_prompt(child: dict, done: dict) -> str:
    """下一步的提示词：默认把上一步的产物附在前面，也支持 {files} / {prev} 占位。"""
    base = child.get("ctx_prompt") or child.get("prompt") or ""
    if "{files}" in base or "{prev}" in base:
        joined = "\n".join(str(OUT_ROOT / rel) for rel in (done.get("files") or []))
        return base.replace("{files}", joined or "（上一步没有产出文件）").replace(
            "{prev}", (done.get("output") or "").strip()[:1200])
    head = (f"【接力上下文 · 上一步是 {done.get('name')} 第 {done.get('step')}/"
            f"{done.get('steps_total')} 步】")
    return f"{head}\n{_chain_context(done)}\n\n【你的任务】\n{base}"


def _advance_chain(done: dict) -> None:
    """一个任务结束后，把等它的下一步放出去；上一步没成则整条链跳过。"""
    status = done.get("status")
    if status not in TERMINAL_STATUSES:
        return
    with JOBS_LOCK:
        children = [j for j in JOBS
                    if j.get("depends_on") == done.get("id") and j.get("status") == "waiting"]
    for child in children:
        if status == "succeeded":
            update_job(child, prompt=chain_prompt(child, done), status="queued", started=now_ts())
            _start_job(child)
            continue
        why = {"failed": "失败", "cancelled": "被取消", "interrupted": "被中断",
               "skipped": "被跳过"}.get(status, status)
        update_job(
            child,
            status="skipped",
            ended=now_ts(),
            elapsed=0,
            error=f"上一步（{done.get('name')} 第 {done.get('step')} 步）{why}，这一步没有执行",
        )
        _advance_chain(child)


def _start_job(job: dict) -> dict:
    runner = JOB_RUNNERS.get(job["target"])
    if not runner:
        update_job(job, status="failed", error=f"不支持的目标: {job['target']}", ended=now_ts())
        _advance_chain(job)
        return job

    def wrapped() -> None:
        try:
            runner(job)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            update_job(job, status="failed", error=f"{exc}", ended=now_ts())
        finally:
            try:
                _advance_chain(job)
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    threading.Thread(target=wrapped, daemon=True, name=f"job-{job['id']}").start()
    return job


def dispatch_job(target: str, prompt: str, params: dict | None = None) -> dict:
    return _start_job(new_job(target, prompt, params))


def dispatch_chain(steps: list[dict], outdir: str | None = None,
                   title: str | None = None) -> tuple[str, list[dict]]:
    """按顺序建一串任务：上一步成功才放下一步，产物与答复自动带过去。"""
    chain_id = "c" + uuid.uuid4().hex[:8]
    total = len(steps)
    made: list[dict] = []
    prev: dict | None = None
    for idx, spec in enumerate(steps, 1):
        target = spec["target"]
        prompt = spec["prompt"]
        params = dict(spec.get("params") or {})
        if outdir and target in ("codex", "dsh"):
            params.setdefault("outdir", outdir)
        job = new_job(target, prompt, params)
        update_job(
            job,
            chain_id=chain_id,
            chain_title=title or prompt[:40],
            step=idx,
            steps_total=total,
            ctx_prompt=prompt,
            depends_on=prev["id"] if prev else None,
            status="queued" if idx == 1 else "waiting",
        )
        prev = job
        made.append(job)
    if made:
        _start_job(made[0])
    return chain_id, made


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job or job.get("status") not in ("queued", "running", "waiting"):
        return False
    job["_cancel"] = True
    proc = job.get("_proc")
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
    if job.get("status") in ("queued", "waiting"):
        update_job(job, status="cancelled", ended=now_ts())
        _advance_chain(job)
    return True

