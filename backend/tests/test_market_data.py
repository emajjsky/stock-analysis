"""真实数据入库边界测试；上游用确定fixture，不调用外网。"""
from datetime import date, timedelta
import hashlib

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.providers import ProviderError


class Source:
    def quotes(self, ids):
        return [dict(security_id=sid, code=sid[3:], name='真实来源测试证券',
                     price='15.00', previous_close='14.80', change_pct='1.35',
                     volume=123400, amount='1851000.00', open='14.80', high='15.10', low='14.70',
                     source='固定测试上游', source_time='2026-10-26T07:00:00Z',
                     fetched_at='2026-10-27T09:00:00Z', raw_hash='q'*64) for sid in ids]

    def daily(self, sid, count=2000):
        start = date(2026, 1, 5)
        result = []
        for i in range(35):
            day = start + timedelta(days=i)
            if day.weekday() > 4:
                continue
            close = str(10 + i / 10)
            result.append(dict(time=day.isoformat(), open=close, high=str(11+i/10), low=str(9+i/10),
                close=close, volume=120000, amount=None, source_time=day.isoformat(),
                fetched_at='2026-10-27T09:00:00Z', raw_hash='d'*64, adjustment='NONE'))
        return result

    def close(self):
        pass


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / 'research.db')
    app.state.market_data.provider_factory = Source
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin'] = 'http://127.0.0.1:8765'
        yield app, client
    app.state.store.db.close()


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


def sync(client, **options):
    return data(client.post('/api/v1/data/providers/tencent/sync', json={
        'security_ids':['600519'], 'sync_daily':True, **options}))


def test_provider_diagnostics_are_read_only_and_empty(setup):
    app, client = setup
    def forbidden():
        pytest.fail('诊断GET不得连接上游')
    app.state.market_data.provider_factory = forbidden
    provider = next(x for x in data(client.get('/api/v1/data/providers')) if x['id'] == 'tencent')
    assert provider['status'] == 'AVAILABLE' and not provider['connected']
    assert data(client.get('/api/v1/data/sync-runs')) == []
    assert data(client.get('/api/v1/securities')) == []


def test_adjusted_bars_are_separate_and_chart_does_not_overlay_raw_quote(setup):
    app, client = setup
    sync(client)
    sid = 'LIVE.SH.600519'
    original = app.state.store.bars(sid)
    class Adjusted(Source):
        def full_history(self, security_id, adjustment='none'):
            rows = super().daily(security_id)
            for row in rows:
                row['open'] = str(float(row['open']) / 2)
                row['high'] = str(float(row['high']) / 2)
                row['low'] = str(float(row['low']) / 2)
                row['close'] = str(float(row['close']) / 2)
                row['adjustment'] = adjustment.upper()
            return rows
    app.state.market_data.provider_factory = Adjusted
    synced = data(client.post(f'/api/v1/securities/{sid}/history/sync?adjustment=qfq', json={}))
    assert synced['adjustment'] == 'QFQ' and synced['count'] > 21
    assert app.state.store.bars(sid) == original
    qfq = data(client.get('/api/v1/market/bars', params={'security_id':sid,'timeframe':'1d','adjustment':'qfq'}))
    assert qfq['adjustment'] == 'QFQ' and qfq['bars'][-1]['close'] != original[-1]['close']
    assert qfq['current_bar'] is None
    assert qfq['bars_coverage']['count'] == len(qfq['bars'])
    assert client.post(f'/api/v1/securities/{sid}/history/sync?adjustment=none', json={}).status_code == 422
    assert client.get('/api/v1/market/bars', params={'security_id':sid,'adjustment':'hfq'}).json()['data']['bars'] == []


def test_adjusted_revision_archives_old_values_without_changing_strategy_input(setup):
    app, client = setup
    sync(client)
    sid = 'LIVE.SH.600519'
    original = app.state.store.bars(sid)
    class Adjusted(Source):
        factor = 1
        partial = False
        def full_history(self, security_id, adjustment='none'):
            rows = self.daily(security_id)
            for row in rows:
                for field in ('open','high','low','close'):
                    row[field] = str(float(row[field])*self.factor)
            return rows[1:] if self.partial else rows
    app.state.market_data.provider_factory = Adjusted
    path = f'/api/v1/securities/{sid}/history/sync?adjustment=qfq'
    data(client.post(path,json={}))
    previous = app.state.store.bars(sid,'qfq')
    Adjusted.factor = 2
    Adjusted.partial = True
    response = client.post(path,json={})
    assert response.status_code == 422 and response.json()['error']['code'] == 'INCOMPLETE_REVISION'
    assert app.state.store.bars(sid,'qfq') == previous
    assert app.state.store.all('adjusted_history_revision') == []
    Adjusted.partial = False
    data(client.post(path,json={}))
    archives = app.state.store.all('adjusted_history_revision')
    assert len(archives) == 1 and archives[0]['bars'][0]['close'] == previous[0]['close']
    assert float(app.state.store.bars(sid,'qfq')[0]['close']) == float(previous[0]['close'])*2
    data(client.post(path,json={}))
    assert len(app.state.store.all('adjusted_history_revision')) == 1
    assert app.state.store.bars(sid) == original
    chart = data(client.get('/api/v1/market/bars',params={'security_id':sid,'adjustment':'qfq'}))
    assert chart['history_updated_at'] and chart['history_refresh_due'] is False


