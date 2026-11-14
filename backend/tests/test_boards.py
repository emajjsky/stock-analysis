"""板块来源的身份、分页、单位与缓存边界，离线固定响应。"""
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.boards import BoardProvider, BoardsData, number, stamp


def provider(data):
    def respond(request):
        payload = data(request) if callable(data) else data
        return httpx.Response(200, json={'rc': 0, 'data': payload})
    return BoardProvider(httpx.Client(transport=httpx.MockTransport(respond)))


def row(code='600519', market=1):
    return dict(f12=code, f13=market, f14='测试名称', f2=12.3, f3=-1.25,
                f5=123, f6=123456, f124=1704438000)


def test_full_pagination_and_duplicate_rejection():
    rows = [row(f'{i:06d}') for i in range(101)]
    def pages(request):
        n = int(request.url.params['pn'])
        return {'total': 101, 'diff': rows[:100] if n == 1 else rows[100:]}
    assert len(provider(pages).pages('test')[0]) == 101
    def duplicate(request):
        return {'total': 101, 'diff': rows[:100] if request.url.params['pn'] == '1' else rows[:1]}
    with pytest.raises(ValueError, match='overlapping'):
        provider(duplicate).pages('test')


def test_unsupported_leader_does_not_erase_board_and_missing_stays_missing():
    raw = row('BK1518', 90)
    raw.update(f140='920001', f141=0, f128='超范围证券', f136=3, f62='-', f8='-')
    result = provider({'total': 1, 'diff': [raw]}).boards('industry')['rows'][0]
    assert result['leader'] is None
    assert result['net_inflow'] is None and result['turnover_rate'] is None
    assert result['source_time'] != stamp()


def test_member_units_scope_and_signed_fund_fields():
    raw = row(); raw.update(f62=-10000, f184=-1.5)
    result = provider({'total': 3, 'diff': [raw, row('920001', 0), row('430001', 2)]}).members('BK1518')
    assert result['total'] == 3 and result['loaded'] == 1
    quote = result['rows'][0]['quote']
    assert quote['volume'] == 12300 and quote['amount'] == '123456'
    assert quote['net_inflow'] == '-10000' and quote['net_ratio'] == '-1.5'
    assert quote['previous_close'] is None and not quote['is_realtime']


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', True, '-1'])
def test_invalid_numbers_never_become_quotes(value):
    with pytest.raises(ValueError): number(value)


def test_chart_identity_dates_ohlc_and_fund_mapping():
    data = dict(code='BK1518', market=90, name='种子', klines=['2026-01-02,10,11,12,9,123,123456,3,1.25,1,4'])
    bars = provider(data).chart('BK1518', 'daily')['bars']
    assert bars[0]['volume'] == 12300 and bars[0]['close'] == '11'
    invalid = deepcopy(data); invalid['code'] = 'BK9999'
    with pytest.raises(ValueError, match='identity'): provider(invalid).chart('BK1518', 'daily')
    invalid = deepcopy(data); invalid['klines'] *= 2
    with pytest.raises(ValueError, match='dates'): provider(invalid).chart('BK1518', 'daily')
    invalid = deepcopy(data); invalid['klines'][0] = '2026-01-02,10,11,8,9,123,123456,3,1.25,1,4'
    with pytest.raises(ValueError, match='OHLC'): provider(invalid).chart('BK1518', 'daily')
    data['klines'] = ['2026-01-02,-123,2,3,4,5,-1.5,7,8,9,10,11,-1.25']
    flow = provider(data).chart('BK1518', 'funds')['flows'][0]
    assert flow['net_inflow'] == '-123' and flow['net_ratio'] == '-1.5' and flow['close'] == '11'


def test_cached_failure_keeps_success_and_factory_failure_clears_pending(tmp_path):
    app = create_app(tmp_path / 'boards.db', network_enabled=False)
    boards = app.state.boards
    saved = dict(id='list:industry', fetched_at='2026-01-02T00:00:00Z', rows=[{'code': 'BK1518'}])
    with app.state.store.lock, app.state.store.db: app.state.store.put('board_cache', saved)
    def fail(): raise ValueError('factory failed')
    boards.factory = fail
    boards.pending.add('list:industry')
    boards.refresh('list:industry', lambda p: p.boards('industry'), 30)
    result = boards.boards('industry')
    assert result['rows'] == saved['rows'] and result['error'] and result['stale']
    assert not boards.pending and not result['enabled']
    boards.stop(); app.state.store.db.close()


def test_api_disabled_does_not_fetch_and_unknown_identity_rejected(tmp_path):
    app = create_app(tmp_path / 'boards-api.db', network_enabled=False)
    with TestClient(app, base_url='http://127.0.0.1:8765') as c:
        c.get('/api/v1/session'); c.headers['Origin'] = 'http://127.0.0.1:8765'
        result = c.get('/api/v1/market/boards').json()['data']
        assert result['status'] == 'EMPTY' and not result['enabled']
        assert c.get('/api/v1/market/boards?kind=invalid').status_code == 422
        assert c.get('/api/v1/market/boards/BK9999/members').status_code == 422
        assert c.get('/api/v1/market/boards/rotation').json()['data']['days'] == []
    app.state.store.db.close()


def test_source_trade_day_rotation_and_success_archive(tmp_path):
    app = create_app(tmp_path / 'boards-rotation.db', network_enabled=False)
    boards = app.state.boards
    boards.factory = lambda: SimpleNamespace(close=lambda: None)
    rows = [dict(code='BK1518', source_time='2026-01-01T23:00:00Z', change_pct='3.1')]
    boards.refresh('list:industry', lambda p: dict(rows=rows, total=1), 30)
    result = boards.rotation('industry')['days']
    assert result[0]['date'] == '2026-01-02'
    assert boards.boards('industry')['rows'] == rows
    assert boards.rotation('concept')['days'] == []
    boards.stop(); app.state.store.db.close()


def test_manual_refresh_retries_cache_without_changing_auto_setting(tmp_path):
    app = create_app(tmp_path / 'boards-manual.db', network_enabled=False)
    boards = app.state.boards
    submitted = []
    class Pool:
        def submit(self, *args): submitted.append(args)
        def shutdown(self, **kwargs): pass
    boards.pool.shutdown(wait=True); boards.pool = Pool()
    boards.terminal.network_enabled = True
    boards.terminal.config = lambda: {'enabled': False}
    boards.due['list:industry'] = float('inf')
    assert not boards.boards('industry')['refreshing']
    assert boards.request('industry')['queued']
    assert len(submitted) == 1 and not boards.terminal.config()['enabled']
    boards.pending.clear()
    assert not boards.request('industry')['queued']  # 手动点击至少间隔5秒。
    boards.stop(); app.state.store.db.close()
