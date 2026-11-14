"""公司研究同步的获知时点、失败保留、数据隔离与来源边界。"""
from copy import deepcopy
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.providers import ProviderError


class Source:
    revision = 1
    received = '2026-10-28T00:00:00Z'

    def envelope(self, sid, section, **kwargs):
        return dict(security_id=sid, source='离线测试研究源', source_url='https://data.eastmoney.com/',
            received_at=self.received, raw_hash=hashlib.sha256((section + str(self.revision)).encode()).hexdigest(), **kwargs)

    def company(self, sid):
        return self.envelope(sid, 'company', business='测试公司主营描述',
            facts=[dict(label='公司全称', value='测试股份', period='当前资料', source='离线测试研究源')])

    def financials(self, sid):
        return self.envelope(sid, 'financials', records=[dict(period='2026-06-30',
            published_at='2026-08-14T16:00:00Z', publication_precision='DATE',
            total_revenue='1234567890.01', parent_net_profit=None, currency='CNY', unit='元')])

    def announcements(self, sid):
        return self.envelope(sid, 'announcements', events=[dict(id='AN123', title='公司公告标题',
            published_at='2026-08-14T16:00:00Z', publication_precision='DATE',
            url='https://data.eastmoney.com/notices/detail/600519/AN123.html')])

    def close(self):
        pass


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / 'research-test.db')
    app.state.research_data.provider_factory = Source
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('security', dict(id='LIVE.SH.600519', code='600519', name='测试股票',
            exchange='SSE', sector='未知', status='LIVE_UNVERIFIED'))
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin'] = 'http://127.0.0.1:8765'
        yield app, client
    app.state.store.db.close()


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


URL = '/api/v1/securities/LIVE.SH.600519'


def sync(client, **body):
    return data(client.post(URL + '/research/sync', json=body))


def test_get_profile_and_diagnostics_never_request_upstream(setup):
    app, client = setup
    def forbidden():
        pytest.fail('GET不得抓取研究资料')
    app.state.research_data.provider_factory = forbidden
    profile = data(client.get(URL + '/profile'))
    assert profile['business'] is None and profile['financials'] == [] and profile['events'] == []
    assert profile['research']['supported'] is True and profile['research']['status'] == 'AVAILABLE'
    provider = next(p for p in data(client.get('/api/v1/data/providers')) if p['id'] == 'eastmoney-research')
    assert provider['data_mode'] == 'RESEARCH' and provider['connected'] is False


def test_sync_sections_keep_decimal_missing_and_received_time_separate(setup):
    app, client = setup
    run = sync(client)
    assert run['status'] == 'SUCCEEDED' and len(run['updated_sections']) == 3
    p = data(client.get(URL + '/profile'))
    assert p['business'] == '测试公司主营描述'
    f = p['financials'][0]
    assert f['total_revenue'] == '1234567890.01' and f['parent_net_profit'] is None
    assert f['available_at'] == Source.received and f['published_at'] != f['available_at']
    assert f['publication_precision'] == 'DATE' and f['unit'] == '元'
    assert p['events'][0]['available_at'] == Source.received
    assert '未读取原文' in p['events'][0]['summary']
    assert len(p['evidence']) == 3 and p['research']['sections'] == ['company', 'financials', 'announcements']
    assert p['research']['section_status']['financials'] == {
        'status': 'SYNCED', 'last_attempt_at': run['finished_at'], 'last_updated_at': Source.received,
        'source': '离线测试研究源', 'error': None,
    }
    assert app.state.store.get('profile', 'LIVE.SH.600519', False) is None, '研究缓存不可覆盖既有Agent资料命名空间'
    for kind in ('signal', 'review', 'watch', 'account', 'order', 'market_snapshot'):
        assert app.state.store.all(kind) == []
    assert app.state.store.db.execute('SELECT count(*) FROM bars').fetchone()[0] == 0
    assert app.state.store.db.execute('SELECT count(*) FROM provider_bars').fetchone()[0] == 0


def test_partial_failure_keeps_old_section_and_reports_error(setup):
    app, client = setup
    sync(client)
    previous = data(client.get(URL + '/profile'))
    class Partial(Source):
        revision = 2
        def company(self, sid):
            raise ProviderError('UPSTREAM', '来源不可用')
    app.state.research_data.provider_factory = Partial
    run = sync(client)
    assert run['status'] == 'PARTIAL' and run['updated_sections'] == ['financials', 'announcements']
    current = data(client.get(URL + '/profile'))
    assert current['business'] == previous['business']
    assert '来源不可用' in current['research']['error']
    assert current['research']['section_status']['company']['status'] == 'STALE'
    assert current['research']['section_status']['company']['last_updated_at'] == Source.received
    assert current['research']['section_status']['company']['error'] == '来源不可用'
    assert current['research']['section_status']['financials']['status'] == 'SYNCED'
    assert len(app.state.store.all('research_snapshot')) == 5


