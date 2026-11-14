"""PyInstaller 本机服务入口，所有用户状态保存在客户端指定目录。"""
import os
import sys
import multiprocessing
from pathlib import Path

if __name__=='__main__' and '--history-worker' in sys.argv:
    from backend.frozen_history import worker_main
    worker_main()
    raise SystemExit(0)

if __name__=='__main__':multiprocessing.freeze_support()

import uvicorn

if getattr(sys,'frozen',False):
    os.chdir(Path(sys._MEIPASS))

from backend.app import app

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=int(os.getenv('WANGZHA_PORT','8765')),log_level='warning')
