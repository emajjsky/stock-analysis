"""在本地同源启动工作台；不会安装依赖或连接交易账户。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="启动A股分析工作台（仅本机）")
    parser.add_argument("--build", action="store_true", help="启动前构建前端，需要已安装npm依赖")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认8765")
    args = parser.parse_args()
    if args.port != 8765:
        parser.error("当前会话来源白名单固定为8765，请使用默认端口")
    if args.build:
        result = subprocess.run(["npm.cmd" if sys.platform == "win32" else "npm", "run", "build"], cwd=ROOT / "frontend")
        if result.returncode:
            return result.returncode
    if not (ROOT / "frontend/dist/index.html").exists():
        print("前端尚未构建。先执行：cd frontend；npm ci；npm run build", file=sys.stderr)
        return 1
    try:
        import uvicorn
    except ImportError:
        print("缺少后端依赖。请执行：python -m pip install -r backend/requirements.txt", file=sys.stderr)
        return 1
    print("工作台：http://127.0.0.1:8765  |  Ctrl+C 停止")
    print("先加载本地缓存，后台更新证券目录和行情。模拟交易独立，实盘未开放。")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port, log_level="info", app_dir=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