def test_repeat_keeps_first_observed_time_and_revisions_append(setup):
    app, client = setup
    sync(client)
    first = deepcopy(data(client.get(URL + '/profile')))
    class Later(Source):
        revision = 2
        received = '2026-10-29T00:00:00Z'
    app.state.research_data.provider_factory = Later
    sync(client)
    later = data(client.get(URL + '/profile'))
    assert later['financials'][0]['available_at'] == first['financials'][0]['available_at']
    assert later['financials'][0]['received_at'] == Later.received
    assert len(app.state.store.all('research_snapshot')) == 6
    sync(client)
    assert len(app.state.store.all('research_snapshot')) == 6
    assert len(app.state.store.all('research_observation')) == 2


def test_agent_context_filters_future_research_and_keeps_evidence_manifest(setup):
    app, client = setup
    sync(client)
    before = app.state.research_data.agent_context('LIVE.SH.600519', '2026-09-01T00:00:00Z')
    assert before['company'] is None and before['financials'] == [] and before['announcements'] == []
    assert len(before['evidence']) == 3
    assert all(item['included'] is False for item in before['evidence'])
    assert all('未来信息' in (item['exclusion_reason'] or '') for item in before['evidence'])

    after = app.state.research_data.agent_context('LIVE.SH.600519', '2026-10-28T00:00:00Z')
    assert after['company']['business'] == '测试公司主营描述'
    assert len(after['financials']) == 1 and len(after['announcements']) == 1
    assert all(item['included'] is True for item in after['evidence'])


def test_wrong_security_rejected_and_failure_preserves_evidence(setup):
    app, client = setup
    sync(client)
    previous = data(client.get(URL + '/profile'))['evidence']
    class Wrong(Source):
        def company(self, sid):
            return super().company('SZ.000001')
    app.state.research_data.provider_factory = Wrong
    run = sync(client, sections=['company'])
    assert run['status'] == 'FAILED' and run['updated_sections'] == []
    assert data(client.get(URL + '/profile'))['evidence'] == previous


def test_origin_sections_and_existing_security_are_required(setup):
    app, client = setup
    for body in ({'sections': []}, {'sections': ['unknown']}, {'sections': ['company', 'company']}, {'url': 'https://example.com'}):
        assert client.post(URL + '/research/sync', json=body).status_code == 422
    assert client.post('/api/v1/securities/LIVE.SH.600000/research/sync', json={}).status_code == 404
    client.headers.pop('Origin')
    assert client.post(URL + '/research/sync', json={}).status_code == 403


def test_demo_not_requested_and_busy_returns_conflict(setup):
    app, client = setup
    data(client.post('/api/v1/demo/seed', json={}))
    demo = next(s for s in data(client.get('/api/v1/securities')) if s['id'].startswith('DEMO.'))
    assert not data(client.get('/api/v1/securities/' + demo['id'] + '/profile'))['research']['supported']
    assert client.post('/api/v1/securities/' + demo['id'] + '/research/sync', json={}).status_code == 422
    app.state.research_data.lock.acquire()
    try:
        assert client.post(URL + '/research/sync', json={}).status_code == 409
    finally:
        app.state.research_data.lock.release()


def test_auto_freshness_uses_successful_check_not_first_evidence(setup):
    app, client = setup
    research = app.state.research_data
    assert research.due_sections('LIVE.SH.600519') == ['company', 'financials', 'announcements']
    sync(client)
    assert research.due_sections('LIVE.SH.600519') == []
    # 同内容检查不会修改证据首次获知时间，也不能因此不断判过期。
    sync(client)
    assert research.due_sections('LIVE.SH.600519') == []
    assert research.profile('LIVE.SH.600519')['evidence'][0]['received_at'] == Source.received


