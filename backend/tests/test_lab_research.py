from datetime import datetime,timedelta,timezone
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.algorithm_lab import CATALOG,compute,validate_selections,stamp
from backend.lab_research import diagnose,event_assessment,session_context
from backend.tests.test_algorithm_lab import bars


def test_expanded_rules_use_their_defined_reference_window():
    rows=bars(80);rows[-1].update(close='40',high='41',volume=1000)
    def run(a,parameters=None):return compute(validate_selections([{'id':a,'parameters':parameters or {}}],'daily')[0],rows)
    assert run('donchian')['matched']
    assert run('volume-contraction')['value']==pytest.approx(.1)
    assert run('drawdown')['value']==0
    assert not run('range-position',{'lower':0,'upper':20})['matched']
    assert not run('volatility',{'max_pct':.1})['matched']
    assert len(CATALOG)==20


def test_new_cross_requires_transition_not_existing_uptrend():
    rows=bars(80)
    result=compute(validate_selections([{'id':'ma-cross'}],'daily')[0],rows)
    assert not result['matched']
    for row in rows[-6:]:row['close']='5'
    rows[-1]['close']='100'
    result=compute(validate_selections([{'id':'ma-cross'}],'daily')[0],rows)
    assert result['matched']


def test_intraday_vwap_requires_real_average_and_quote_filters_need_fields():
    s=validate_selections([{'id':'intraday-vwap'}],'intraday')[0]
    assert compute(s,[dict(time='10:00',close='11')],mode='intraday')['status']=='MISSING'
    assert compute(s,[dict(time='10:00',close='11',average_price='10')],mode='intraday')['matched']
    q=validate_selections([{'id':'quote-range'}],'intraday')[0]
    assert compute(q,[],dict(price='11',high='12',low='10'),mode='intraday')['value']==50
    assert compute(q,[],dict(price='11',high='11',low='11'),mode='intraday')['status']=='MISSING'


def setup(tmp_path):
    app=create_app(tmp_path/'research.db',network_enabled=False);store=app.state.store
    with store.db:
        store.put('security',dict(id='DEMO.A',name='测试',code='000001'))
        store.put('market_snapshot',dict(id='DEMO.A',change_pct='4',source_time=stamp()))
    return app


def test_partial_missing_is_counted_and_not_misreported_as_zero(tmp_path):
    app=setup(tmp_path)
    result=app.state.lab.run(dict(scope='saved',mode='intraday',selections=[{'id':'price-change'},{'id':'macd'}]))
    assert result['skipped']==1 and result['skipped_all']==0 and result['eligible']==0
    assert result['rows'][0]['missing']==1
    assert result['coverage_status']=='NONE'


def test_snapshot_is_frozen_and_has_all_input_hash_fields(tmp_path,monkeypatch):
    app=setup(tmp_path);lab=app.state.lab;store=app.state.store
    with store.db:store.put('security',dict(id='DEMO.B',name='测试B',code='000002'));store.put('market_snapshot',dict(id='DEMO.B',change_pct='4',source_time=stamp()))
    original=lab.analyze
    def analyze(*args,**kwargs):
        with store.db:store.put('market_snapshot',dict(id='DEMO.B',change_pct='-9',source_time=stamp()))
        return original(*args,**kwargs)
    monkeypatch.setattr(lab,'analyze',analyze)
    r=lab.run(dict(scope='saved',mode='intraday',selections=[{'id':'price-change'}]))
    assert r['matched']==2 and r['data_cutoff'] and r['source_from'] and r['config_hash']


def test_batches_survive_more_than_fifteen_and_rename_preserves_result(tmp_path):
    app=setup(tmp_path);lab=app.state.lab
    config=dict(scope='saved',mode='daily',selections=[{'id':'momentum'}])
    first=lab.run(config)
    for _ in range(17):lab.run(config)
    assert len(app.state.store.all('lab_run'))==18
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session');client.headers['Origin']='http://127.0.0.1:8765'
        assert client.patch('/api/v1/lab/runs/'+first['id'],json={'batch_name':'午间复核'}).status_code==200
        restored=client.get('/api/v1/lab/runs/'+first['id']).json()['data']
        assert restored['batch_name']=='午间复核' and restored['rows']==first['rows']


def test_legacy_summary_migrates_partial_missing_consistently(tmp_path):
    app=setup(tmp_path);store=app.state.store
    run=app.state.lab.run(dict(scope='saved',mode='intraday',selections=[{'id':'price-change'},{'id':'macd'}]))
    old=deepcopy(run);old.pop('stats_version');old.pop('rows');old['skipped']=0
    with store.db:store.put('lab_run_summary',old)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        summary=client.get('/api/v1/lab/runs').json()['data'][0]
        assert summary['skipped']==1 and summary['stats_version']==2


def test_minute_algorithms_fail_before_creating_full_market_job(tmp_path):
    app=setup(tmp_path)
    with app.state.store.db:
        for i in range(21):app.state.store.put('security',dict(id='DEMO.'+str(i),name=str(i),code=str(i)))
    with pytest.raises(ValueError,match='最多20只'):
        app.state.lab_jobs.start(dict(scope='saved',mode='intraday',selections=[{'id':'macd'}]))
    assert not app.state.lab_jobs.list()


def test_news_missing_is_unknown_and_recent_title_is_not_buy_signal(tmp_path):
    app=setup(tmp_path);lab=app.state.lab;store=app.state.store
    config=dict(scope='saved',mode='news',selections=[{'id':'announcement'}])
    assert lab.run(config)['rows'][0]['missing']==1
    with store.db:
        store.put('news_feed',dict(id='test',updated_at=stamp(),items=[dict(id='a',kind='announcement',title='回购计划',published_at=stamp(),securities=[{'id':'DEMO.A'}],url='https://example.com')]))
    row=lab.run(config)['rows'][0]
    assert row['action']=='公告待核实'
    assert row['news_evidence'][0]['direction']=='偏正面线索'
    assert row['news_evidence'][0]['evidence_type']=='TITLE_ONLY'
    assert event_assessment({'title':'关于日常关联交易的公告'})['direction']=='方向不确定'


