import copy
import json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.algorithm_lab import validate_selections
from backend.jev_decision import decide


@pytest.mark.parametrize('value',[None,'macd',[None],[{'id':[]}],[{'id':'rsi','parameters':[]}],[{'id':'rsi','parameters':{'period':True}}]])
def test_untrusted_algorithm_input_is_validation_error(value):
    with pytest.raises(ValueError):validate_selections(value,'daily')


def test_live_stale_quote_is_visible_but_cannot_trigger(tmp_path):
    app=create_app(tmp_path/'test.db',network_enabled=False);s=app.state.store;lab=app.state.lab
    sid='LIVE.SH.600519'
    with s.db:
        s.put('security',dict(id=sid,name='测试',code='600519'))
        s.put('market_snapshot',dict(id=sid,change_pct='1',source_time='2020-01-01T01:30:00Z'))
    task=lab.save_task(dict(name='过期验证',mode='intraday',scope='custom',security_ids=[sid],selections=[{'id':'price-change'}],enabled=True))
    lab.tick();assert not s.all('lab_event')
    assert '非今日' in s.get('lab_task',task['id'])['error']
    with s.db:s.put('market_snapshot',dict(id=sid,change_pct='5',source_time='2020-01-02T01:30:00Z'))
    task=s.get('lab_task',task['id']);task.pop('last_checked_at',None)
    with s.db:s.put('lab_task',task)
    lab.tick();assert not s.all('notification')
    row=lab.run(dict(scope='custom',security_ids=[sid],mode='intraday',selections=[{'id':'price-change'}]))['rows'][0]
    assert row['data_status']=='STALE' and not row['matched']
    assert row['results'][0]['matched']  # 保留原始规则证据，但过期输入不进入候选。
    assert row['data_as_of']=='2020-01-02T01:30:00Z'


def test_edit_pause_and_delete_do_not_resurrect_or_trigger_old_condition(tmp_path,monkeypatch):
    app=create_app(tmp_path/'a.db',network_enabled=False);lab=app.state.lab;s=app.state.store
    with s.db:
        s.put('security',dict(id='DEMO.A',code='A',name='测试'))
        s.put('market_snapshot',dict(id='DEMO.A',change_pct='5'))
    task=lab.save_task(dict(mode='intraday',scope='custom',security_ids=['DEMO.A'],selections=[{'id':'price-change'}],enabled=True))
    lab.tick();assert len(s.all('lab_monitor_state'))==1
    task=lab.save_task({**task,'enabled':False});assert not s.all('lab_monitor_state')
    task=lab.save_task({**task,'enabled':True});lab.tick();assert not s.all('lab_event')
    with s.db:
        task=s.get('lab_task',task['id']);task.pop('last_checked_at',None);s.put('lab_task',task)
    def remove(_):
        with s.db:s.db.execute("DELETE FROM documents WHERE kind='lab_task'")
    monkeypatch.setattr(lab,'refresh_inputs',remove)
    lab.tick();assert not s.all('lab_task')
    assert not s.all('lab_run')  # 自动检查不写手动运行记录。


@pytest.mark.parametrize('support,conflict,status,allow',[(.9,.1,'SUCCEEDED',True),(.6,.1,'SUCCEEDED',False),(.95,.9,'SUCCEEDED',False),('0.9',.1,'FAILED',False),(.9,True,'FAILED',False)])
def test_jev_official_contract_and_fail_closed(monkeypatch,support,conflict,status,allow):
    monkeypatch.setenv('JEV_API_KEY','unit-test-key')
    calls=[]
    def post(url,**kw):
        calls.append((url,kw))
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'model':'jev-1.13.0','answers':{'support':{'type':'noul','noul':support},'conflict':{'type':'noul','noul':conflict}}})
    monkeypatch.setattr('backend.jev_decision.httpx.post',post)
    result=decide({'missing':0,'data_status':'CURRENT','matched':True})
    assert result['status']==status and result['allow_review']==allow
    assert calls[0][0]=='https://api.typesafe.ai/v1/systemone'
    assert calls[0][1]['json']['questions']['support']['type']=='noul'
    assert decide({'missing':1})['status']=='BLOCKED' and len(calls)==1