def test_adjusted_source_is_visible_and_refresh_failure_preserves_last_success(setup):
    app, client = setup
    sync(client)
    sid = 'LIVE.SH.600519'
    class Adjusted(Source):
        failed = False
        def full_history(self, security_id, adjustment='qfq'):
            if self.failed: raise ProviderError('HISTORY_UNAVAILABLE', '两个历史来源暂不可用')
            return [{**row, 'source':'东方财富公开日线 / 前复权（备用源）'} for row in self.daily(security_id)]
    app.state.market_data.provider_factory = Adjusted
    path = f'/api/v1/securities/{sid}/history/sync?adjustment=qfq'
    data(client.post(path, json={}))
    original = app.state.store.bars(sid, 'qfq')
    assert all(row['source'] == '东方财富公开日线 / 前复权（备用源）' for row in original)
    chart = data(client.get('/api/v1/market/bars', params={'security_id':sid, 'adjustment':'qfq'}))
    assert chart['history_source'] == '东方财富公开日线 / 前复权（备用源）'
    Adjusted.failed = True
    assert client.post(path, json={}).status_code == 422
    assert app.state.store.bars(sid, 'qfq') == original
    assert data(client.get('/api/v1/market/bars', params={'security_id':sid, 'adjustment':'qfq'}))['bars'] == chart['bars']


def test_sync_persists_real_data_separately_and_supports_charts_and_algorithms(setup):
    app, client = setup
    data(client.post('/api/v1/demo/seed', json={}))
    before = app.state.store.db.execute('SELECT count(*) FROM bars').fetchone()[0]
    result = sync(client)
    assert result['status'] == 'SUCCEEDED' and result['quotes_updated'] == 1 and result['daily_rows_saved'] > 21
    sid = 'LIVE.SH.600519'
    security = data(client.get('/api/v1/securities/' + sid))
    assert security['quote']['mode'] == 'LIVE' and security['quote']['is_realtime'] is False
    assert security['quote']['as_of'] == '2026-10-26T07:00:00Z'
    assert security['quote']['fetched_at'] != security['quote']['as_of']
    assert app.state.store.db.execute('SELECT count(*) FROM bars').fetchone()[0] == before
    for timeframe in ['1d', '1w', '1mo']:
        chart = data(client.get('/api/v1/market/bars', params={'security_id':sid,'timeframe':timeframe}))
        assert chart['bars'] and all(x['amount'] is None for x in chart['bars'])
        assert len(chart['indicators']['ma20']) == len(chart['bars'])
    recs = data(client.post('/api/v1/recommendations/run', json={'algorithm_id':'trend-stability-v1'}))
    assert recs and all(x['security']['id'].startswith('LIVE.') for x in recs)
    assert data(client.get('/api/v1/watchlists')) == []
    assert data(client.get('/api/v1/sim/accounts')) == []
    assert len(data(client.get('/api/v1/data/sync-runs'))) == 1
    assert sync(client, security_ids=[sid])['daily_rows_saved'] == 0


def test_sync_cannot_replace_csv_or_demo_identity(setup):
    app, client = setup
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('security', dict(id='SH.600519', code='600519', name='自己的CSV名称',
                                           exchange='SSE', sector='自己分类', status='IMPORTED_UNVERIFIED'))
    sync(client)
    assert app.state.store.get('security', 'SH.600519')['name'] == '自己的CSV名称'
    assert app.state.store.get('security', 'LIVE.SH.600519')['name'] == '真实来源测试证券'


def test_history_revision_rolls_back_one_symbol_and_preserves_old_rows(setup):
    app, client = setup
    sync(client)
    first = app.state.store.bars('LIVE.SH.600519')
    class Revised(Source):
        def daily(self, *args, **kwargs):
            rows = super().daily(*args, **kwargs)
            rows[0]['close'] = '999'
            return rows
    app.state.market_data.provider_factory = Revised
    result = sync(client)
    assert result['status'] == 'PARTIAL' and result['daily_rows_saved'] == 0
    assert result['errors'] and app.state.store.bars('LIVE.SH.600519') == first


def test_upstream_failure_preserves_cache_and_never_fakes_success(setup):
    app, client = setup
    sync(client)
    old = app.state.store.get('market_snapshot', 'LIVE.SH.600519')
    class Broken(Source):
        def quotes(self, *args):
            raise ProviderError('UPSTREAM_UNAVAILABLE', '公开来源暂时不可用')
    app.state.market_data.provider_factory = Broken
    result = sync(client, sync_daily=False)
    assert result['status'] == 'FAILED' and result['quotes_updated'] == 0
    assert app.state.store.get('market_snapshot', 'LIVE.SH.600519') == old
    provider = next(x for x in data(client.get('/api/v1/data/providers')) if x['id'] == 'tencent')
    assert provider['status'] == 'ERROR' and '不可用' in provider['error']


def test_source_input_limits_origin_and_live_trading_isolation(setup):
    app, client = setup
    for payload in [
        {'security_ids':['https://evil.test']}, {'security_ids':[]},
        {'security_ids':['DEMO.000001']},
        {'security_ids':['600000','600519','000001','000002','000333','600036'],'sync_daily':True},
    ]:
        assert client.post('/api/v1/data/providers/tencent/sync', json=payload).status_code == 422
    client.headers.pop('Origin')
    assert client.post('/api/v1/data/providers/tencent/sync',json={'security_ids':['600519']}).status_code == 403
    client.headers['Origin']='http://127.0.0.1:8765'
    sync(client)
    assert client.post('/api/v1/sim/accounts', json={'name':'外部','initial_cash':'76543.21','mode':'LIVE'}).status_code == 409
    assert data(client.get('/api/v1/live/status'))['enabled'] is False
