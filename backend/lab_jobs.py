"""用户计算任务独立于页面请求；只持久保存进度，完整结果沿用lab_run。"""
from copy import deepcopy
import hashlib
import json
import threading
import time
import uuid

from backend.algorithm_lab import stamp, validate_selections


ACTIVE={'QUEUED','RUNNING','CANCELLING'}


class LabJobs:
    def __init__(self,lab):
        self.lab,self.store=lab,lab.store
        self.lock=threading.RLock()
        self.cancel_event=threading.Event()
        self.thread=None
        self.current=None
        # 应用重启不假装上次计算仍在进行，也不自动重跑用户任务。
        with self.store.lock,self.store.db:
            for job in self.store.all('lab_job'):
                if job['status'] in ACTIVE:
                    result=self.store.get('lab_run',job['run_id'],False)
                    if result:job.update(status='SUCCEEDED',completed=result['total'],matched=result['matched'],skipped=result['skipped'],finished_at=result['finished_at'],error=None)
                    else:job.update(status='INTERRUPTED',finished_at=stamp(),error='上次计算因客户端退出而中断，已有完整结果保留；可重新运行。')
                    self.store.put('lab_job',job)

    def list(self):
        with self.lock:
            jobs=sorted(self.store.all('lab_job'),key=lambda j:j['started_at'],reverse=True)[:20]
            if self.current:
                jobs=[deepcopy(self.current)]+[j for j in jobs if j['id']!=self.current['id']]
            return jobs

    def start(self,body):
        mode=body.get('mode','daily');scope=body.get('scope','watch')
        workspace=body.get('workspace','screen')
        if workspace not in {'screen','stock','monitor'}:raise ValueError('计算场景无效')
        selections=validate_selections(body.get('selections'),mode)
        combination=body.get('combination','all')
        if combination not in {'all','any'}:raise ValueError('组合条件无效')
        config=dict(mode=mode,scope=scope,workspace=workspace,selections=selections,combination=combination,security_ids=body.get('security_ids',[]))
        jid=body.get('request_id') or uuid.uuid4().hex
        if not isinstance(jid,str) or len(jid)>80 or not jid.replace('-','').isalnum():raise ValueError('任务请求标识无效')
        digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        with self.lock:
            previous=self.store.get('lab_job',jid,False)
            if previous:
                if previous['request_hash']!=digest:raise ValueError('同一请求标识对应不同配置')
                return previous
            if self.current and self.current['status'] in ACTIVE:raise ValueError('已有计算在后台运行，请先查看或取消当前任务。')
            pool=self.lab.universe(scope,config['security_ids'])
            if not pool:raise ValueError('股票池为空，请先选择股票或添加自选。')
            if workspace=='stock' and (scope!='custom' or len(pool)!=1):raise ValueError('个股分析请选择一只股票')
            job=dict(id=jid,run_id=jid,status='QUEUED',workspace=workspace,config=config,request_hash=digest,
                     started_at=stamp(),updated_at=stamp(),finished_at=None,total=len(pool),completed=0,matched=0,skipped=0,current='等待计算',error=None)
            with self.store.lock,self.store.db:
                self.store.put('lab_job',job)
                old=sorted(self.store.all('lab_job'),key=lambda j:j['started_at'],reverse=True)
                for item in old[20:]:self.store.db.execute("DELETE FROM documents WHERE kind='lab_job' AND id=?",(item['id'],))
            self.current=job;self.cancel_event.clear()
            self.thread=threading.Thread(target=self._execute,args=(deepcopy(config),pool),name='user-algorithm-job',daemon=True)
            self.thread.start()
            return deepcopy(job)

    def _save(self):
        with self.store.lock,self.store.db:self.store.put('lab_job',self.current)

    def _execute(self,config,pool):
        checkpoint=0
        def progress(completed,total,current,matched,skipped):
            nonlocal checkpoint
            with self.lock:
                self.current.update(status='CANCELLING' if self.cancel_event.is_set() else 'RUNNING',completed=completed,total=total,current=current,matched=matched,skipped=skipped,updated_at=stamp())
                if completed==0 or completed%25==0 or time.monotonic()-checkpoint>1:
                    self._save();checkpoint=time.monotonic()
        status,error,current='SUCCEEDED',None,'计算完成'
        try:
            self.lab.run(config,run_id=self.current['id'],progress=progress,cancelled=self.cancel_event.is_set,prepared_pool=pool)
        except InterruptedError as exc:
            status,error,current='CANCELLED',str(exc),'已取消'
        except Exception as exc:
            status,error,current='FAILED',(str(exc) or type(exc).__name__)[:300],'计算失败'
        finally:
            with self.lock:
                self.current.update(status=status,error=error,current=current,finished_at=stamp(),updated_at=stamp());self._save()

    def cancel(self,jid):
        with self.lock:
            if self.current and self.current['id']==jid and self.current['status'] in ACTIVE:
                self.cancel_event.set();self.current['status']='CANCELLING';self._save()
                return deepcopy(self.current)
            job=self.store.get('lab_job',jid)
            return job

    def stop(self):
        self.cancel_event.set()