def test_history_source_selection_transaction_and_quality(tmp_path):
    app=create_app(tmp_path/'a.db',network_enabled=False);s=app.state.store;sync=app.state.history_sync
    sec=dict(id='LIVE.SH.600519',name='测试',code='600519')
    row=dict(time='2026-11-13',open='10',high='12',low='9',close='11',volume=100,amount='1100',source='BaoStock',source_time='2026-11-13T07:00:00Z',fetched_at='now',raw_hash='hash')
    assert sync._store_baostock(sec,'2026-11-13',[row],[{'date':'2020-01-01','action':'INVALID_SOURCE_ROW_SKIPPED'}])==1
    assert sync._store_baostock(sec,'2026-11-13',[row],[])==0
    with s.db:s.db.execute('INSERT INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('tencent',sec['id'],'2026-11-13','2','3','1','2',100,None,'Tencent','x','x','x','NONE'))
    assert len(s.bars(sec['id']))==1 and s.bars(sec['id'])[0]['close']=='11'
    with pytest.raises(ValueError):sync._store_baostock(sec,'2026-11-13',[{**row,'close':'10'}],[])
    assert s.bars(sec['id'])[0]['close']=='11'
    assert sync.coverage()['quality_warning_count']==1


def test_new_api_auth_records_and_models_without_key(tmp_path,monkeypatch):
    monkeypatch.delenv('JEV_API_KEY',raising=False)
    monkeypatch.delenv('TYPESAFE_API_KEY',raising=False)
    app=create_app(tmp_path/'api.db',network_enabled=False)
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        assert c.post('/api/v1/lab/run',json={}).status_code==403
        c.get('/api/v1/session');c.headers['Origin']='http://127.0.0.1:8765'
        assert len(c.get('/api/v1/lab/catalog').json()['data'])==20
        model=c.get('/api/v1/lab/model-status').json()['data']
        assert model['jev']['configured'] is False and 'key' not in model['jev']
        bad=c.post('/api/v1/lab/run',json={'selections':[None]})
        assert bad.status_code==422
        s=app.state.store
        with s.db:s.put('security',dict(id='DEMO.A',name='测试',code='A'))
        r=c.post('/api/v1/lab/run',json={'scope':'saved','selections':[{'id':'momentum'}]}).json()['data']
        assert r['skipped']==1 and len(c.get('/api/v1/lab/runs').json()['data'])==1
        d=c.post('/api/v1/lab/decision',json={'run_id':r['id'],'security_id':'DEMO.A'})
        assert d.json()['data']['status']=='UNAVAILABLE'


def test_news_window_removal_is_not_new_announcement(tmp_path):
    app=create_app(tmp_path/'news.db',network_enabled=False);s=app.state.store;lab=app.state.lab
    with s.db:s.put('security',dict(id='DEMO.A',name='测试',code='A'))
    task=lab.save_task(dict(mode='news',scope='custom',security_ids=['DEMO.A'],selections=[{'id':'announcement'}],enabled=True))
    def feed(ids):
        with s.db:
            s.put('news_feed',dict(id='feed',updated_at='2026-11-15T00:00:00Z',items=[dict(id=x,title='测试公告'+x,kind='announcement',securities=[{'id':'DEMO.A'}],published_at='2026-11-14') for x in ids]))
            current=s.get('lab_task',task['id']);current.pop('last_checked_at',None);s.put('lab_task',current)
    feed(['1','2']);lab.tick();assert not s.all('lab_event')
    feed(['2']);lab.tick();assert not s.all('lab_event')
    feed(['2','3']);lab.tick();assert len(s.all('lab_event'))==1
    assert s.all('lab_event')[0]['row']['news_evidence'][0]['evidence_type']=='TITLE_ONLY'


def test_automatic_model_budget_is_persistent_and_bounded(tmp_path,monkeypatch):
    app=create_app(tmp_path/'budget.db',network_enabled=False);s=app.state.store;lab=app.state.lab
    with s.db:s.put('security',dict(id='DEMO.A',name='测试',code='A'))
    task=lab.save_task(dict(mode='intraday',scope='custom',security_ids=['DEMO.A'],selections=[{'id':'price-change'}],enabled=True,auto_review=True))
    calls=[]
    monkeypatch.setattr(lab,'review',lambda row:calls.append(row['input_hash']) or {'status':'SUCCEEDED','summary':'测试'})
    row=dict(security=dict(id='DEMO.A',name='测试',code='A'),matched=True,news_ids=[],data_status='LOCAL',data_note='本地',action='关注机会')
    for i in range(5):
        monkeypatch.setattr(lab,'run',lambda config,persist=False,i=i:{'rows':[{**row,'input_hash':str(i)}]})
        with s.db:
            s.put('lab_monitor_state',dict(id=task['id']+':DEMO.A',matched=False))
            current=s.get('lab_task',task['id']);current.pop('last_checked_at',None);s.put('lab_task',current)
        lab.tick()
    assert len(calls)==4 and len(s.all('lab_event'))==5
    assert s.all('lab_model_budget')[0]['count']==4
    assert any('上限' in e.get('model_note','') for e in s.all('lab_event'))


def test_baostock_silent_next_failure_cannot_be_complete(monkeypatch):
    import baostock as bs
    from backend import baostock_history as history
    monkeypatch.setattr(history,'ensure_session',lambda:None)
    monkeypatch.setattr('baostock.common.contants.BAOSTOCK_PER_PAGE_COUNT',2)
    class Result:
        code='sh.600519';adjustflag='3';frequency='d';error_code='0';error_msg='';cur_row_num=0
        data=[['2026-11-12','10','12','9','11','100','1100','1'],['2026-11-13','10','12','9','11','100','1100','1']]
        def next(self):return self.cur_row_num<len(self.data)
        def get_row_data(self):
            row=self.data[self.cur_row_num];self.cur_row_num+=1;return row
    monkeypatch.setattr(bs,'query_history_k_data_plus',lambda *args,**kwargs:Result())
    with pytest.raises(ValueError,match='最后分页未确认'):history.download(('LIVE.SH.600519','2026-11-13','1990-01-01'))


def test_release_export_excludes_personal_records_and_guards_coverage(tmp_path):
    import sqlite3
    from scripts.release_manifest import export
    app=create_app(tmp_path/'source.db',network_enabled=False);s=app.state.store
    app.state.terminal.catalog.import_rows([dict(code='600519',name='测试',market=1)],minimum=1)
    sec=dict(id='LIVE.SH.600519',name='测试',code='600519')
    row=dict(time='2026-11-13',open='10',high='12',low='9',close='11',volume=100,amount='1100',source='BaoStock',source_time='2026-11-13T07:00:00Z',fetched_at='now',raw_hash='hash')
    app.state.history_sync._store_baostock(sec,'2026-11-13',[row],[])
    with s.db:
        s.put('account',dict(id='private',name='private-content-no-ship'))
        s.put('lab_task',dict(id='private-task',name='private-content-no-ship'))
    report=export(tmp_path/'source.db',tmp_path/'public.db',tmp_path/'manifest.json')
    assert report['status']=='COMPLETE' and report['completed_check_count']==1
    assert report['row_count']==1 and report['history_count']==1
    assert b'private-content-no-ship' not in (tmp_path/'public.db').read_bytes()
    with sqlite3.connect(tmp_path/'public.db') as dest:
        kinds={r[0] for r in dest.execute('SELECT kind FROM documents')}
        assert 'account' not in kinds and 'lab_task' not in kinds
        assert 'history_release' in kinds
        state=json.loads(dest.execute("SELECT payload FROM documents WHERE kind='history_coverage'").fetchone()[0])
        assert state['row_count']==1
    with s.db:s.db.execute("DELETE FROM documents WHERE kind='history_coverage'")
    with pytest.raises(ValueError,match='覆盖未完成'):export(tmp_path/'source.db',tmp_path/'rejected.db',tmp_path/'rejected.json')
    assert not (tmp_path/'rejected.db').exists()


def test_released_coverage_uses_metadata_without_scanning_all_bars(tmp_path):
    app=create_app(tmp_path/'a.db',network_enabled=False);s=app.state.store
    with s.db:
        s.put('history_release',dict(id='latest',metadata_counts=True))
        s.put('history_coverage',dict(id='LIVE.SH.600519',row_count=5000,first_date='2001-08-27',last_date='2026-11-13'))
    queries=[];original=s.db
    class Recording:
        def execute(self,sql,*args):queries.append(sql);return original.execute(sql,*args)
    s.db=Recording()
    stats=app.state.history_sync.coverage();s.db=original
    assert stats['rows']==5000 and stats['history_count']==1
    assert not any('FROM provider_bars' in q for q in queries)


def test_baostock_closed_connection_and_deadline_fail_instead_of_hanging(monkeypatch):
    from backend.baostock_history import DeadlineSocket
    class Socket:
        def settimeout(self,value):pass
        def send(self,data):return len(data)
        def recv(self,count):return b''
    guarded=DeadlineSocket(Socket());guarded.send(b'query')
    with pytest.raises(ConnectionError,match='提前关闭'):guarded.recv(8192)
    guarded.deadline=0
    with pytest.raises(TimeoutError,match='45秒'):guarded.recv(8192)


def test_input_hash_includes_indicator_warmup_before_last_260_bars(tmp_path):
    from datetime import date
    app=create_app(tmp_path/'warmup.db',network_enabled=False);store=app.state.store
    sid='DEMO.WARMUP';sec=dict(id=sid,code='WARMUP',name='预热测试')
    rows=[]
    for i in range(300):
        day=(date(2020,1,1)+timedelta(days=i)).isoformat()
        price=str(10+i/100)
        rows.append((sid,day,price,price,price,price,100,'1000','测试','DEMO'))
    with store.db:store.db.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
    selections=validate_selections([{'id':'rsi','parameters':{'period':60}}],'daily')
    before=app.state.lab.analyze(sec,selections)
    with store.db:store.db.execute('UPDATE bars SET close=? WHERE security_id=? AND time=?',('20',sid,rows[0][1]))
    after=app.state.lab.analyze(sec,selections)
    assert before['input_hash']!=after['input_hash']


@pytest.mark.parametrize('flag,allowed',[('',True),('3',True),('1',False),('2',False)])
def test_baostock_omitted_adjustment_echo_is_recorded_but_other_adjustment_rejected(monkeypatch,flag,allowed):
    import baostock as bs
    from backend import baostock_history as history
    monkeypatch.setattr(history,'ensure_session',lambda:None)
    monkeypatch.setattr(history.time,'sleep',lambda _:None)
    class Result:
        code='sh.600519';frequency='d';error_code='0';error_msg='';cur_row_num=0;adjustflag=flag
        data=[['2026-11-13','10','12','9','11','100','1100','1']]
        def next(self):return self.cur_row_num<len(self.data)
        def get_row_data(self):
            row=self.data[self.cur_row_num];self.cur_row_num+=1;return row
    def query(*args,**kwargs):
        assert kwargs['adjustflag']=='3'
        return Result()
    monkeypatch.setattr(bs,'query_history_k_data_plus',query)
    if not allowed:
        with pytest.raises(ValueError,match='复权身份不符'):history.download(('LIVE.SH.600519','2026-11-13','1990-01-01'))
    else:
        rows,diagnostics=history.download(('LIVE.SH.600519','2026-11-13','1990-01-01'))
        assert len(rows)==1
        assert bool(diagnostics)==(flag=='')
