"""Windows冻结服务使用固定子命令与JSON行通信，避免spawn继承宿主状态。"""
import json
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor


def worker_main():
    from contextlib import redirect_stdout
    from backend.baostock_history import initialize,download
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    output=sys.stdout
    with redirect_stdout(sys.stderr):initialize()
    for line in sys.stdin:
        try:
            args=json.loads(line)
            if not isinstance(args,list) or len(args)!=3 or any(not isinstance(x,str) for x in args):raise ValueError('历史子任务格式无效')
            with redirect_stdout(sys.stderr):rows,diagnostics=download(args)
            reply={'ok':True,'rows':rows,'diagnostics':diagnostics}
        except Exception as exc:reply={'ok':False,'error':str(exc)[:300] or type(exc).__name__}
        output.write(json.dumps(reply,ensure_ascii=False)+'\n');output.flush()


class Worker:
    def __init__(self):
        self.responses=queue.Queue()
        self.process=subprocess.Popen([sys.executable,'--history-worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=None,text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            env={**os.environ,'PYTHONUNBUFFERED':'1'})
        def read():
            try:
                for line in self.process.stdout:self.responses.put(line)
            finally:self.responses.put(None)
        threading.Thread(target=read,name='history-worker-output',daemon=True).start()

    def call(self,args):
        self.process.stdin.write(json.dumps(list(args))+'\n');self.process.stdin.flush()
        try:line=self.responses.get(timeout=90)
        except queue.Empty:
            self.close();raise ValueError('历史子进程90秒内没有返回；已停止并保留原数据')
        if line is None:raise ValueError('历史子进程已退出，请查看backend.log')
        result=json.loads(line)
        if not result.get('ok'):raise ValueError(result.get('error','历史子进程返回失败'))
        return result['rows'],result['diagnostics']

    def close(self):
        if self.process.poll() is not None:return
        try:
            self.process.stdin.close();self.process.wait(timeout=1)
        except Exception:
            self.process.kill()
            try:self.process.wait(timeout=2)
            except Exception:pass


class FrozenHistoryPool:
    def __init__(self,max_workers):
        self.executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='history-ipc')
        self.local=threading.local();self.workers=[];self.lock=threading.Lock()

    def submit(self,_download,args):
        def call():
            worker=getattr(self.local,'worker',None)
            if worker is None or worker.process.poll() is not None:
                worker=Worker();self.local.worker=worker
                with self.lock:self.workers.append(worker)
            try:return worker.call(args)
            except Exception:
                worker.close();self.local.worker=None;raise
        return self.executor.submit(call)

    def __enter__(self):return self

    def __exit__(self,*_):
        self.executor.shutdown(wait=True,cancel_futures=True)
        for worker in self.workers:worker.close()
