"""使用独立临时库与本进程拥有的5173服务验收Agent证据页面。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
PORT=int(os.environ.get('AGENT_EVIDENCE_PORT','5174'))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',PORT))==0:
            raise SystemExit(f'{PORT}已占用，不操作已有服务')
    runtime=ROOT/'.runtime'
    runtime.mkdir(exist_ok=True)
    token=uuid.uuid4().hex
    database=runtime/f'agent-evidence-acceptance-{token}.db'
    logfile=runtime/f'agent-evidence-acceptance-{token}.log'
    env=dict(os.environ,WORKSTATION_DB=str(database),AGENT_EVIDENCE_PORT=str(PORT),WORKSTATION_TEST_PORT=str(PORT))
    for key in ('AGENT_API_BASE','AGENT_MODEL','AGENT_API_KEY'):
        env.pop(key,None)
    options={}
    if os.name=='nt':
        info=subprocess.STARTUPINFO()
        info.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow=subprocess.SW_HIDE
        options['startupinfo']=info
    process=None
    result=None
    try:
        with logfile.open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn',
                'backend.app:app','--host','127.0.0.1','--port',str(PORT),'--no-access-log'],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,**options)
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError('验收服务提前退出，请查看'+str(logfile))
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',PORT))==0:
                        break
                time.sleep(0.2)
            else:
                raise RuntimeError('验收服务启动超时')
            result=subprocess.run([sys.executable,str(ROOT/'scripts/agent_evidence_browser.py')],cwd=ROOT,env=env)
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    out=ROOT/'docs/evidence/agent-evidence-increment'
    out.mkdir(parents=True,exist_ok=True)
    (out/'environment.json').write_text(json.dumps(dict(database=str(database),server_log=str(logfile),
        formal_database_modified=False,port=PORT,server_stopped=True),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result.returncode if result else 1


if __name__=='__main__':
    raise SystemExit(main())
