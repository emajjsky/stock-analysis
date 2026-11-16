"""用户计算任务独立于页面请求；只持久保存进度，完整结果沿用lab_run。"""
from copy import deepcopy
import hashlib
import json
import threading
import time
import uuid

from backend.algorithm_lab import stamp, validate_selections
from backend.lab_research import QUOTE_IDS


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
        config['batch_name']=str(body.get('batch_name',''))[:60]
        config['refresh_inputs']=body.get('refresh_inputs',True) is True
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
            if mode=='intraday' and any(s['id'] not in QUOTE_IDS for s in selections) and len(pool)>20:
                raise ValueError('分时序列算法请指定最多20只股票，运行前逐只更新分时；全市场请先用涨跌幅、换手率、日内位置等报价规则筛选，再将候选带入分时监测。')
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
            if config.get('refresh_inputs') and config['mode']!='daily':
                self._refresh(config,pool)
                if self.cancel_event.is_set():raise InterruptedError('计算已取消，上一份完整结果保留。')
                config['input_errors']=self.current.get('input_errors',[])
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

    def _refresh(self,config,pool):
        if not self.lab.terminal.network_enabled or not self.lab.terminal.config()['enabled']:
            return
        live=[s for s in pool if s['id'].startswith('LIVE.')]
        if not live:return
        errors=[]
        def phase(text):
            with self.lock:self.current.update(status='RUNNING',current=text,updated_at=stamp());self._save()
        if config['mode']=='news':
            phase('更新近期公告目录；该来源为最新目录，非全量历史')
            provider=self.lab.news.provider_factory()
            try:
                items=provider.announcements([s['id'] for s in live] if len(live)<=20 else None)
                with self.store.lock,self.store.db:self.store.put('news_feed',dict(id='lab-user-latest',items=items,updated_at=stamp()))
            except Exception as exc:errors.append(str(exc)[:200])
            finally:provider.close()
        else:
            for start in range(0,len(live),50):
                if self.cancel_event.is_set():return
                phase(f'更新报价 {start+1}～{min(start+50,len(live))} / {len(live)}，随后开始筛查')
                try:
                    result=self.lab.terminal.market_data.sync([s['id'] for s in live[start:start+50]])
                    errors.extend(result.get('errors',[]))
                except Exception as exc:errors.append(str(exc)[:200])
                # 与已有报价轮询共享限速，失败不做紧密重试。
                if self.cancel_event.wait(.5):return
            if any(s['id'] not in QUOTE_IDS for s in config['selections']):
                provider=self.lab.terminal.provider_factory()
                try:
                    for i,sec in enumerate(live):
                        if self.cancel_event.is_set():return
                        phase(f'更新分时序列 {i+1} / {len(live)} · {sec["name"]}')
                        try:
                            series=provider.stock_intraday(sec['id'])
                            with self.store.lock,self.store.db:self.store.put('stock_intraday',{**series,'id':sec['id']})
                        except Exception as exc:errors.append(sec['name']+'：'+str(exc)[:150])
                finally:provider.close()
        with self.lock:
            self.current['input_errors']=list(dict.fromkeys(errors))[:20];self._save()
