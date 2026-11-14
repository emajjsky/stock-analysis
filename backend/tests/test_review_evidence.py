"""研究资料进入复核的时点、引用、修订、请求期间变化及重启验证。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.providers import ProviderError

SID = 'SH.600519'
BASE = '/api/v1'
ORIGIN = 'http://127.0.0.1:8765'


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


class Source:
    def __init__(self, received, revision=1, fail=False):
        self.received, self.revision, self.fail = received, revision, fail

    def company(self, sid):
        if self.fail:
            raise ProviderError('UPSTREAM', '测试来源故障')
        return dict(security_id=sid, source='离线研究测试源',
                    source_url='https://data.eastmoney.com/', received_at=self.received,
                    raw_hash=hashlib.sha256(str(self.revision).encode()).hexdigest(),
                    business='研究测试公司版本' + str(self.revision), facts=[])

    def close(self):
        pass


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENT_API_BASE', raising=False)
    monkeypatch.delenv('AGENT_MODEL', raising=False)
    monkeypatch.delenv('AGENT_API_KEY', raising=False)
    path = tmp_path / 'review-evidence.db'
    app = create_app(path)
    instant = datetime.now(timezone.utc)
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('security', dict(id=SID, code='600519', name='离线研究测试股',
            exchange='SSE', sector='测试', status='IMPORTED_UNVERIFIED'))
        for index in range(30):
            day = (instant.date() - timedelta(days=31-index)).isoformat()
            price = str(10 + index)
            app.state.store.db.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                (SID, day, price, str(11+index), str(9+index), price, 10000, '100000', '离线测试', 'IMPORTED'))
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        client.get(BASE + '/session')
        app.state.automation.stop()
        data(client.post(BASE + '/monitors', json=dict(security_id=SID, algorithm_id='trend-cross-v1',
            parameters={'fast':5, 'slow':20}, enabled=True, agent_mode='FILTER')))
        public = data(client.post(BASE + '/signals/run', json={}))['signals'][0]
        signal = app.state.store.get('signal', public['id'])
        # 此测试构造有效信号时窗，只验证复核协议，不是市场时点或行情有效性证明。
        signal.update(kind='BUY', confirmed_at=stamp(instant-timedelta(minutes=5)),
                      valid_until=stamp(instant+timedelta(hours=1)))
        with app.state.store.lock, app.state.store.db:
            app.state.store.put('signal', signal)
        yield app, client, signal, instant, path
    app.state.store.db.close()


def sync(app, client, instant, revision=1, fail=False, future=False):
    received = stamp(instant + timedelta(minutes=1) if future else instant - timedelta(minutes=10))
    app.state.research_data.provider_factory = lambda: Source(received, revision, fail)
    return data(client.post(BASE + '/securities/' + SID + '/research/sync', json={'sections':['company']}))


def model(monkeypatch, captured, citations=None, during=None):
    monkeypatch.setenv('AGENT_API_BASE', 'https://model.invalid/v1')
    monkeypatch.setenv('AGENT_MODEL', '离线协议测试模型')

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            prompt = captured[-1]
            ids = [item['id'] for item in prompt['research']['evidence']]
            answer = dict(verdict='SUPPORT', summary='离线协议验证，非投资结论',
                supporting_evidence=['仅核对测试材料'], opposing_evidence=[], unknowns=[],
                conditions=[], limitations=['HTTP测试替身，不是真实模型或收益证据'],
                cited_evidence_ids=ids if citations is None else citations)
            return {'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)}}]}

    def post(*args, **kwargs):
        captured.append(json.loads(kwargs['json']['messages'][1]['content']))
        if during:
            during()
        return Response()

    monkeypatch.setattr('backend.app.httpx.post', post)


def review(client, signal):
    return data(client.post(BASE + '/reviews', json={'signal_id':signal['id']}))


def test_available_at_boundary_unknown_time_and_security_isolation(prepared):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    research = app.state.research_data
    snapshot = research.agent_context(SID, signal['confirmed_at'])
    assert snapshot['company']['business'] == '研究测试公司版本1'
    assert snapshot['evidence'][0]['included'] is True
    at = research.agent_context(SID, stamp(instant - timedelta(minutes=10)))
    assert at['evidence'][0]['included'] is True, '获知时间等于信号时点可纳入'
    before = research.agent_context(SID, stamp(instant - timedelta(minutes=11)))
    assert before['company'] is None and before['evidence'][0]['included'] is False
    for cutoff in (None, '2026-10-28', '2026-10-28T00:00:00', 'bad'):
        unknown = research.agent_context(SID, cutoff)
        assert unknown['company'] is None
        assert unknown['evidence'][0]['exclusion_reason'] == '缺少可比较的获知时间'
    assert research.agent_context('SH.600000', signal['confirmed_at'])['evidence'] == []


def test_late_revision_uses_original_historical_version_and_never_sends_future_body(prepared, monkeypatch):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    original = deepcopy(app.state.research_data.agent_context(SID, signal['confirmed_at']))
    sync(app, client, instant, revision=2, future=True)
    captured = []
    model(monkeypatch, captured)
    result = review(client, signal)
    assert result['mode'] == 'LLM' and result['verdict'] == 'SUPPORT'
    assert result['model_request_attempted'] is True and result['research_binding_status'] == 'CURRENT'
    assert result['research_context_snapshot']['company'] == original['company']
    assert [item['included'] for item in result['research_evidence_snapshot']] == [True, False]
    assert '版本2' not in json.dumps(captured[0], ensure_ascii=False)
    assert len(captured[0]['research']['evidence']) == len(result['cited_evidence_ids']) == 1
    assert data(client.get(BASE + '/signals'))[0]['decision']['gate_passed'] is True
    assert data(client.get(BASE + '/sim/accounts')) == []


@pytest.mark.parametrize('citations', [['invented-id'], None, 'not-an-array'])
def test_unknown_or_missing_research_citations_keep_wait(prepared, monkeypatch, citations):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    captured = []
    model(monkeypatch, captured, citations=citations if citations is not None else ['not-provided'])
    result = review(client, signal)
    assert result['verdict'] == 'WAIT' and result['mode'] == 'UNAVAILABLE'
    assert result['cited_evidence_ids'] == []
    assert data(client.get(BASE + '/signals'))[0]['decision']['gate_passed'] is False


def test_invalid_model_shape_returns_safe_error_code_and_latency(prepared, monkeypatch):
    _, client, signal, _, _ = prepared
    monkeypatch.setenv('AGENT_API_BASE', 'https://model.invalid/v1')
    monkeypatch.setenv('AGENT_MODEL', 'offline-test-model')

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'choices': [{'message': {'content': json.dumps({
                'verdict': [], 'summary': 'bad shape'
            })}}]}

    monkeypatch.setattr('backend.app.httpx.post', lambda *args, **kwargs: Response())
    result = review(client, signal)
    assert result['verdict'] == 'WAIT' and result['mode'] == 'UNAVAILABLE'
    assert result['model_request_attempted'] is True
    assert result['model_error_code'] == 'INVALID_RESPONSE'
    assert isinstance(result['model_latency_ms'], int) and result['model_latency_ms'] >= 0
    assert 'bad shape' not in result['summary']


def test_revision_invalidates_without_overwriting_review_and_no_automatic_retry(prepared, monkeypatch):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    captured = []
    model(monkeypatch, captured)
    result = review(client, signal)
    saved = deepcopy(app.state.store.get('review', result['id']))
    sync(app, client, instant, revision=2, future=True)
    public = data(client.get(BASE + '/signals'))[0]
    assert public['status'] == 'CONFIRMED', '研究变化不改写算法信号'
    assert public['review']['research_binding_status'] == 'STALE'
    assert public['decision']['gate_passed'] is False
    assert any(item['id']=='research_binding' and not item['passed'] for item in public['decision']['checks'])
    assert app.state.store.get('review', result['id']) == saved
    listed = data(client.get(BASE + '/reviews'))
    assert listed[0]['research_binding_status'] == 'STALE'
    data(client.patch(BASE + '/automation', json={'enabled':True,'auto_review':True}))
    app.state.automation.run('MANUAL')
    assert len(captured) == 1, '资料更新不得隐式重发收费模型请求'
    renewed = review(client, signal)
    assert renewed['id'] != result['id'] and renewed['research_binding_status']=='CURRENT'
    assert len(app.state.store.all('review')) == 2


def test_same_version_or_failed_sync_preserves_binding(prepared, monkeypatch):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    captured = []
    model(monkeypatch, captured)
    result = review(client, signal)
    sync(app, client, instant)
    assert data(client.get(BASE + '/reviews'))[0]['research_binding_status']=='CURRENT'
    failed = sync(app, client, instant, revision=2, fail=True)
    assert failed['status'] == 'FAILED'
    assert data(client.get(BASE + '/reviews'))[0]['research_revision_hash']==result['research_revision_hash']
    assert data(client.get(BASE + '/signals'))[0]['decision']['gate_passed'] is True


def test_research_changes_during_model_call_keep_wait_and_original_evidence(prepared, monkeypatch):
    app, client, signal, instant, _ = prepared
    sync(app, client, instant)
    source = Source(stamp(instant+timedelta(seconds=1)), revision=2)
    captured=[]
    model(monkeypatch, captured, during=lambda: app.state.research_data._save(SID,'company',source.company(SID)))
    result=review(client, signal)
    assert result['mode']=='LLM' and result['verdict']=='WAIT'
    assert result['research_binding_status']=='STALE'
    assert '请求期间' in result['summary']
    assert result['research_context_snapshot']['company']['business']=='研究测试公司版本1'
    assert data(client.get(BASE+'/signals'))[0]['decision']['gate_passed'] is False


def test_no_model_and_rule_demo_record_snapshot_without_claiming_model_use(prepared):
    app, client, signal, instant, _=prepared
    sync(app,client,instant)
    unavailable=review(client,signal)
    demo=data(client.post(BASE+'/reviews',json={'signal_id':signal['id'],'demo':True}))
    assert unavailable['mode']=='UNAVAILABLE' and unavailable['verdict']=='WAIT'
    assert demo['mode']=='RULE_DEMO'
    for result in (unavailable,demo):
        assert result['model_request_attempted'] is False and result['cited_evidence_ids']==[]
        assert len(result['research_evidence_snapshot'])==1
    assert data(client.get(BASE+'/signals'))[0]['decision']['gate_passed'] is False


def test_legacy_unbound_review_cannot_pass_and_snapshot_survives_restart(prepared,monkeypatch):
    app,client,signal,instant,path=prepared
    sync(app,client,instant)
    captured=[]
    model(monkeypatch,captured)
    current=review(client,signal)
    second=create_app(path)
    try:
        assert second.state.store.get('review',current['id'])['research_context_snapshot']==current['research_context_snapshot']
        assert second.state.research_data.revision_hash(SID,signal['confirmed_at'])==current['research_revision_hash']
    finally:
        second.state.store.db.close()
    with app.state.store.lock,app.state.store.db:
        legacy=app.state.store.get('review',current['id'])
        legacy.pop('research_revision_hash')
        app.state.store.put('review',legacy)
    public=data(client.get(BASE+'/signals'))[0]
    assert public['review']['research_binding_status']=='UNBOUND'
    assert public['decision']['gate_passed'] is False
