"""发行数据与启动补数：独立可恢复任务，不把行情目录自动加入用户自选。"""
from __future__ import annotations

import json
import threading
import time
import os
import sys
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from backend.providers import TencentProvider, download_tencent_history


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class HistorySync:
    def __init__(self, store, terminal):
        self.store, self.terminal = store, terminal
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.scheduler = None
        self.scheduler_stop = threading.Event()
        self._coverage_cache = None
        self._coverage_at = 0
        self.progress = dict(status='IDLE', total=0, completed=0, downloaded=0, failed=0,
                             current='', errors=[], started_at=None, finished_at=None)

    def coverage(self):
        if self._coverage_cache is not None and time.monotonic()-self._coverage_at<30:
            return dict(self._coverage_cache)
        with self.store.lock:
            count = self.store.db.execute('SELECT count(*) FROM security_catalog').fetchone()[0]
            if self.store.get('history_release','latest',False):
                row=self.store.db.execute("SELECT coalesce(sum(json_extract(payload,'$.row_count')),0),count(*),min(json_extract(payload,'$.first_date')),max(json_extract(payload,'$.last_date')) FROM documents WHERE kind='history_coverage' AND json_extract(payload,'$.row_count')>0").fetchone()
            else:
                row = self.store.db.execute('SELECT count(*),count(distinct security_id),min(time),max(time) FROM provider_bars').fetchone()
            quality=self.store.db.execute("SELECT count(*) FROM documents WHERE kind='history_coverage' AND json_array_length(json_extract(payload,'$.excluded_dates'))>0").fetchone()[0]
        self._coverage_cache=dict(catalog_count=count, history_count=row[1], rows=row[0], first_date=row[2], last_date=row[3],quality_warning_count=quality)
        self._coverage_at=time.monotonic()
        return dict(self._coverage_cache)

    def status(self):
        with self.lock:
            p = {**self.progress, 'errors': self.progress['errors'][-20:]}
        return {**p, 'coverage': self.coverage(), 'scope': '沪深在市证券 / 来源可提供的完整未复权日线',
                'limitations': ['不含退市全样本、北交所和完整历史分钟线', '上游缺失或停牌不补造日线；失败保留缓存']}

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return dict(accepted=False, reason='已有补数任务')
            self.stop_event.clear()
            self.progress = dict(status='RUNNING', total=0, completed=0, downloaded=0, failed=0,
                                 current='检查证券目录', errors=[], started_at=stamp(), finished_at=None)
            self.thread = threading.Thread(target=self.run, name='history-bootstrap', daemon=True)
            self.thread.start()
        return dict(accepted=True)

    def stop(self,*,shutdown=False):
        self.stop_event.set()
        if shutdown:self.scheduler_stop.set()

    def start_scheduler(self):
        def loop():
            attempted=None
            while not self.scheduler_stop.wait(60):
                china=datetime.now(timezone(timedelta(hours=8)))
                if not self.terminal.network_enabled or not self.terminal.config()['enabled'] or china.hour<16:
                    continue
                day=china.date().isoformat()
                if attempted==day:continue
                if self.thread and self.thread.is_alive():continue
                # 来源核对真实交易日期；周末/节假日不猜测存在新日线。
                attempted=day
                self.start()
        self.scheduler=threading.Thread(target=loop,name='history-close-check',daemon=True)
        self.scheduler.start()

    def _one(self, security, target):
        sid = security['id']
        with self.store.lock:
            existing = self.store.db.execute('SELECT max(time) FROM provider_bars WHERE security_id=?', (sid,)).fetchone()[0]
            state = self.store.get('history_coverage', sid, False) or {}
        if state.get('target') == target and state.get('status') == 'READY':
            return 0
        if state.get('provider_id')=='baostock':
            self.start()
            return 0
        client = TencentProvider(timeout=12)
        try:
            use_proxy = True
            def get(url, params):
                nonlocal use_proxy
                if use_proxy:
                    url=url.replace('https://web.ifzq.gtimg.cn/appstock/','https://proxy.finance.qq.com/ifzqgtimg/appstock/')
                response = client.client.get(url, params=params)
                response.raise_for_status()
                time.sleep(0.3)
                return response.content
            diagnostics=[]
            # 已完成全历史的证券仅拉最新一段；首次与中断恢复继续完整分页。
            if state.get('full') and existing:
                from backend.providers import parse_tencent_daily, KLINE_URL
                from datetime import date,timedelta
                code=sid.removeprefix('LIVE.').replace('.','').lower()
                rows=parse_tencent_daily(get(KLINE_URL,{'param':f'{code},day,,,2000,'}),sid.removeprefix('LIVE.'),today=date.fromisoformat(target)+timedelta(days=1),tolerate_source_errors=True,diagnostics=diagnostics)
                if rows and existing < rows[0]['time']:
                    rows = download_tencent_history(get, sid.removeprefix('LIVE.'),tolerate_source_errors=True,diagnostics=diagnostics)
            else:
                rows = download_tencent_history(get, sid.removeprefix('LIVE.'),tolerate_source_errors=True,diagnostics=diagnostics)
            if not rows:
                raise ValueError('来源没有返回完成日线')
            if rows[-1]['time']>target:rows=[r for r in rows if r['time']<=target]
            added = 0
            with self.store.lock, self.store.db:
                for row in rows:
                    values = ('tencent', sid, row['time'], row['open'], row['high'], row['low'], row['close'],
                              row['volume'], row.get('amount'), row.get('source', '腾讯财经公开日线 / 未复权'),
                              row['source_time'], row['fetched_at'], row['raw_hash'], row['adjustment'])
                    cursor = self.store.db.execute('INSERT OR IGNORE INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
                    added += cursor.rowcount
                    old = self.store.db.execute('SELECT open,high,low,close,volume FROM provider_bars WHERE provider_id=? AND security_id=? AND time=?',values[:3]).fetchone()
                    if old and tuple(Decimal(str(x)) for x in old) != tuple(Decimal(str(x)) for x in values[3:8]):
                        raise ValueError('来源修订与旧值冲突，保留已存历史，请检查数据')
                previous_diagnostics=state.get('diagnostics',[]) if state.get('full') else []
                diagnostics=list({(d.get('date'),d.get('action')):d for d in previous_diagnostics+diagnostics}.values())
                summary=self.store.db.execute("SELECT count(*),min(time) FROM provider_bars WHERE provider_id='tencent' AND security_id=?",(sid,)).fetchone()
                self.store.put('history_coverage', dict(id=sid, status='READY', target=target,
                    last_date=rows[-1]['time'],first_date=summary[1],row_count=summary[0],full=True, checked_at=stamp(),diagnostics=diagnostics,
                    excluded_dates=[d['date'] for d in diagnostics if d['action']=='INVALID_SOURCE_ROW_SKIPPED']))
                self.store.put('market_history', dict(id=sid, history_complete=True, checked_at=stamp()))
            return added
        finally:
            client.close()

    def _store_baostock(self,sec,target,rows,diagnostics):
        sid=sec['id'];values=[('baostock',sid,r['time'],r['open'],r['high'],r['low'],r['close'],r['volume'],r['amount'],r['source'],r['source_time'],r['fetched_at'],r['raw_hash'],'NONE') for r in rows]
        with self.store.lock,self.store.db:
            # 同一来源已存值不覆盖；新版与旧值有冲突时整只事务回滚。
            self.store.db.execute('CREATE TEMP TABLE IF NOT EXISTS incoming_history(time TEXT PRIMARY KEY,open TEXT,high TEXT,low TEXT,close TEXT,volume INTEGER)')
            self.store.db.execute('DELETE FROM incoming_history')
            self.store.db.executemany('INSERT INTO incoming_history VALUES(?,?,?,?,?,?)',[(r['time'],r['open'],r['high'],r['low'],r['close'],r['volume']) for r in rows])
            conflict=self.store.db.execute("SELECT 1 FROM provider_bars b JOIN incoming_history i ON b.time=i.time WHERE b.provider_id='baostock' AND b.security_id=? AND (CAST(b.open AS REAL)!=CAST(i.open AS REAL) OR CAST(b.high AS REAL)!=CAST(i.high AS REAL) OR CAST(b.low AS REAL)!=CAST(i.low AS REAL) OR CAST(b.close AS REAL)!=CAST(i.close AS REAL) OR b.volume!=i.volume) LIMIT 1",(sid,)).fetchone()
            if conflict:raise ValueError('BaoStock来源修订与旧值冲突，保留原数据')
            before=self.store.db.total_changes
            self.store.db.executemany('INSERT OR IGNORE INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
            added=self.store.db.total_changes-before
            previous=self.store.get('history_coverage',sid,False) or {}
            old=previous.get('diagnostics',[]) if previous.get('provider_id')=='baostock' else []
            diagnostics=list({(d.get('date'),d.get('action')):d for d in old+diagnostics}.values())
            summary=self.store.db.execute("SELECT count(*),min(time) FROM provider_bars WHERE provider_id='baostock' AND security_id=?",(sid,)).fetchone()
            self.store.put('history_coverage',dict(id=sid,status='READY',provider_id='baostock',target=target,last_date=rows[-1]['time'],full=True,
                checked_at=stamp(),first_date=summary[1],row_count=summary[0],pagination_verified=True,diagnostics=diagnostics,excluded_dates=[d['date'] for d in diagnostics if d['action']=='INVALID_SOURCE_ROW_SKIPPED']))
            self.store.put('market_history',dict(id=sid,history_complete=True,checked_at=stamp()))
        return added

    def _run_baostock(self,securities):
        from backend.baostock_history import initialize, download
        from datetime import date
        from multiprocessing import get_context
        china=datetime.now(timezone(timedelta(hours=8)))
        end=(china.date() if china.hour>=16 else china.date()-timedelta(days=1)).isoformat()
        workers=max(1,min(8,int(os.getenv('HISTORY_WORKERS','4'))))
        if getattr(sys,'frozen',False):
            from backend.frozen_history import FrozenHistoryPool
            executor=FrozenHistoryPool(workers)
        else:
            executor=ProcessPoolExecutor(max_workers=workers,mp_context=get_context('spawn'),initializer=initialize)
        with executor as pool:
            # 冻结worker自身在90秒关闭超时连接，外层稍后等待以保留具体错误。
            index,_=pool.submit(download,('LIVE.SH.000001',end,(date.fromisoformat(end)-timedelta(days=30)).isoformat())).result(timeout=100 if getattr(sys,'frozen',False) else 150)
            target=index[-1]['time']
            with self.lock:self.progress.update(total=len(securities),target_date=target,provider='BaoStock 0.9.4',current='逐只检查历史覆盖')
            pending={};iterator=iter(securities)
            def schedule():
                while len(pending)<workers*2 and not self.stop_event.is_set():
                    sec=next(iterator,None)
                    if sec is None:break
                    state=self.store.get('history_coverage',sec['id'],False) or {}
                    if state.get('status')=='READY' and state.get('target')==target and (state.get('provider_id')!='baostock' or state.get('pagination_verified') or state.get('last_date')==target):
                        with self.lock:self.progress['completed']+=1
                        continue
                    start=state['last_date'] if state.get('provider_id')=='baostock' and state.get('full') else '1990-01-01'
                    pending[pool.submit(download,(sec['id'],target,start))]=sec
            schedule();failures=0
            while pending:
                future=next(as_completed(pending));sec=pending.pop(future)
                try:
                    rows,diagnostics=future.result()
                    added=self._store_baostock(sec,target,rows,diagnostics);failures=0
                    error=None
                except Exception as exc:
                    added=0;failures+=1;error=sec['code']+'：'+(str(exc) or type(exc).__name__)[:160]
                with self.lock:
                    self.progress['completed']+=1;self.progress['downloaded']+=added
                    self.progress['current']=sec['name']+' '+sec['code']
                    if error:self.progress['failed']+=1;self.progress['errors'].append(error)
                    checkpoint=dict(id='latest',**self.progress)
                if checkpoint['completed']%25==0:
                    with self.store.lock,self.store.db:self.store.put('history_bootstrap',checkpoint)
                if failures>=8:self.stop_event.set()
                schedule()

    def run(self):
        try:
            with self.store.lock:
                entry=self.store.db.execute('SELECT payload FROM security_catalog LIMIT 1').fetchone()
            fresh=False
            if entry:
                try:
                    updated=datetime.fromisoformat(json.loads(entry[0]).get('updated_at','').replace('Z','+00:00'))
                    fresh=updated.astimezone(timezone(timedelta(hours=8))).date()==datetime.now(timezone(timedelta(hours=8))).date()
                except (ValueError,TypeError):pass
            if not fresh:self.terminal.catalog.sync()
            with self.store.lock:
                securities = [json.loads(row[0]) for row in self.store.db.execute('SELECT payload FROM security_catalog ORDER BY code')]
            if not securities:
                raise ValueError('证券目录不可用，请联网重试')
            with self.lock:self.progress['current']='核对来源最近完成交易日'
            if os.getenv('HISTORY_PROVIDER','baostock')=='baostock':
                self._run_baostock(securities)
                with self.lock:self.progress['status']='PARTIAL' if self.progress['failed'] else 'CANCELLED' if self.stop_event.is_set() else 'SUCCEEDED'
                return
            # 真实指数交易日期作为本轮参考，不用周一至周五猜测节假日。
            client = TencentProvider(timeout=12)
            try:
                rows = download_tencent_history(lambda url, params: client.client.get(url.replace('https://web.ifzq.gtimg.cn/appstock/','https://proxy.finance.qq.com/ifzqgtimg/appstock/'), params=params).content,
                                               'SH.000001', allow_index=True)
                target = rows[-1]['time']
            finally:
                client.close()
            with self.lock:
                self.progress.update(total=len(securities), target_date=target, current='逐只检查历史覆盖')
            def work(sec):
                if self.stop_event.is_set():
                    return sec, None, None
                try:
                    return sec, self._one(sec, target), None
                except Exception as exc:
                    if '501' in str(exc) or '429' in str(exc):
                        self.stop_event.set()
                    return sec, 0, str(exc)[:160]
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='history') as pool:
                futures = [pool.submit(work, sec) for sec in securities]
                for future in as_completed(futures):
                    sec, added, error = future.result()
                    if added is None:
                        continue
                    with self.lock:
                        self.progress['completed'] += 1
                        self.progress['downloaded'] += added
                        self.progress['current'] = sec['name'] + ' ' + sec['code']
                        if error:
                            self.progress['failed'] += 1
                            self.progress['errors'].append(sec['code'] + '：' + error)
                        if self.progress['completed'] % 25 == 0:
                            with self.store.lock, self.store.db:
                                self.store.put('history_bootstrap', dict(id='latest', **self.progress))
            with self.lock:
                self.progress['status'] = 'PARTIAL' if self.progress['failed'] else 'CANCELLED' if self.stop_event.is_set() else 'SUCCEEDED'
        except Exception as exc:
            with self.lock:
                self.progress.update(status='FAILED')
                self.progress['errors'].append((str(exc) or type(exc).__name__)[:200])
        finally:
            self._coverage_at=0
            with self.lock:
                self.progress['finished_at'] = stamp()
                with self.store.lock, self.store.db:
                    self.store.put('history_bootstrap', dict(id='latest', **self.progress))
