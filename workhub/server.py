"""本地 HTTP 服务：单页界面 + JSON API。只监听回环地址。"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .config import APP_NAME, CFG, DATA_DIR, HOME, LOG_DIR, OUT_ROOT, TEMPLATES
from .jobs import (
    CHAIN_MAX_STEPS,
    CHAIN_TARGETS,
    cancel_job,
    dispatch_chain,
    dispatch_job,
    get_job,
    handback_job,
    job_log_path,
    job_public,
    list_jobs,
    load_jobs,
)
from .targets import handle_action, kimi_web_status, target_state
from .util import fmt_clock, tail

TARGET_IDS = ("codex", "workbuddy", "kimi", "muse", "kimiweb", "dsh")

APP_VERSION = __version__
STATIC_DIR = Path(__file__).resolve().parent / "web"
PORT = int(os.environ.get("WORKHUB_PORT") or CFG.get("port") or 8770)
HOST = os.environ.get("WORKHUB_HOST") or CFG.get("host") or "127.0.0.1"
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
#: 设置后所有 /api 与 /artifact 请求都要带 token（默认不设，本机免认证）
TOKEN = os.environ.get("WORKHUB_TOKEN") or ""
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "")

# ------------------------------------------------------------------ web

STATE_LOCK = threading.Lock()


def state_payload() -> dict:
    targets = [target_state(t) for t in ("codex", "workbuddy", "dsh", "kimi", "muse")]
    return {
        "now": fmt_clock(),
        "hub": {"name": APP_NAME, "version": APP_VERSION, "port": PORT,
                "pid": os.getpid(), "started": STARTED_AT},
        "targets": targets,
        "jobs": list_jobs(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if os.environ.get("WORKHUB_DEBUG"):
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # -- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _text(self, obj: str, code: int = 200) -> None:
        self._send(code, obj.encode("utf-8"), "text/plain; charset=utf-8")

    def _authorized(self, parsed) -> bool:
        """没设 token 就是本机模式；设了就要 header 或 ?token=。"""
        if not TOKEN:
            return True
        header = self.headers.get("X-WorkHub-Token") or ""
        if header == TOKEN:
            return True
        qs = urllib.parse.parse_qs(parsed.query)
        return (qs.get("token") or [""])[0] == TOKEN

    def _guard(self, parsed) -> bool:
        if self._authorized(parsed):
            return True
        self._json({"ok": False, "message": "需要 token（X-WorkHub-Token 头或 ?token=）"}, 401)
        return False

    def _body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            return self._text("ok")
        if path in ("/", "/index.html"):
            try:
                html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            except Exception:
                return self._text("static/index.html 缺失", 500)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json({"ok": True, "name": APP_NAME, "pid": os.getpid(),
                               "version": APP_VERSION, "started": STARTED_AT})
        if path.startswith(("/api/", "/artifact")):
            if not self._guard(parsed):
                return None
        if path == "/api/state":
            return self._json(state_payload())
        if path == "/api/config":
            safe = json.loads(json.dumps(CFG))
            return self._json(safe)
        if path == "/api/logs":
            qs = urllib.parse.parse_qs(parsed.query)
            target = (qs.get("target") or ["codex"])[0]
            lines = int((qs.get("lines") or ["200"])[0] or 200)
            return self._json(self._logs(target, lines))
        if path == "/api/job":
            qs = urllib.parse.parse_qs(parsed.query)
            job = get_job((qs.get("id") or [""])[0])
            return self._json(job_public(job) if job else {"error": "not found"},
                              200 if job else 404)
        if path == "/api/job/log":
            qs = urllib.parse.parse_qs(parsed.query)
            job = get_job((qs.get("id") or [""])[0])
            if not job:
                return self._json({"error": "not found"}, 404)
            lines = int((qs.get("lines") or ["300"])[0] or 300)
            log = job_log_path(job)
            return self._json({"id": job["id"], "path": str(log), "lines": tail(log, lines)})
        if path == "/api/templates":
            return self._json({"templates": TEMPLATES, "out_root": str(OUT_ROOT)})
        if path == "/api/kimi/probe":
            return self._json(kimi_web_status())
        if path == "/artifact":
            qs = urllib.parse.parse_qs(parsed.query)
            return self._artifact((qs.get("path") or [""])[0])
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._text("not found", 404)

    def _artifact(self, rel: str) -> None:
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel:
            return self._text("missing path", 400)
        try:
            target = (OUT_ROOT / rel).resolve()
            target.relative_to(OUT_ROOT.resolve())
        except Exception:
            return self._text("forbidden", 403)
        if not target.is_file():
            return self._text("not found", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in (".md", ".txt", ".log"):
            ctype = "text/plain; charset=utf-8"
        try:
            body = target.read_bytes()
        except Exception as exc:  # noqa: BLE001
            return self._text(f"读取失败: {exc}", 500)
        return self._send(200, body, ctype)

    def _logs(self, target: str, lines: int) -> dict:
        if target == "codex":
            files = sorted((HOME / ".codex" / "log").glob("*.log"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                return {"target": target, "path": None, "lines": ["（暂无日志）"]}
            return {"target": target, "path": str(files[0]), "lines": tail(files[0], lines)}
        if target == "workbuddy":
            p = HOME / ".workbuddy" / "logs" / "daemon.log"
            return {"target": target, "path": str(p), "lines": tail(p, lines)}
        if target == "kimi":
            p = HOME / ".kimi-webbridge" / "logs" / "desktop-daemon.log"
            return {"target": target, "path": str(p), "lines": tail(p, lines)}
        if target == "muse":
            p = LOG_DIR / "muse.log"
            if not p.exists():
                return {"target": target, "path": str(p),
                        "lines": ["（Muse 由桌面图标启动时无控制台日志；可查看 muse/ui_state.json）"]}
            return {"target": target, "path": str(p), "lines": tail(p, lines)}
        return {"target": target, "path": None, "lines": ["未知目标"]}

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            payload = json.loads(self._body().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        if not self._guard(parsed):
            return None
        if path == "/api/action":
            target = payload.get("target", "")
            act = payload.get("action", "")
            if target not in ("codex", "workbuddy", "kimi", "muse"):
                return self._json({"ok": False, "message": "未知目标"}, 400)
            try:
                ok, msg = handle_action(target, act)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                ok, msg = False, str(exc)
            return self._json({"ok": ok, "message": msg})
        if path == "/api/task":
            prompt = (payload.get("prompt") or "").strip()
            targets = payload.get("targets") or []
            if not prompt:
                return self._json({"ok": False, "message": "提示词不能为空"}, 400)
            targets = [t for t in targets if t in TARGET_IDS]
            if not targets:
                return self._json({"ok": False, "message": "请至少选择一个工具"}, 400)
            muse_params = payload.get("muse") or {}
            codex_params = payload.get("codex") or {}
            web_params = payload.get("kimiweb") or {}
            dsh_params = payload.get("dsh") or {}
            params_of = {"muse": muse_params, "codex": codex_params, "kimiweb": web_params,
                         "dsh": dsh_params}
            jobs = [dispatch_job(t, prompt, params_of.get(t)) for t in targets]
            return self._json({"ok": True, "jobs": [job_public(j) for j in jobs]})
        if path == "/api/chain":
            steps = payload.get("steps") or []
            if not isinstance(steps, list) or not (2 <= len(steps) <= CHAIN_MAX_STEPS):
                return self._json(
                    {"ok": False, "message": f"接力需要 2–{CHAIN_MAX_STEPS} 步"}, 400)
            clean: list[dict] = []
            for idx, spec in enumerate(steps, 1):
                if not isinstance(spec, dict):
                    return self._json({"ok": False, "message": f"第 {idx} 步格式不对"}, 400)
                target = (spec.get("target") or "").strip()
                prompt = (spec.get("prompt") or "").strip()
                if target not in CHAIN_TARGETS:
                    return self._json(
                        {"ok": False,
                         "message": f"第 {idx} 步的目标不支持接力：{target or '（空）'}"}, 400)
                if not prompt:
                    return self._json({"ok": False, "message": f"第 {idx} 步没写内容"}, 400)
                clean.append({"target": target, "prompt": prompt,
                              "params": spec.get("params") or {}})
            outdir = (payload.get("outdir") or "").strip() or None
            title = (payload.get("title") or "").strip() or clean[0]["prompt"][:40]
            chain_id, made = dispatch_chain(clean, outdir=outdir, title=title)
            return self._json({"ok": True, "chain_id": chain_id,
                               "jobs": [job_public(j) for j in made]})
        m = re.fullmatch(r"/api/job/([^/]+)/cancel", path)
        if m:
            return self._json({"ok": cancel_job(m.group(1))})
        m = re.fullmatch(r"/api/job/([^/]+)/handback", path)
        if m:
            ok, message = handback_job(
                m.group(1),
                (payload.get("output") or "").strip(),
                (payload.get("note") or "").strip() or None,
            )
            job = get_job(m.group(1))
            status = 200 if ok else (404 if job is None else 400)
            return self._json(
                {"ok": ok, "message": message,
                 "job": job_public(job) if job else None}, status)
        m = re.fullmatch(r"/api/job/([^/]+)/retry", path)
        if m:
            job = get_job(m.group(1))
            if not job:
                return self._json({"ok": False, "message": "任务不存在"}, 404)
            fresh = dispatch_job(job["target"], job["prompt"], job.get("params"))
            return self._json({"ok": True, "job": job_public(fresh)})
        return self._text("not found", 404)


def serve(host: str = "127.0.0.1", port: int | None = None, open_browser: bool = False,
          token: str = "") -> None:
    """起服务并阻塞。单实例守卫在 cli 里做，这里只管监听。"""
    global PORT, HOST, STARTED_AT, TOKEN
    if port:
        PORT = int(port)
    HOST = host
    if token:
        TOKEN = token
    STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
    if HOST not in LOOPBACK_HOSTS and not TOKEN:
        print("拒绝在非回环地址上无口令启动。")
        print("要么用 --host 127.0.0.1（只本机可访问），要么加 --token <口令>。")
        raise SystemExit(2)
    load_jobs()
    url = f"http://{HOST}:{PORT}/"
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"端口 {HOST}:{PORT} 无法监听：{exc}")
        print("用 --port 换一个端口，或先关掉占用该端口的进程。")
        raise SystemExit(2) from exc
    print(f"{APP_NAME} {APP_VERSION} 已启动：{url}")
    print(f"数据目录：{DATA_DIR}" + ("（已启用 token）" if TOKEN else ""))
    print("按 Ctrl+C 退出（不会关掉被管理的应用）。")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        httpd.server_close()



def already_running(port: int, host: str = "127.0.0.1") -> dict | None:
    """端口上是不是已经有一个 WorkHub 在跑？是就返回它的 /api/ping。"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=1.5) as resp:
            info = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        return info if info.get("name") == APP_NAME else None
    except Exception:
        return None
