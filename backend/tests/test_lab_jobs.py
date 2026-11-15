import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.lab_jobs import LabJobs


def setup(tmp_path):
    app=create_app(tmp_path/'jobs.db',network_enabled=False)
    with app.state.store.db:
        for i in range(3):app.state.store.put('security',dict(id='DEMO.'+str(i),name='股票'+str(i),code=str(i)))
    return app,dict(workspace='screen',scope='saved',mode='daily',selections=[{'id':'momentum'}],combination='all',request_id='request-1')


def test_job_returns_before_calculation_and_progress_survives_new_http_session(tmp_path,monkeypatch):
    app,config=setup(tmp_path);jobs=app.state.lab_jobs
    entered=threading.Event();release=threading.Event();original=app.state.lab.analyze;count=0
    def analyze(*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:entered.set();assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(app.state.lab,'analyze',analyze)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session');client.headers['Origin']='http://127.0.0.1:8765'
        response=client.post('/api/v1/lab/jobs',json=config)
        assert response.status_code==200 and entered.wait(3)
        progress=client.get('/api/v1/lab/jobs').json()['data'][0]
        assert progress['completed']==1 and progress['total']==3 and progress['status']=='RUNNING'
        assert not app.state.store.all('lab_run')
        # 浏览器刷新建立新会话只读同一任务，不触发第二次计算。
        client.cookies.clear();client.get('/api/v1/session')
        assert client.get('/api/v1/lab/jobs').json()['data'][0]['id']==config['request_id']
        duplicate=client.post('/api/v1/lab/jobs',json=config).json()['data']
        assert duplicate['id']==config['request_id']
        assert client.post('/api/v1/lab/jobs',json={**config,'request_id':'request-2'}).status_code==422
        release.set();jobs.thread.join(5);assert not jobs.thread.is_alive()
        finished=client.get('/api/v1/lab/jobs').json()['data'][0]
        assert finished['status']=='SUCCEEDED' and finished['completed']==3
        result=client.get('/api/v1/lab/runs/'+finished['run_id']).json()['data']
        assert result['workspace']=='screen' and len(result['rows'])==3 and count==3
        assert 'rows' not in client.get('/api/v1/lab/runs').json()['data'][0]


def test_cancel_does_not_publish_partial_results_and_keeps_previous_result(tmp_path,monkeypatch):
    app,config=setup(tmp_path);jobs=app.state.lab_jobs;lab=app.state.lab
    previous=lab.run(config);entered=threading.Event();release=threading.Event();original=lab.analyze
    def analyze(*args,**kwargs):entered.set();assert release.wait(5);return original(*args,**kwargs)
    monkeypatch.setattr(lab,'analyze',analyze)
    jobs.start(config);assert entered.wait(3)
    assert jobs.cancel(config['request_id'])['status']=='CANCELLING'
    release.set();jobs.thread.join(5)
    assert jobs.list()[0]['status']=='CANCELLED'
    assert [r['id'] for r in app.state.store.all('lab_run')]==[previous['id']]


def test_failure_is_durable_and_does_not_fake_empty_success(tmp_path,monkeypatch):
    app,config=setup(tmp_path);jobs=app.state.lab_jobs
    def fail(*args,**kwargs):raise ValueError('来源读取失败')
    monkeypatch.setattr(app.state.lab,'analyze',fail)
    jobs.start(config);jobs.thread.join(5)
    assert jobs.list()[0]['status']=='FAILED' and jobs.list()[0]['error']=='来源读取失败'
    assert not app.state.store.all('lab_run')
    assert LabJobs(app.state.lab).list()[0]['status']=='FAILED'


def test_restart_marks_only_incomplete_jobs_interrupted(tmp_path):
    app,config=setup(tmp_path);jobs=app.state.lab_jobs
    jobs.start(config);jobs.thread.join(5)
    complete=jobs.list()[0];orphan=deepcopy(complete);orphan.update(id='orphan',run_id='orphan',status='RUNNING')
    complete['status']='RUNNING'  # 模拟完整结果提交后、状态最终提交前退出。
    with app.state.store.db:
        app.state.store.put('lab_job',complete);app.state.store.put('lab_job',orphan)
    restored={j['id']:j for j in LabJobs(app.state.lab).list()}
    assert restored['orphan']['status']=='INTERRUPTED'
    assert restored[complete['id']]['status']=='SUCCEEDED'


def test_invalid_or_empty_input_never_creates_job(tmp_path):
    app,config=setup(tmp_path);jobs=app.state.lab_jobs
    for body in [{**config,'scope':'watch'},{**config,'workspace':'stock'},{**config,'selections':[None]}]:
        with pytest.raises(ValueError):jobs.start(body)
    assert not jobs.list()