def test_stock_diagnosis_has_price_context_but_no_order(tmp_path):
    app=setup(tmp_path);store=app.state.store
    with store.db:
        for b in bars(80):store.db.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',('DEMO.A',b['time'],b['open'],b['high'],b['low'],b['close'],b['volume'],'100000','fixture','DEMO'))
    run=app.state.lab.run(dict(scope='custom',security_ids=['DEMO.A'],workspace='stock',mode='daily',selections=[{'id':'ma-trend'}]))
    d=run['rows'][0]['diagnosis'];assert d['status']=='READY' and d['support']<d['price']<d['resistance']
    assert len(d['metrics'])>=6 and d['conditions'] and 'orders' not in d


def test_market_session_is_not_assumed_to_be_continuously_trading():
    assert session_context(datetime(2026,11,16,4,tzinfo=timezone.utc))['session']=='午间休市'
    assert session_context(datetime(2026,11,16,6,tzinfo=timezone.utc))['session']=='下午盘'
    assert session_context(datetime(2026,11,15,6,tzinfo=timezone.utc))['session']=='休市'


def test_daily_filters_unfinished_same_day_and_intraday_filters_future(tmp_path):
    app=setup(tmp_path);lab=app.state.lab;store=app.state.store;now=datetime.now(timezone.utc)
    sid='LIVE.SZ.000001';sec=dict(id=sid,name='平安银行',code='000001')
    with store.db:
        store.put('security',sec)
        store.put('stock_intraday',dict(id=sid,points=[{'time':(now-timedelta(seconds=30)).isoformat().replace('+00:00','Z'),'value':'10'},{'time':(now+timedelta(days=1)).isoformat().replace('+00:00','Z'),'value':'100'}]))
    r=lab.run(dict(scope='custom',security_ids=[sid],mode='intraday',selections=[{'id':'intraday-vwap'}]))
    assert r['rows'][0]['price']=='10'


def test_refresh_downloads_quote_then_minute_and_retains_cache_on_failure(tmp_path,monkeypatch):
    from types import SimpleNamespace
    app=setup(tmp_path);lab=app.state.lab;jobs=app.state.lab_jobs;calls=[]
    sec=dict(id='LIVE.SZ.000001',name='平安银行',code='000001')
    monkeypatch.setattr(lab.terminal,'network_enabled',True)
    monkeypatch.setattr(lab.terminal,'config',lambda:{'enabled':True})
    monkeypatch.setattr(lab.terminal.market_data,'sync',lambda ids:calls.append('quote') or {'errors':[]})
    def minute(sid):
        calls.append('minute')
        return dict(points=[dict(time=stamp(),value='10',average_price='9')])
    provider=SimpleNamespace(stock_intraday=minute,close=lambda:calls.append('close'))
    monkeypatch.setattr(lab.terminal,'provider_factory',lambda:provider)
    jobs.current=dict(id='refresh-test');config=dict(mode='intraday',selections=[{'id':'intraday-vwap'}])
    jobs._refresh(config,[sec])
    assert calls==['quote','minute','close']
    old=app.state.store.get('stock_intraday',sec['id'])
    def fail(sid):raise ValueError('来源不可用')
    provider.stock_intraday=fail
    jobs._refresh(config,[sec])
    assert app.state.store.get('stock_intraday',sec['id'])==old
    assert '来源不可用' in jobs.current['input_errors'][0]
    calls.clear();jobs.cancel_event.set();jobs._refresh(config,[sec]);assert not calls


def test_new_minute_rule_monitor_refreshes_series_and_batch_hash_tracks_pool(tmp_path,monkeypatch):
    from types import SimpleNamespace
    app=setup(tmp_path);lab=app.state.lab;store=app.state.store;calls=[]
    sec=dict(id='LIVE.SZ.000001',name='平安银行',code='000001')
    with store.db:store.put('security',sec)
    monkeypatch.setattr(lab.terminal,'network_enabled',True)
    monkeypatch.setattr(lab.terminal,'config',lambda:{'enabled':True})
    monkeypatch.setattr(lab.terminal.market_data,'sync',lambda ids:{'errors':[]})
    monkeypatch.setattr(lab.terminal,'provider_factory',lambda:SimpleNamespace(stock_intraday=lambda sid:calls.append(sid) or {'points':[]},close=lambda:None))
    lab.refresh_inputs(dict(id='m',scope='custom',security_ids=[sec['id']],mode='intraday',selections=[{'id':'intraday-vwap'}]))
    assert calls==[sec['id']]
    config=dict(scope='saved',mode='daily',selections=[{'id':'momentum'}])
    first=lab.run(config)
    with store.db:store.put('security',dict(id='DEMO.NEW',name='新增',code='000002'))
    assert lab.run(config)['config_hash']!=first['config_hash']


def test_quote_only_batch_displays_quote_price_not_older_minute_price(tmp_path):
    app=setup(tmp_path);s=app.state.store
    with s.db:
        s.put('market_snapshot',dict(id='DEMO.A',price='12',change_pct='4',source_time=stamp()))
        s.put('stock_intraday',dict(id='DEMO.A',points=[dict(time='2020-01-01T01:30:00Z',value='3')]))
    row=app.state.lab.run(dict(scope='saved',mode='intraday',selections=[{'id':'price-change'}]))['rows'][0]
    assert row['price']=='12'