def test_auto_failure_backoff_preserves_cache_and_is_section_specific(setup):
    from datetime import datetime, timedelta, timezone
    app, client = setup
    research = app.state.research_data
    sync(client)
    previous = research.profile('LIVE.SH.600519')['business']
    class Unavailable(Source):
        def company(self, sid):
            raise ProviderError('UNAVAILABLE', '暂时失败')
    research.provider_factory = Unavailable
    run = sync(client, sections=['company'])
    assert research.due_sections('LIVE.SH.600519') == []
    run['finished_at'] = (datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat()
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('research_sync_run', run)
    assert research.due_sections('LIVE.SH.600519') == ['company']
    assert research.profile('LIVE.SH.600519')['business'] == previous


def test_auto_queue_is_nonblocking_deduplicated_and_obeys_switch(setup):
    import threading
    from backend.research_data import ResearchData
    app, client = setup
    research = ResearchData(app.state.store)
    research.request_auto('LIVE.SH.600519')
    assert not research.pending
    research.auto_enabled = lambda: True
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Slow(Source):
        def company(self, sid):
            calls.append(sid)
            entered.set()
            assert release.wait(3)
            return super().company(sid)
    research.provider_factory = Slow
    research.request_auto('DEMO.SH.600519')
    for _ in range(5):
        research.request_auto('LIVE.SH.600519')
    assert research.pending == {'LIVE.SH.600519'}
    research.start()
    try:
        assert entered.wait(3)
        p = research.profile('LIVE.SH.600519')
        assert p['business'] is None and p['research']['auto_refresh']['pending']
        research.request_auto('LIVE.SH.600519')
        assert not research.pending, '正在抓取的证券不能重复入队'
        research.auto_enabled = lambda: False
        release.set()
        assert research.lock.acquire(timeout=3)
        research.lock.release()
        assert calls == ['SH.600519']
        p = research.profile('LIVE.SH.600519')
        assert p['business'] == '测试公司主营描述'
        assert p['financials'] == [], '关闭开关后不再抓取下一栏目'
    finally:
        release.set()
        research.stop()


def test_initialization_failure_has_section_status_and_backoff(setup):
    app, client = setup
    def unavailable():
        raise RuntimeError('offline')
    research = app.state.research_data
    research.provider_factory = unavailable
    sync(client, sections=['financials'])
    p = research.profile('LIVE.SH.600519')
    assert p['research']['section_status']['financials']['status'] == 'ERROR'
    assert research.due_sections('LIVE.SH.600519') == ['company', 'announcements']


def test_financial_schema_upgrade_bypasses_success_ttl_but_not_failure_backoff(setup):
    from datetime import datetime, timedelta, timezone
    app, client = setup
    research = app.state.research_data
    sync(client)
    class Upgraded(Source):
        financial_schema_version = 2
        fail = True
        def financials(self, sid):
            if self.fail:
                raise ProviderError('UNAVAILABLE', '暂时失败')
            response = super().financials(sid)
            response['schema_version'] = 2
            response['records'][0].update(revenue_yoy='12.3', profit_yoy=None)
            return response
    research.provider_factory = Upgraded
    assert research.due_sections('LIVE.SH.600519') == ['financials']
    run = sync(client, sections=['financials'])
    assert research.due_sections('LIVE.SH.600519') == []
    run['finished_at'] = (datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('research_sync_run', run)
    assert research.due_sections('LIVE.SH.600519') == ['financials']
    Upgraded.fail = False
    sync(client, sections=['financials'])
    assert research.due_sections('LIVE.SH.600519') == []
    assert research.profile('LIVE.SH.600519')['financials'][0]['revenue_yoy'] == '12.3'


def test_missing_corporate_actions_queue_once_even_when_sections_are_fresh(setup):
    app, client = setup
    research = app.state.research_data
    sync(client)
    class WithActions(Source):
        calls = 0
        def corporate_actions(self, sid):
            WithActions.calls += 1
            return dict(security_id=sid, items=[], source='测试源', received_at=self.received)
    research.provider_factory = WithActions
    assert research.due_sections('LIVE.SH.600519') == ['announcements']
    sync(client, sections=research.due_sections('LIVE.SH.600519'))
    assert WithActions.calls == 1
    assert research.due_sections('LIVE.SH.600519') == []


def test_corporate_actions_failure_preserves_data_and_backs_off(setup):
    app, client = setup
    research = app.state.research_data
    class WithActions(Source):
        def corporate_actions(self, sid):
            raise ProviderError('UNAVAILABLE', '暂时失败')
    research.provider_factory = WithActions
    sync(client)
    assert research.due_sections('LIVE.SH.600519') == []
    assert research.profile('LIVE.SH.600519')['corporate_actions']['error']
