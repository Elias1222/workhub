"""平台相关的小工具：进程枚举 / 结束、后台启动、剪贴板、端口探测。

Windows 走 ctypes/ToolhelpAPI（不依赖 tasklist 的本地化输出）；macOS / Linux
用 ``ps`` 与 ``os.kill``。全部失败都返回空值而不是抛异常，界面据此显示"未找到"。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = os.sys.platform == "darwin"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
DETACHED_PROCESS = 0x00000008 if IS_WINDOWS else 0


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def _list_pids_windows(image: str) -> list[int]:
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap == ctypes.c_void_p(-1).value:
        return []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    pids: list[int] = []
    target = image.lower()
    try:
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() == target:
                    pids.append(int(entry.th32ProcessID))
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return pids


def _list_pids_unix(image: str) -> list[int]:
    try:
        out = subprocess.run(["ps", "-eo", "pid=,comm="], capture_output=True,
                             timeout=10, text=True).stdout
    except Exception:
        return []
    want = Path(image).name.lower()
    if want.endswith(".exe"):
        want = want[:-4]
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, comm = parts
        name = Path(comm).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name == want and pid.isdigit():
            pids.append(int(pid))
    return pids


def list_pids(image: str) -> list[int]:
    """按镜像名枚举进程 PID。"""
    if IS_WINDOWS:
        return _list_pids_windows(image)
    return _list_pids_unix(image)


def kill_image(image: str, graceful_wait: float = 4.0) -> int:
    """先温和结束，等 graceful_wait 秒还活着就强杀；返回处理过的进程数。"""
    pids = list_pids(image)
    if not pids:
        return 0
    if IS_WINDOWS:
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        deadline = time.time() + graceful_wait
        while time.time() < deadline and list_pids(image):
            time.sleep(0.3)
        for pid in list_pids(image):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        return len(pids)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + graceful_wait
    while time.time() < deadline and list_pids(image):
        time.sleep(0.3)
    for pid in list_pids(image):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return len(pids)


def spawn(exe: str, args: list[str] | None = None, cwd: str | None = None,
          stdout=None) -> subprocess.Popen:
    """后台启动一个 GUI/服务进程，不占终端、不继承控制台。"""
    if not Path(exe).exists():
        raise FileNotFoundError(f"可执行文件不存在：{exe}")
    if cwd and not Path(cwd).is_dir():
        raise FileNotFoundError(f"工作目录不存在：{cwd}")
    cmd = [exe] + (args or [])
    kwargs: dict = {
        "cwd": cwd,
        "stdout": stdout or subprocess.DEVNULL,
        "stderr": subprocess.STDOUT if stdout else subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def set_clipboard(text: str) -> bool:
    """把文本塞进系统剪贴板（Windows / macOS / Linux 各走各的命令）。"""
    try:
        if IS_WINDOWS:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::InputEncoding = [Text.Encoding]::UTF8; "
                 "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=text.encode("utf-8"), capture_output=True, timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
            return proc.returncode == 0
        if IS_MACOS:
            proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                                  capture_output=True, timeout=15)
            return proc.returncode == 0
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
            exe = shutil.which(cmd[0])
            if not exe:
                continue
            proc = subprocess.run([exe, *cmd[1:]], input=text.encode("utf-8"),
                                  capture_output=True, timeout=15)
            if proc.returncode == 0:
                return True
        return False
    except Exception:
        return False


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, int(port))) == 0
