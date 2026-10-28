"""命令行入口：``python -m workhub [--port 8770] [--open]``。"""
from __future__ import annotations

import argparse
import os

from . import __version__
from .config import APP_NAME, CFG, DATA_DIR
from .server import PORT, already_running, serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workhub",
        description="WorkHub — 把 Codex / WorkBuddy / DSH / Kimi / Muse 放进同一个本地控制台。",
        epilog="示例：python -m workhub --port 8800 --open",
    )
    parser.add_argument("--host", default=os.environ.get("WORKHUB_HOST") or CFG.get("host")
                        or "127.0.0.1", help="监听地址（默认只监听回环 127.0.0.1）")
    parser.add_argument("--port", type=int, default=PORT, help="端口（默认 8770，或 WORKHUB_PORT）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--token", default=os.environ.get("WORKHUB_TOKEN") or "",
                        help="访问口令；设置后 /api 与 /artifact 需要 X-WorkHub-Token 头或 ?token=")
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="数据目录（任务历史/日志/产物），默认 %(default)s")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--debug", action="store_true", help="打印每个 HTTP 请求（排错用）")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.debug:
        os.environ["WORKHUB_DEBUG"] = "1"
    os.environ["WORKHUB_DATA"] = str(args.data_dir)

    url = f"http://{args.host}:{args.port}/"
    # 单实例：否则旧进程继续占着端口，新代码永远不生效（"改完重启却没变化"就是这么来的）
    stale = already_running(args.port, args.host)
    if stale:
        print(f"WorkHub 已经在运行（PID {stale.get('pid')}，启动于 {stale.get('started')}）：{url}")
        print("要继续用旧实例就直接打开上面的地址；想换新代码，先结束该 PID 再启动。")
        if args.open:
            import webbrowser

            webbrowser.open(url)
        raise SystemExit(0)

    serve(host=args.host, port=args.port, open_browser=args.open, token=args.token)


if __name__ == "__main__":
    main()
