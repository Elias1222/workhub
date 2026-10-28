"""与业务无关的工具函数：时间、子进程、HTTP JSON、日志尾巴、缓存。"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import types
import urllib.request
from pathlib import Path

from .procs import CREATE_NO_WINDOW

# ------------------------------------------------------------------ helpers


def now_ts() -> float:
    return time.time()


def fmt_clock(ts: float | None = None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts or now_ts()))


def _decode(raw: bytes | None) -> str:
    """先按 UTF-8 解，失败再退回 GBK；都不行就替换掉坏字节。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def run_hidden(args, timeout=20, cwd=None, env=None, text=True):
    """跑一个隐藏窗口的子进程，返回带 .returncode/.stdout/.stderr 的对象。

    坑：text=True 会让 subprocess 按控制台 locale（cp936）解码，而 kimi-webbridge
    status 的 JSON 里有 UTF-8 破折号，解码线程抛 UnicodeDecodeError 后 stdout 直接
    变成 None —— 于是"守护进程明明在跑"却被判成没运行，探测就报错。这里自己拿
    bytes，先 UTF-8 再 GBK 兜底。
    """
    res = subprocess.run(
        args, cwd=cwd, env=env, timeout=timeout,
        capture_output=True, creationflags=CREATE_NO_WINDOW,
    )
    return types.SimpleNamespace(
        returncode=res.returncode,
        stdout=_decode(res.stdout),
        stderr=_decode(res.stderr),
    )


def http_json(method: str, url: str, payload: dict | None = None, timeout: float = 10) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def tail(path: Path, lines: int = 200) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except Exception as exc:  # noqa: BLE001
        return [f"<读取失败: {exc}>"]
    rows = data.splitlines()
    keep = max(1, min(int(lines or 200), 2000))
    return rows[-keep:]

_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_LOCK = threading.Lock()


def cached(key: str, ttl: float, producer):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = producer()
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
    return value


def invalidate(prefix: str) -> None:
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if k.startswith(prefix)]:
            _CACHE.pop(key, None)

