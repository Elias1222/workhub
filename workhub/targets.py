"""五个受管目标（Codex / WorkBuddy / DSH / Kimi / Muse）的探测、启停与打开。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .config import CFG, LOG_DIR
from .procs import kill_image, list_pids, spawn
from .util import cached, http_json, invalidate, run_hidden

# ------------------------------------------------------------------ targets


def codex_version() -> str:
    cli = Path(CFG["codex"]["cli"])
    if not cli.exists():
        return ""
    try:
        env = dict(os.environ)
        env["PATH"] = CFG["codex"]["node_dir"] + os.pathsep + env.get("PATH", "")
        out = run_hidden(["cmd", "/c", str(cli), "--version"], timeout=10,
                         cwd=str(cli.parent), env=env)
        text = (out.stdout or out.stderr or "").strip()
        m = re.search(r"(\d+\.\d+\.\d+)", text)
        return m.group(1) if m else text[:40]
    except Exception:
        return ""


def read_version_file(*candidates: Path) -> str:
    for cand in candidates:
        try:
            if cand.is_file():
                txt = cand.read_text(encoding="utf-8", errors="replace").strip()
                if txt:
                    return txt.splitlines()[0][:40]
        except Exception:
            continue
    return ""


def workbuddy_version() -> str:
    exe = Path(CFG["workbuddy"]["exe"])
    return read_version_file(exe.parent / "version")


def _kimi_version() -> str:
    exe = Path(CFG["kimi"]["exe"])
    for pkg in (exe.parent / "resources" / "app" / "package.json",
                exe.parent / "resources" / "app.asar" / "package.json"):
        try:
            if pkg.is_file():
                v = str(json.loads(pkg.read_text(encoding="utf-8", errors="replace")).get("version", ""))
                if v:
                    return v
        except Exception:
            continue
    # 安装包里没有可读的 package.json 时，退回读取 exe 的版本资源
    try:
        out = run_hidden(["powershell", "-NoProfile", "-Command",
                          f"(Get-Item -LiteralPath '{exe}').VersionInfo.ProductVersion"], timeout=15)
        txt = (out.stdout or "").strip()
        if txt:
            ver = txt.splitlines()[0].strip()[:20]
            parts = ver.split(".")
            if len(parts) == 4 and parts[3] == "0":
                ver = ".".join(parts[:3])
            return ver
    except Exception:
        pass
    return ""


def kimi_version() -> str:
    return cached("kimi:version", 300, _kimi_version)


def bridge_status() -> dict:
    exe = Path(CFG["kimi"]["bridge"])
    if not exe.exists():
        return {"running": False, "note": "未安装"}
    try:
        out = run_hidden([str(exe), "status"], timeout=10)
        raw = (out.stdout or "").strip()
        data = json.loads(raw) if raw.startswith("{") else {}
        running = bool(data.get("running"))
        return {"running": running, "pid": data.get("pid"), "note": data.get("note", ""),
                "extension": bool(data.get("extension_connected")),
                "extension_version": data.get("extension_version", ""),
                "version": data.get("version", "")}
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "note": f"查询失败: {exc}"}


def muse_base() -> str:
    return f"http://127.0.0.1:{int(CFG['muse']['port'])}"


def kimi_web_base() -> str:
    return (CFG["kimi"].get("web") or "http://127.0.0.1:10086").rstrip("/")


def kimi_command(action: str, args: dict | None = None, session: str = "workhub",
                 timeout: float = 60) -> tuple[bool, object]:
    """调用 Kimi 浏览器扩展的本地 /command 接口。

    返回 (ok, data)；失败时 data 是 {"code":..., "message":...}。
    """
    body = json.dumps({"action": action, "args": args or {}, "session": session},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(kimi_web_base() + "/command", data=body,
                                 headers={"Content-Type": "application/json"})
    raw = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return False, {"code": "daemon_unreachable", "message": f"连不上 WebBridge 服务：{exc}"}
    try:
        payload = json.loads(raw) if raw.strip().startswith("{") else {}
    except Exception:
        payload = {}
    if payload.get("ok"):
        return True, payload.get("data")
    err = payload.get("error") or {}
    if not err:
        err = {"code": "bad_response", "message": raw[:300] or "（空响应）"}
    return False, err


def kimi_web_status() -> dict:
    """探测 WebBridge 是否可直接下发网页任务（守护进程 + 浏览器扩展两端）。"""
    exe = Path(CFG["kimi"]["bridge"])
    out = {"daemon": False, "port": 10086, "version": "", "extension": False,
           "extension_version": "", "ready": False, "error": "",
           "help": "https://www.kimi.com/products/kimi-webbridge"}
    if exe.exists():
        try:
            res = run_hidden([str(exe), "status"], timeout=10)
            raw = (res.stdout or "").strip()
            data = json.loads(raw) if raw.startswith("{") else {}
            out["daemon"] = bool(data.get("running"))
            out["port"] = int(data.get("port") or 10086)
            out["version"] = data.get("version", "")
            out["extension"] = bool(data.get("extension_connected"))
            out["extension_version"] = data.get("extension_version", "")
            mm = data.get("version_mismatch") or {}
            if mm or data.get("update_available"):
                msg = (mm.get("message") if isinstance(mm, dict) else "") or "扩展与守护进程版本不一致"
                out["update_hint"] = msg
                cmd = (mm.get("command") if isinstance(mm, dict) else "") or ""
                if cmd:
                    out["update_command"] = cmd
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"读取状态失败：{exc}"
    if not out["daemon"]:
        out["error"] = out["error"] or "WebBridge 守护进程未运行（点卡片上的「启桥」，或直接发任务会自动拉起）"
        return out
    if not out["extension"]:
        ver, port, help_url = out["version"], out["port"], out["help"]
        out["error"] = (
            f"守护进程在（{ver}，端口 {port}），但浏览器扩展没连上。两步：① 装好/更新 Kimi 浏览器扩展"
            f"；② Kimi 侧边栏 → 设置 → 本地远程控制 → 打开连接 ws://127.0.0.1:{port}/ws。"
            f"装扩展看 {help_url}"
        )
        return out
    out["ready"] = True
    return out


def muse_ping() -> dict:
    try:
        return http_json("GET", muse_base() + "/api/ping", timeout=3)
    except Exception:
        return {}


def target_state(tid: str) -> dict:
    cfg = CFG[tid]
    if tid == "codex":
        pids = list_pids("codex.exe")
        ver = cached("codex:version", 120, codex_version)
        return {
            "id": "codex", "name": "Codex", "color": "#10a37f", "kind": "桌面端 + CLI",
            "running": bool(pids), "pids": pids[:6], "pid_count": len(pids),
            "version": ver, "headline": "运行中" if pids else "未运行",
            "detail": " · ".join(filter(None, [
                f"{len(pids)} 个进程" if pids else "",
                f"CLI {ver}" if ver else "CLI 未找到",
                "工作目录 " + cfg["cwd"],
            ])),
            "config": cfg["home"] + "\\config.toml",
            "cost": "使用 Codex 账号额度",
            "actions": ["start", "stop", "open", "logs"],
        }
    if tid == "workbuddy":
        pids = list_pids("WorkBuddy.exe")
        ver = workbuddy_version()
        return {
            "id": "workbuddy", "name": "WorkBuddy", "color": "#f0a12e", "kind": "Electron 桌面端",
            "running": bool(pids), "pids": pids[:6], "pid_count": len(pids),
            "version": ver, "headline": "运行中" if pids else "未运行",
            "detail": " · ".join(filter(None, [
                f"{len(pids)} 个进程" if pids else "",
                f"v{ver}" if ver else "",
                "连接器已就绪" if pids else "",
            ])),
            "config": cfg["home"],
            "cost": "办公文档 / 连接器",
            "actions": ["start", "stop", "open", "logs"],
        }
    if tid == "kimi":
        pids = list_pids("Kimi.exe")
        bridge = cached("kimi:bridge", 8, bridge_status)
        ver = kimi_version()
        return {
            "id": "kimi", "name": "Kimi", "color": "#4c8dff", "kind": "桌面端 + WebBridge",
            "running": bool(pids), "pids": pids[:6], "pid_count": len(pids),
            "version": ver, "headline": "运行中" if pids else "未运行",
            "bridge": bridge,
            "detail": " · ".join(filter(None, [
                f"{len(pids)} 个进程" if pids else "",
                f"v{ver}" if ver else "",
                ("WebBridge 在线" if bridge.get("running") else "WebBridge 未运行"),
                ("扩展已连 " + (bridge.get("extension_version") or "")) if bridge.get("extension") else "",
                "扩展未连" if (bridge.get("running") and not bridge.get("extension")) else "",
            ])),
            "config": cfg["home"],
            "cost": "PPT / 资料 / 浏览器任务",
            "actions": ["start", "stop", "open", "logs"],
            "extras": [{"action": "bridge-start", "label": "启桥"},
                        {"action": "bridge-stop", "label": "停桥"}],
        }
    if tid == "dsh":
        pids = list_pids("DeepSeek Harness.exe")
        cli = Path(cfg["cli"])
        has_cli = cli.exists()
        return {
            "id": "dsh", "name": "DSH", "color": "#c94dff", "kind": "我自己 · 无头 CLI + 这个界面",
            "running": bool(pids) or has_cli, "pids": pids[:6], "pid_count": len(pids),
            "version": "", "headline": "在线（你正在对话的就是它）" if pids else "界面进程没找到",
            "detail": " · ".join(filter(None, [
                f"{len(pids)} 个界面进程" if pids else "",
                "无头 CLI 可用" if has_cli else "没找到 dsh.cmd",
                "工作目录 " + cfg["cwd"],
                "与当前对话同一个账号/额度",
            ])),
            "config": cfg["cli"] if has_cli else cfg["cli"] + "（不存在）",
            "cost": "DeepSeek 额度（和你聊天共用）",
            "actions": ["open"],
            "url": cfg["gui"],
        }
    # muse
    ping = muse_ping()
    port = int(cfg["port"])
    ok = bool(ping.get("ok"))
    return {
        "id": "muse", "name": "Muse", "color": "#a67cff", "kind": "MiniMax H3 · 本地服务",
        "running": ok, "pids": [], "pid_count": 0,
        "version": "", "headline": "服务在线" if ok else "服务未运行",
        "detail": " · ".join(filter(None, [
            f"127.0.0.1:{port}" if ok else f"端口 {port} 未监听",
            "MiniMax-H3" if ok else "",
        ])),
        "config": cfg["dir"],
        "cost": "视频生成，按输出秒计费",
        "actions": ["start", "stop", "open", "logs"],
        "url": muse_base(),
    }


# ------------------------------------------------------------------ actions


def action_start(tid: str) -> tuple[bool, str]:
    cfg = CFG[tid]
    if tid == "codex":
        if list_pids("codex.exe"):
            return True, "Codex 已在运行"
        import glob as _glob

        cands = [Path(p) for p in _glob.glob(cfg["exe_glob"])]
        cands = [p for p in cands if p.is_file()]
        if not cands:
            return False, "未找到 Codex 桌面端可执行文件"
        exe = max(cands, key=lambda p: p.stat().st_mtime)
        spawn(str(exe), cwd=str(exe.parent))
        return True, f"已启动 {exe.name}"
    if tid == "workbuddy":
        if list_pids("WorkBuddy.exe"):
            return True, "WorkBuddy 已在运行"
        exe = Path(cfg["exe"])
        if not exe.exists():
            return False, "未找到 WorkBuddy.exe"
        spawn(str(exe), cwd=str(exe.parent))
        return True, "已启动 WorkBuddy"
    if tid == "kimi":
        exe = Path(cfg["exe"])
        if not list_pids("Kimi.exe"):
            if not exe.exists():
                return False, "未找到 Kimi.exe"
            spawn(str(exe), cwd=str(exe.parent))
        bridge = bridge_status()
        if not bridge.get("running") and Path(cfg["bridge"]).exists():
            run_hidden([cfg["bridge"], "start"], timeout=20)
        invalidate("kimi:bridge")
        return True, "已启动 Kimi（并检查 WebBridge）"
    # muse
    if muse_ping().get("ok"):
        return True, "Muse 服务已在线"
    script = Path(cfg["dir"]) / "museui.py"
    if not script.exists():
        return False, (f"Muse 目录里没有 museui.py（当前 {cfg['dir']}）。"
                       "在数据目录的 config.json 里把 muse.dir 指到 Muse 项目。")
    # 注意：Path("") 是 "."，.exists() 恒真 —— 必须先用空串判断，否则会拿 "." 去 CreateProcess
    py = Path(cfg["python"]) if cfg.get("python") else None
    if py is None or not py.exists():
        sibling = Path(sys.executable).with_name("pythonw.exe")
        if sibling.exists():
            py = sibling
        else:
            base = shutil.which("pythonw") or shutil.which("python")
            py = Path(base) if base else Path(sys.executable)
    log = LOG_DIR / "muse.log"
    fh = open(log, "a", encoding="utf-8", buffering=1)
    fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start by WorkHub ===\n")
    spawn(str(py), [str(script), "--no-browser"], cwd=cfg["dir"], stdout=fh)
    for _ in range(40):
        time.sleep(0.5)
        if muse_ping().get("ok"):
            return True, f"Muse 服务已启动（127.0.0.1:{cfg['port']}）"
    return False, "Muse 启动超时，请查看 workhub/logs/muse.log"


def action_stop(tid: str) -> tuple[bool, str]:
    if tid == "codex":
        n = kill_image("codex.exe")
        return (True, f"已关闭 Codex（{n} 个进程）") if n else (True, "Codex 本来就没运行")
    if tid == "workbuddy":
        n = kill_image("WorkBuddy.exe")
        return (True, f"已关闭 WorkBuddy（{n} 个进程）") if n else (True, "WorkBuddy 本来就没运行")
    if tid == "kimi":
        n = kill_image("Kimi.exe")
        bridge = CFG["kimi"]["bridge"]
        if Path(bridge).exists():
            run_hidden([bridge, "stop"], timeout=15)
        return True, f"已关闭 Kimi（{n} 个进程）并停桥"
    try:
        http_json("POST", muse_base() + "/api/quit", {}, timeout=5)
    except Exception:
        pass
    for _ in range(20):
        time.sleep(0.3)
        if not muse_ping().get("ok"):
            return True, "Muse 服务已停止"
    return False, "Muse 未响应退出请求"


def action_open(tid: str) -> tuple[bool, str]:
    if tid == "muse":
        if not muse_ping().get("ok"):
            action_start("muse")
        webbrowser.open(muse_base())
        return True, "已在浏览器打开 Muse"
    if tid == "dsh":
        webbrowser.open(CFG["dsh"]["gui"])
        return True, "已在浏览器打开 DeepSeek Harness"
    if tid == "codex":
        return action_start("codex")
    if tid == "workbuddy":
        return action_start("workbuddy")
    if tid == "kimi":
        return action_start("kimi")
    return False, "未知目标"


def action_bridge(tid: str, on: bool) -> tuple[bool, str]:
    exe = CFG["kimi"]["bridge"]
    if not Path(exe).exists():
        return False, "未安装 kimi-webbridge"
    out = run_hidden([exe, "start" if on else "stop"], timeout=25)
    invalidate("kimi:bridge")
    msg = (out.stdout or out.stderr or "").strip().splitlines()
    return out.returncode == 0, (msg[-1] if msg else ("已启动" if on else "已停止"))


def handle_action(tid: str, action: str) -> tuple[bool, str]:
    if action == "start":
        return action_start(tid)
    if action == "stop":
        return action_stop(tid)
    if action == "restart":
        action_stop(tid)
        time.sleep(0.8)
        return action_start(tid)
    if action == "open":
        return action_open(tid)
    if action == "bridge-start":
        return action_bridge("kimi", True)
    if action == "bridge-stop":
        return action_bridge("kimi", False)
    return False, f"未知动作: {action}"

