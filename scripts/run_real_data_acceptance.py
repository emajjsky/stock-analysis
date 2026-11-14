"""启动独立测试服务并验收真实数据，不操作正式8765服务或用户库。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 5173)) == 0:
            raise SystemExit('5173端口已占用，请先结束对应测试服务；不会操作已有服务。')
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    token = uuid.uuid4().hex[:12]
    database = runtime / f'real-data-acceptance-{token}.db'
    logfile = runtime / f'real-data-acceptance-{token}.log'
    env = dict(os.environ, WORKSTATION_DB=str(database))
    for key in ('AGENT_API_BASE', 'AGENT_MODEL', 'AGENT_API_KEY'):
        env.pop(key, None)
    options = {}
    if os.name == 'nt':
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        options['startupinfo'] = info
    process = None
    try:
        with logfile.open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(ROOT / '.venv/Scripts/python.exe'), '-m', 'uvicorn',
                'backend.app:app', '--host', '127.0.0.1', '--port', '5173', '--no-access-log'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **options)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('测试服务提前退出，请查看 ' + str(logfile))
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1', 5173)) == 0:
                        break
                time.sleep(0.2)
            else:
                raise RuntimeError('测试服务启动超时')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/real_data_acceptance.py')], cwd=ROOT)
            if result.returncode:
                return result.returncode
    finally:
        if process and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, **options)
            else:
                process.terminate()
            process.wait(timeout=10)
    (ROOT / 'docs/evidence/real-data-increment/environment.json').write_text(
        json.dumps({'database': str(database), 'server_log': str(logfile),
                    'formal_database_modified': False, 'port': 5173}, indent=2) + '\n', encoding='utf-8')
    print('独立测试服务已停止，正式用户库未改写。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
