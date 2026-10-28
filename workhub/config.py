"""配置、默认路径与数据目录。

运行时数据（任务历史、日志、产物）默认放在 ``~/.workhub``，可用环境变量
``WORKHUB_DATA`` 覆盖；配置文件是 ``<data>/config.json``（可选，键可只写要覆盖的）。

默认值只是"猜一个大概率存在的位置"，猜不到也不影响启动——对应卡片会显示
"未找到"，在 ``config.json`` 里改路径即可。所有路径都能用环境变量覆盖。
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
from pathlib import Path

APP_NAME = "WorkHub"

HOME = Path.home()
IS_WINDOWS = os.name == "nt"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or (HOME / "AppData" / "Local"))
MAC_APPS = Path("/Applications")

# ------------------------------------------------------------------ 目录

def _data_dir() -> Path:
    env = os.environ.get("WORKHUB_DATA")
    if env:
        return Path(env).expanduser().resolve()
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or (HOME / ".workhub"))
        return (base / "WorkHub") if base.name != "WorkHub" else base
    return HOME / ".workhub"


DATA_DIR = _data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"
CONFIG_FILE = DATA_DIR / "config.json"

#: 任务默认工作目录（Codex / DSH 没指定交付目录时用）
WORKSPACE = Path(os.environ.get("WORKHUB_WORKDIR") or Path.cwd()).resolve()


def _which(*names: str) -> str:
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    return ""


def _first(*candidates: Path) -> str:
    """返回第一个存在的路径；都不存在就返回第一个候选（便于界面提示"未找到"）。"""
    for cand in candidates:
        try:
            if cand and Path(cand).exists():
                return str(cand)
        except OSError:
            continue
    return str(candidates[0]) if candidates else ""


def _exe(rel: str) -> str:
    return rel + (".exe" if IS_WINDOWS else "")


# ------------------------------------------------------------------ 默认值

DEFAULTS: dict = {
    "port": 8770,
    "host": "127.0.0.1",
    "codex": {
        "cli": os.environ.get("WORKHUB_CODEX_CLI")
               or _first(Path(HOME / ".node" / "node-v26.12.1-win-x64" / _exe("codex")),
                         Path(_which("codex") or "/nonexistent")),
        "node_dir": os.environ.get("WORKHUB_CODEX_NODE_DIR")
                    or str(HOME / ".node" / "node-v26.12.1-win-x64"),
        "exe_glob": str(LOCALAPPDATA / "OpenAI" / "Codex" / "bin" / "*" / _exe("codex")),
        "home": str(HOME / ".codex"),
        "cwd": str(WORKSPACE),
    },
    "workbuddy": {
        "exe": os.environ.get("WORKHUB_WORKBUDDY_EXE")
               or _first(LOCALAPPDATA / "Programs" / "WorkBuddy" / _exe("WorkBuddy"),
                         MAC_APPS / "WorkBuddy.app" / "Contents" / "MacOS" / "WorkBuddy"),
        "home": str(HOME / ".workbuddy"),
    },
    "kimi": {
        "exe": os.environ.get("WORKHUB_KIMI_EXE")
               or _first(LOCALAPPDATA / "Programs" / "Kimi" / _exe("Kimi"),
                         MAC_APPS / "Kimi.app" / "Contents" / "MacOS" / "Kimi"),
        "bridge": os.environ.get("WORKHUB_KIMI_BRIDGE")
                  or _first(HOME / ".kimi-webbridge" / "bin" / _exe("kimi-webbridge"),
                            Path(_which("kimi-webbridge") or "/nonexistent")),
        "home": str(HOME / ".kimi-webbridge"),
        "slides": str(HOME / ".kimi-work" / "bin" / "kimi-tools" / _exe("kimi-slides")),
        "web": os.environ.get("WORKHUB_KIMI_WEB") or "http://127.0.0.1:10086",
    },
    "muse": {
        "dir": os.environ.get("WORKHUB_MUSE_DIR")
               or _first(WORKSPACE / "muse", WORKSPACE.parent / "muse", HOME / "muse"),
        "port": int(os.environ.get("WORKHUB_MUSE_PORT") or 8765),
        "python": "",
    },
    "dsh": {
        "cli": os.environ.get("WORKHUB_DSH_CLI")
               or str(LOCALAPPDATA / "Programs" / "DeepSeek Harness" / "resources"
                      / "runtime" / "cli" / "bin" / "dsh.cmd"),
        "exe": os.environ.get("WORKHUB_DSH_EXE")
               or str(LOCALAPPDATA / "Programs" / "DeepSeek Harness" / "DeepSeek Harness.exe"),
        "js": os.environ.get("WORKHUB_DSH_JS")
              or str(LOCALAPPDATA / "Programs" / "DeepSeek Harness" / "resources"
                     / "app.asar" / "dsh" / "node_modules" / "@deepseek-ai"
                     / "dsh-desktop-host" / "lib" / "cli.js"),
        "creds": os.environ.get("WORKHUB_DSH_CREDS")
                 or str(HOME / ".dsh" / ".credentials.yaml"),
        "cwd": str(WORKSPACE),
        "gui": os.environ.get("WORKHUB_DSH_GUI") or "http://127.0.0.1:49870",
    },
    "out": {
        "root": os.environ.get("WORKHUB_OUT") or str(DATA_DIR / "out"),
    },
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            traceback.print_exc()
    return cfg


CFG = load_config()
OUT_ROOT = Path(CFG["out"]["root"]).expanduser()
OUT_ROOT.mkdir(parents=True, exist_ok=True)

# 快捷模板：一键把「要做什么」写成合适的提示词，并把成品收进统一目录
TEMPLATES = [
    {
        "id": "image", "name": "出图", "desc": "插图 / 封面 / 配图，成品进 out/",
        "targets": ["codex"], "prefix": "image",
        "example": "做 3 张「替换成你的主题」的配图：16:9，扁平插画风，配色干净；"
                   "用 Python(Pillow) 或 SVG 生成并导出 PNG。",
    },
    {
        "id": "doc", "name": "文档", "desc": "说明文档 / 周报，成品进 out/",
        "targets": ["codex"], "prefix": "doc",
        "example": "写一份《替换成你的主题》的说明文档：标题、目录、分小节，3000 字以内，"
                   "同时给出 Markdown 源文件。",
    },
    {
        "id": "deck", "name": "PPT", "desc": "汇报稿：Codex 备资料 + Kimi 做页",
        "targets": ["codex", "kimi"], "prefix": "deck",
        "example": "做一份《替换成你的主题》的 8 页汇报 PPT：封面 / 背景 / 现状 / 方案 / "
                   "数据 / 排期 / 风险 / 结论。",
    },
    {
        "id": "code", "name": "代码", "desc": "改代码 / 跑脚本，直接留在工作区",
        "targets": ["codex"], "prefix": "",
        "example": "实现「替换成你的需求」，改完跑一遍自测，最后说明改了哪些文件、为什么。",
    },
    {
        "id": "video", "name": "视频", "desc": "Muse 出片（按输出秒计费）",
        "targets": ["muse"], "prefix": "video",
        "example": "一只橘猫在窗台上伸懒腰，晨光穿过纱帘，镜头缓慢推进。",
    },
]
