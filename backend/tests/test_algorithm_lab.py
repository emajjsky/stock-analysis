import copy
from datetime import date,timedelta

import pytest

from backend.app import create_app
from backend.algorithm_lab import compute,validate_selections


def bars(count=80):
    return [dict(time=(date(2025,1,1)+timedelta(days=i)).isoformat(),open=str(10+i*.1),close=str(10+i*.1),high=str(10.2+i*.1),low=str(9.8+i*.1),volume=10000) for i in range(count)]


def test_breakout_excludes_current_from_reference():
    rows=bars();rows[-1].update(close='30',high='31',volume=20000)
    s=validate_selections([{'id':'volume-breakout'}],'daily')[0]
    result=compute(s,rows)
    assert result['matched']
    assert result['value']==2
    assert compute(s,rows[:10])['status']=='MISSING'


@pytest.mark.parametrize('selections,mode',[
    ([{'id':'ma-trend','parameters':{'fast':20,'slow':5}}],'daily'),
    ([{'id':'volume-breakout'}],'intraday'),
    ([{'id':'momentum','parameters':{'window':float('nan')}}],'daily'),
    ([{'id':'momentum','parameters':{'window':5.5}}],'daily'),
    ([{'id':'macd'},{'id':'macd'}],'daily'),
])
def test_parameters_fail_closed(selections,mode):
    with pytest.raises(ValueError):validate_selections(selections,mode)


def test_all_algorithms_preserve_input():
    from backend.algorithm_lab import CATALOG
    rows=bars();original=copy.deepcopy(rows)
    for a in CATALOG:
        if 'daily' in a['supports']:
            out=compute(validate_selections([{'id':a['id']}],'daily')[0],rows)
            assert out['status']=='READY'
            assert out['stance'] in {'WATCH','WAIT','WEAK','RISK','PASS'}
    assert original==rows


def test_monitor_baseline_transition_dedup_and_recovery(tmp_path):
    app=create_app(tmp_path/'test.db',network_enabled=False);store=app.state.store;lab=app.state.lab
    with store.db:
        store.put('security',dict(id='DEMO.A',name='测试',code='000001'))
        store.put('market_snapshot',dict(id='DEMO.A',change_pct='1',source_time='2025-01-01'))
    task=lab.save_task(dict(name='测试任务',scope='custom',security_ids=['DEMO.A'],mode='intraday',selections=[{'id':'price-change','parameters':{'threshold':3}}],enabled=True))
    lab.tick();assert not store.all('lab_event')
    with store.db:
        store.put('market_snapshot',dict(id='DEMO.A',change_pct='4',source_time='2025-01-02'))
        task=store.get('lab_task',task['id']);task.pop('last_checked_at',None);store.put('lab_task',task)
    lab.tick();assert len(store.all('lab_event'))==1
    with store.db:
        task=store.get('lab_task',task['id']);task.pop('last_checked_at',None);store.put('lab_task',task)
    lab.tick();assert len(store.all('lab_event'))==1
    reopened=create_app(tmp_path/'test.db',network_enabled=False)
    assert reopened.state.store.all('lab_task')[0]['enabled']
    assert len(reopened.state.store.all('notification'))==1


def test_combination_and_missing_data(tmp_path):
    app=create_app(tmp_path/'test.db',network_enabled=False);lab=app.state.lab;store=app.state.store
    with store.db:store.put('security',dict(id='DEMO.A',name='测试',code='000001'))
    r=lab.run(dict(scope='saved',selections=[{'id':'momentum'}],mode='daily',combination='all'))
    assert r['skipped']==1 and r['matched']==0
    assert r['rows'][0]['missing']==1
    assert lab.review(r['rows'][0])['status']=='BLOCKED'
