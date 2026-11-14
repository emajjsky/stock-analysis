"""终端目录、缓存、刷新边界：所有上游均为固定替身，不访问外网。"""
from datetime import datetime, timezone, date, timedelta
import json
import threading
import httpx
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app, indicators
from backend.technical import extended_indicators
from backend.providers import ProviderError, normalize_security_id
from backend.terminal_data import TerminalProvider, market_open
from backend.catalog import CatalogProvider


ROWS = [dict(code='600519', name='贵州茅台', market=1), dict(code='000001', name='平安银行', market=0),
        dict(code='600039', name='四川路桥', market=1), dict(code='601127', name='赛力斯', market=1),
        dict(code='600106', name='重庆路桥', market=1), dict(code='302132', name='中航成飞', market=0)]


def test_chart_indicators_include_long_moving_averages_and_standard_oscillators():
    bars = [dict(time=(date(2025, 1, 1) + timedelta(days=i)).isoformat(), open=str(10 + i), high=str(11 + i),
                 low=str(9 + i), close=str(10 + i), volume=1000, amount=None) for i in range(260)]
    values = indicators(bars)
    assert values['ma5'][3] is None and values['ma5'][4] == '12.00'
    assert values['ma250'][248] is None and values['ma250'][249] == '134.50'
    assert values['rsi6'][-1] == '100.00' and values['rsi14'][-1] == '100.00'
    assert all(values[key][-1] is not None for key in ('macd_dif', 'macd_dea', 'macd', 'k', 'd', 'j'))
    extended = extended_indicators(bars)
    assert all(extended[key][-1] is not None for key in ('ene_mid', 'ene_upper', 'ene_lower'))


@pytest.fixture
def prepared(tmp_path):
    app = create_app(tmp_path/'terminal.db')
    app.state.terminal.catalog.import_rows(ROWS, '固定测试目录', minimum=1)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin'] = 'http://127.0.0.1:8765'
        yield app, client
    app.state.store.db.close()


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_tencent_terminal_client_ignores_proxy_environment(monkeypatch):
    options = {}

    class Client:
        def __init__(self, **kwargs):
            options.update(kwargs)
        def close(self):
            pass

    monkeypatch.setattr('backend.terminal_data.httpx.Client', Client)
    provider = TerminalProvider()
    provider.close()
    assert options['trust_env'] is False
    assert options['headers']['User-Agent'] == 'Mozilla/5.0'


def test_catalog_client_ignores_proxy_environment(monkeypatch):
    options = {}

    class Client:
        def __init__(self, **kwargs):
            options.update(kwargs)
        def close(self):
            pass

    monkeypatch.setattr('backend.catalog.httpx.Client', Client)
    provider = CatalogProvider()
    provider.close()
    assert options['trust_env'] is False


@pytest.mark.parametrize('query', ['600519','贵州茅台','guizhoumaotai','gzmt'])
def test_catalog_search_without_materializing_whole_universe(prepared, query):
    app, client = prepared
    rows = data(client.get('/api/v1/securities', params={'q':query}))
    assert rows[0]['id'] == 'LIVE.SH.600519' and rows[0]['quote'] is None
    assert data(client.get('/api/v1/securities')) == []
    assert app.state.store.all('security') == []


def test_catalog_search_and_paging_return_the_same_saved_quote(prepared):
    app, client = prepared
    security_id = 'LIVE.SH.600519'
    quote = dict(id=security_id, security_id='SH.600519', price='1688.00', change_pct='1.25',
                 amount='123450000', volume=80000, source_time='2026-11-08T02:00:00Z')
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('market_snapshot', quote)

    searched = data(client.get('/api/v1/securities', params={'q': '600519'}))[0]
    paged = next(row for row in data(client.get('/api/v1/securities', params={'catalog': 'true', 'limit': 100}))
                 if row['id'] == security_id)
    assert searched['quote'] == paged['quote']
    assert paged['quote']['price'] == quote['price']
    assert paged['quote']['as_of'] == quote['source_time']
    assert paged['quote']['is_realtime'] is False


def test_pinyin_polyphone_and_literal_wildcards(prepared):
    _, client = prepared
    assert data(client.get('/api/v1/securities', params={'q':'cqlq'}))[0]['name'] == '重庆路桥'
    assert data(client.get('/api/v1/securities', params={'q':'chongqingluqiao'}))[0]['name'] == '重庆路桥'
    assert data(client.get('/api/v1/securities', params={'q':'%'})) == []


def test_demo_never_duplicates_real_search_match(prepared):
    app, client = prepared
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('security', dict(id='DEMO.SH.600519',code='600519',name='贵州茅台',exchange='SSE'))
    for term in ['600519','贵州茅台','gzmt']:
        assert [x['id'] for x in data(client.get('/api/v1/securities',params={'q':term}))] == ['LIVE.SH.600519']


def test_catalog_paging_activation_watch_and_restart_offline(prepared, tmp_path):
    app, client = prepared
    assert len(data(client.get('/api/v1/securities?catalog=true&limit=2&offset=1'))) == 2
    assert data(client.post('/api/v1/securities/LIVE.SH.600519/activate', json={}))['name'] == '贵州茅台'
    assert data(client.post('/api/v1/watchlists', json={'security_id':'LIVE.SZ.302132'}))['security']['name'] == '中航成飞'
    assert len(data(client.get('/api/v1/securities'))) == 2
    assert len(data(client.get('/api/v1/securities?q=600519'))) == 1
    assert app.state.terminal.thread is None
    path = str(app.state.store.db.execute('PRAGMA database_list').fetchone()[2])
    second = create_app(path)
    with TestClient(second, base_url='http://127.0.0.1:8765') as reopened:
        assert data(reopened.get('/api/v1/securities?q=gzmt'))[0]['name'] == '贵州茅台'
        assert data(reopened.get('/api/v1/data/catalog'))['count'] == len(ROWS)
        assert second.state.terminal.thread is None
    second.state.store.db.close()


def test_catalog_failed_or_partial_replacement_keeps_complete_old_version(prepared):
    app, _ = prepared
    catalog = app.state.terminal.catalog
    initial = catalog.status()
    with pytest.raises(ProviderError):
        catalog.import_rows(ROWS[:1])
    assert catalog.status() == initial
    with pytest.raises(ProviderError):
        catalog.import_rows([ROWS[0], ROWS[0]], minimum=1)
    assert catalog.status() == initial
    class Failed:
        def download(self):
            raise ProviderError('FAILED', '固定上游失败')
        def close(self): pass
    catalog.provider_factory = Failed
    assert catalog.sync()['status'] == 'ERROR'
    assert catalog.status()['count'] == len(ROWS)
    assert catalog.search('gzmt')[0]['name'] == '贵州茅台'


class IndexSource:
    calls = []
    def quotes(self):
        self.calls.append('quotes')
        return [dict(security_id='SH.000001', price='3200', change_pct='1.2', volume=12300,
                     amount='10000', source_time='2026-10-29T07:00:00Z', fetched_at='2026-10-29T07:00:01Z')]
    def daily(self, symbol):
        self.calls.append('daily')
        return [dict(time='2026-10-28', open='3100', close='3200', high='3250', low='3050', volume=10000, amount=None)]
    def intraday(self, symbol):
        self.calls.append('intraday')
        return dict(symbol=symbol, points=[dict(time='2026-10-29T01:30:00Z',value='3200',volume=100)],
                    source='固定测试上游', source_time='2026-10-29T01:30:00Z', trade_date='2026-10-29', error=None)
    def close(self): pass


def test_stock_quote_and_intraday_arrive_before_history_backfill(prepared, monkeypatch):
    app, client = prepared
    terminal = app.state.terminal
    key = 'LIVE.SH.600519'
    terminal.activate(key)
    terminal.pending_symbols.add('sh000001')
    events = []
    def sync(ids, daily=False):
        events.append('stock_history' if daily else 'stock_quote')
        return {'quotes_updated': len(ids), 'errors': []}
    monkeypatch.setattr(terminal.market_data, 'sync', sync)
    class Prioritized(IndexSource):
        def stock_intraday(self, sid):
            assert events == ['stock_quote']
            events.append('stock_intraday')
            return dict(symbol='sh600519', points=[dict(time='2026-11-03T01:30:00Z', value='100', volume=100)],
                        source='固定测试源', source_time=None, error=None)
        def daily(self, symbol):
            assert app.state.store.get('stock_intraday', key)['points']
            events.append('index_history')
            return super().daily(symbol)
    terminal.provider_factory = Prioritized
    terminal.refresh_once()
    assert events[:2] == ['stock_quote', 'stock_intraday']
    assert events.index('stock_intraday') < events.index('index_history') < events.index('stock_history')


def test_new_stock_interrupts_remaining_history_and_is_first_next_batch(prepared, monkeypatch):
    app, _ = prepared
    terminal = app.state.terminal
    first, newest = 'LIVE.SH.600519', 'LIVE.SZ.000001'
    terminal.activate(first)
    terminal.pending_symbols.update(['sh000001', 'sz399001'])
    events = []
    def sync(ids, daily=False):
        events.append(('history' if daily else 'quotes', list(ids)))
        return {'quotes_updated': len(ids), 'errors': []}
    monkeypatch.setattr(terminal.market_data, 'sync', sync)
    monkeypatch.setattr(terminal, 'refresh_rankings', lambda: events.append(('rankings', [])))
    class Source(IndexSource):
        def stock_intraday(self, sid):
            events.append(('intraday', sid))
            return dict(symbol=sid, points=[dict(time='2026-11-03T01:30:00Z',value='100',volume=100)],error=None)
        def daily(self, symbol):
            events.append(('index_history', symbol))
            terminal.activate(newest)  # 用户在长历史请求期间打开另一只新股。
            return super().daily(symbol)
    terminal.provider_factory = Source
    terminal.refresh_once()
    assert len([x for x in events if x[0] == 'index_history']) == 1
    assert not any(x[0] in ('history','rankings') for x in events)
    assert terminal.manual  # 下一轮无需等待常规轮询间隔。
    events.clear()
    terminal.refresh_once()
    assert events[0][0] == 'quotes' and events[0][1][0] == newest
    assert events[1] == ('intraday', newest)
    assert app.state.store.get('stock_intraday', newest)['points']


@pytest.mark.parametrize('cached', [False, True])
def test_stock_intraday_failure_is_explicit_and_preserves_points(prepared, monkeypatch, cached):
    app, _ = prepared
    terminal = app.state.terminal
    key = 'LIVE.SH.600519'
    terminal.activate(key)
    points = [dict(time='2026-11-03T01:30:00Z',value='100',volume=100)] if cached else []
    if cached:
        app.state.store.put('stock_intraday',dict(id=key,points=points,error=None))
    class FailedSource(IndexSource):
        def stock_intraday(self, sid):
            raise ProviderError('INTRADAY_UNAVAILABLE','分时来源超时')
    terminal.provider_factory = FailedSource
    monkeypatch.setattr(terminal.market_data,'sync',lambda *args: {'quotes_updated':0,'errors':[]})
    terminal.refresh_once()
    result = terminal.stock_intraday(key)
    assert result['points'] == points
    assert result['error'] == '分时来源超时'


def test_eight_index_cached_charts_and_no_duplicate_daily_requests(prepared):
    app, client = prepared
    terminal = app.state.terminal
    IndexSource.calls = []
    terminal.provider_factory = IndexSource
    terminal.refresh_once()
    overview = data(client.get('/api/v1/market/overview'))
    assert len(overview['indices']) == 8
    assert overview['indices'][0]['price'] == '3200'
    assert overview['indices'][1]['price'] is None
    assert overview['rankings']['gainers'] == [] and overview['breadth'] is None
    for tf in ['1d','1w','1mo']:
        chart = data(client.get('/api/v1/market/indices/sh000001/bars?timeframe='+tf))
        assert chart['bars'][0]['close'] == '3200'
        assert all(len(values) == len(chart['bars']) for values in chart['indicators'].values())
        assert {'ma10', 'ma60', 'ma120', 'ma250', 'macd_dif', 'macd_dea', 'k', 'd', 'j', 'rsi6'} <= chart['indicators'].keys()
    assert data(client.get('/api/v1/market/indices/sh000001/intraday'))['points']
    terminal.refresh_once()
    assert IndexSource.calls.count('daily') == 1
    assert app.state.store.get('index_daily', 'sh000001')['history_limit'] == 2000
    assert client.get('/api/v1/market/indices/invalid/intraday').status_code == 422


def test_polling_reads_are_throttled_and_disable_prevents_implicit_fetch(prepared):
    app, client = prepared
    terminal = app.state.terminal
    for _ in range(10):
        data(client.get('/api/v1/market/indices/sh000001/intraday'))
        with terminal.state_lock:
            if _ == 0:
                assert terminal.manual
                terminal.manual = False
            else:
                assert not terminal.manual
    data(client.patch('/api/v1/data/refresh', json={'enabled':False}))
    terminal.chart_queued_at.clear()
    data(client.get('/api/v1/market/indices/sh000001/intraday'))
    assert not terminal.manual
    assert client.patch('/api/v1/data/refresh', json={'interval_seconds':5}).status_code == 422
    assert client.patch('/api/v1/data/refresh', json={'interval_seconds':True}).status_code == 422


def test_closed_market_gets_share_300_second_poll_interval(prepared, monkeypatch):
    app, _ = prepared
    terminal = app.state.terminal
    key = 'LIVE.SH.600519'
    terminal.activate(key)
    terminal.manual = False
    clock = [160.0]
    monkeypatch.setattr('backend.terminal_data.time', SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr('backend.terminal_data.market_open', lambda:False)
    terminal.next_poll = 400
    terminal.chart_queued_at['sh000001'] = terminal.stock_queued_at[key] = 100
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('index_intraday', dict(id='sh000001',points=[]))
        app.state.store.put('stock_intraday', dict(id=key,points=[]))
    assert terminal.effective_interval() == 300
    for now in [160,200,300,399]:
        clock[0] = now
        terminal.intraday('sh000001')
        terminal.stock_intraday(key)
        assert not terminal.manual
    clock[0] = 400
    terminal.intraday('sh000001')
    assert terminal.manual
    terminal.manual = False
    terminal.stock_intraday(key)
    assert terminal.manual


def test_first_missing_chart_initializes_but_gets_cannot_bypass_failure_backoff(prepared, monkeypatch):
    app, _ = prepared
    terminal = app.state.terminal
    clock = [100.0]
    monkeypatch.setattr('backend.terminal_data.time', SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr('backend.terminal_data.market_open', lambda:True)
    terminal.next_poll = 1000
    terminal.intraday('sh000688')
    assert terminal.manual  # 新标的首次缺缓存，不等待休市周期。
    terminal.manual = False
    terminal.failures = 5
    assert terminal.effective_interval() == 900
    terminal.intraday('sh000016')
    assert not terminal.manual  # 新标的也不能绕过上游失败退避。
    key = 'LIVE.SH.600519'
    terminal.activate(key)
    terminal.manual = False
    for now in [160,300,600,999]:
        clock[0] = now
        terminal.intraday('sh000688')
        terminal.stock_intraday(key)
        assert not terminal.manual
    clock[0] = 1000
    terminal.intraday('sh000016')
    assert terminal.manual


@pytest.mark.parametrize('field,revision', [('open','3101'),('high','3251'),('low','3051'),
    ('close','3201'),('volume',10001),('amount','123')])
def test_index_history_conflict_preserves_whole_old_series_and_updates_intraday(prepared, field, revision):
    app, _ = prepared
    terminal = app.state.terminal
    terminal.provider_factory = IndexSource
    terminal.refresh_once()
    original = app.state.store.get('index_daily','sh000001')
    original['checked_date'] = 'force-recheck'
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('index_daily',original)
    class Revised(IndexSource):
        def daily(self,symbol):
            row = super().daily(symbol)[0]
            new = {**row, 'time':'2026-10-29'}
            return [new, {**row,field:revision}]
        def intraday(self,symbol):
            row = super().intraday(symbol)
            row['points'][0]['value'] = '3210'
            return row
    terminal.provider_factory = Revised
    status = terminal.refresh_once()
    assert 'HISTORY_CONFLICT' in status['error']
    assert app.state.store.get('index_daily','sh000001') == original
    assert terminal.intraday('sh000001')['points'][0]['value'] == '3210'


def test_index_history_numeric_format_and_source_metadata_are_not_conflicts(prepared):
    app, _ = prepared
    terminal = app.state.terminal
    terminal.provider_factory = IndexSource
    terminal.refresh_once()
    old = app.state.store.get('index_daily','sh000001')
    old['checked_date'] = 'force-recheck'
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('index_daily',old)
    class MetadataRevision(IndexSource):
        def daily(self,symbol):
            return [{**super().daily(symbol)[0], 'close':'3200.00', 'volume':'10000.0',
                     'source_time':'changed', 'fetched_at':'later'}]
    terminal.provider_factory = MetadataRevision
    assert terminal.refresh_once()['error'] is None
    saved = app.state.store.get('index_daily','sh000001')
    assert saved['bars'] == old['bars']
    assert saved['checked_date'] != 'force-recheck'


def test_refresh_failure_keeps_index_and_chart_cache_and_sets_backoff(prepared):
    app, client = prepared
    terminal = app.state.terminal
    terminal.provider_factory = IndexSource
    terminal.refresh_once()
    before = data(client.get('/api/v1/market/overview'))['indices']
    class Broken(IndexSource):
        def quotes(self): raise ProviderError('FAILED', '固定报价失败')
        def intraday(self, symbol): raise ProviderError('FAILED', '固定分时失败')
    terminal.provider_factory = Broken
    status = terminal.refresh_once()
    assert status['error'] and terminal.failures == 1
    assert data(client.get('/api/v1/market/overview'))['indices'] == before
    assert data(client.get('/api/v1/market/indices/sh000001/intraday'))['points']


@pytest.mark.parametrize('quote_failed', [False, True])
def test_history_conflict_does_not_delay_unmonitored_watch_quotes(prepared, monkeypatch, quote_failed):
    app, _ = prepared
    terminal = app.state.terminal
    key = 'LIVE.SH.600519'
    terminal.activate(key)
    app.state.store.put('watch', dict(id='unmonitored', security_id=key,
                                    group_name='我的自选', monitor_enabled=False))
    terminal.provider_factory = IndexSource
    monkeypatch.setattr('backend.terminal_data.market_open', lambda: True)
    calls = []

    def sync(ids, daily=False):
        calls.append((list(ids), daily))
        return dict(quotes_updated=0 if daily or quote_failed else len(ids),
                    errors=['历史存在数值修订，保留原数据'] if daily else
                           ['固定报价失败'] if quote_failed else [])

    monkeypatch.setattr(terminal.market_data, 'sync', sync)
    terminal.failures = 5
    for _ in range(3):
        status = terminal.refresh_once()
        assert '历史存在数值修订' in status['error']
        assert app.state.store.get('watch', 'unmonitored')['monitor_enabled'] is False
        if not quote_failed:
            assert terminal.failures == 0
            assert terminal.effective_interval() == 60
    assert len([ids for ids, daily in calls if not daily and key in ids]) == 3
    if quote_failed:
        assert terminal.failures == 8
        assert terminal.effective_interval() == 900


def test_refresh_mutex(prepared):
    app, _ = prepared
    terminal = app.state.terminal
    terminal.provider_factory = lambda: pytest.fail('互斥时不得请求上游')
    terminal.run_lock.acquire()
    try:
        terminal.refresh_once()
    finally:
        terminal.run_lock.release()


def test_rankings_use_separate_ttl_and_keep_old_cache_on_failure(prepared):
    app, _ = prepared
    terminal = app.state.terminal
    class RankingSource:
        calls = 0
        def rankings(self):
            RankingSource.calls += 1
            return dict(gainers=[{'id':'LIVE.SH.600519'}],losers=[],amount=[])
        def close(self): pass
    terminal.ranking_provider_factory = RankingSource
    terminal.refresh_rankings()
    terminal.refresh_rankings()
    assert RankingSource.calls == 1
    assert terminal.overview()['rankings']['gainers'][0]['id'] == 'LIVE.SH.600519'
    class Broken(RankingSource):
        def rankings(self): raise ProviderError('FAILED', '固定排行失败')
    terminal.ranking_provider_factory = Broken
    terminal.ranking_next = 0
    terminal.refresh_rankings()
    assert terminal.ranking_error
    assert terminal.overview()['rankings']['gainers'][0]['id'] == 'LIVE.SH.600519'


def test_close_window_runs_history_again_and_deduplicates(prepared, monkeypatch):
    app, _ = prepared
    terminal = app.state.terminal
    terminal.activate('LIVE.SH.600519')
    terminal.provider_factory = IndexSource
    calls = []
    def sync(ids, sync_daily=False):
        calls.append(sync_daily)
        return dict(quotes_updated=1,errors=[])
    terminal.market_data.sync = sync
    class Morning(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,29,2,0,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr('backend.terminal_data.datetime', Morning)
    terminal.refresh_once()
    terminal.refresh_once()
    assert calls.count(True) == 1
    class Closing(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,29,9,0,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr('backend.terminal_data.datetime', Closing)
    terminal.refresh_once()
    terminal.refresh_once()
    assert calls.count(True) == 2


def test_index_intraday_parser_normalizes_volume_and_never_joins_dates():
    provider = TerminalProvider()
    raw = {'data':{'sh000001':{'data':{'date':'20261029', 'data':['0930 3200 10 1000','0931 3201 15 1500']}}}}
    provider.get = lambda *args: json.dumps(raw).encode()
    parsed = provider.intraday('sh000001')
    assert [x['volume'] for x in parsed['points']] == [1000, 500]
    assert all(x['time'].startswith('2026-10-29') for x in parsed['points'])
    assert parsed['average_supported'] is False
    assert all(x['average_price'] is None for x in parsed['points'])
    provider.close()


def test_stock_intraday_cache_refresh_and_disabled_gets(prepared):
    app, client = prepared
    terminal = app.state.terminal
    data(client.post('/api/v1/securities/LIVE.SH.600519/activate', json={}))
    assert client.get('/api/v1/market/intraday?security_id=DEMO.SH.600519').status_code == 422
    assert data(client.get('/api/v1/market/intraday?security_id=LIVE.SH.600519'))['points'] == []
    class StockSource(IndexSource):
        def stock_intraday(self,key):
            return dict(symbol='sh600519', points=[dict(time='2026-10-29T07:30:00Z',value='1400',volume=100)],
                        source='固定测试分时',source_time='2026-10-29T07:30:00Z',trade_date='2026-10-29',error=None)
    terminal.provider_factory = StockSource
    terminal.market_data.sync = lambda *a: dict(quotes_updated=1,errors=[])
    terminal.refresh_once()
    parsed = data(client.get('/api/v1/market/intraday?security_id=LIVE.SH.600519'))
    assert parsed['points'][0]['value'] == '1400'
    assert parsed['points'][0]['time'].endswith('07:30:00Z')
    terminal.configure({'enabled':False})
    terminal.manual = False
    terminal.stock_queued_at.clear()
    assert data(client.get('/api/v1/market/intraday?security_id=LIVE.SH.600519')) == parsed
    assert not terminal.manual


def test_existing_index_cache_cannot_expose_stock_average_as_index_points(prepared):
    app, client=prepared
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('index_intraday',dict(id='sh000001',symbol='sh000001',
            points=[dict(time='2026-11-03T07:00:00Z',value='3600',volume=100,average_price='14.88')],
            source='test',source_time='2026-11-03T07:00:00Z',error=None))
    row=data(client.get('/api/v1/market/indices/sh000001/intraday'))
    assert row['average_supported'] is False and row['points'][0]['average_price'] is None
    assert app.state.store.get('index_intraday','sh000001')['points'][0]['average_price']=='14.88'


@pytest.mark.parametrize('key,symbol,multiplier', [('LIVE.SH.600519','sh600519',100),('LIVE.SH.688981','sh688981',1),('LIVE.SZ.302132','sz302132',100)])
def test_stock_intraday_verified_volume_units(key,symbol,multiplier):
    provider = TerminalProvider()
    raw = {'data':{symbol:{'data':{'date':'20261029','data':['1500 100 10 1000','1530 100 15 1500']}}}}
    provider.get = lambda *args: json.dumps(raw).encode()
    parsed = provider.stock_intraday(key)
    assert [row['volume'] for row in parsed['points']] == [10*multiplier,5*multiplier]
    assert len(parsed['points']) == 2
    provider.close()


def test_index_namespace_and_weekday_session_hint():
    assert normalize_security_id('SZ.302132')[0] == 'SZ.302132'
    with pytest.raises(ProviderError): normalize_security_id('SH.000001')
    assert normalize_security_id('SH.000001', allow_index=True)[1] == 'sh000001'
    assert market_open(datetime(2026,10,29,2,0,tzinfo=timezone.utc))
    assert not market_open(datetime(2026,10,31,2,0,tzinfo=timezone.utc))


def test_intraday_average_uses_actual_cumulative_amount_not_average_of_prices():
    provider=TerminalProvider()
    raw={'data':{'sz300502':{'data':{'date':'20261103','data':[
        '0930 100 10 100000', '0931 110 30 320000', '0932 110 40']}}}}
    provider.get=lambda *args: json.dumps(raw).encode()
    try:
        points=provider.stock_intraday('LIVE.SZ.300502')['points']
        assert points[1]['volume']==2000
        assert points[1]['average_price']=='106.6667'
        assert points[1]['cumulative_volume']==3000 and points[1]['cumulative_amount']=='320000'
        assert points[2]['average_price'] is None
    finally:
        provider.close()


def test_blocked_primary_uses_whole_backup_series_with_independent_units():
    calls=[]
    def transport(request):
        calls.append(request)
        if request.url.host=='web.ifzq.gtimg.cn':
            return httpx.Response(501,text='<html>blocked</html>')
        assert request.headers['referer']=='https://quote.eastmoney.com/'
        assert request.url.params['secid']=='1.688066'
        return httpx.Response(200,json={'rc':0,'data':{'code':'688066','market':1,'preClose':6.28,'trends':[
            '2026-11-03 09:30,6.28,6.28,6.28,6.28,10,6280,6.280',
            '2026-11-03 09:31,6.28,6.30,6.30,6.28,20,12600,6.293']}})
    provider=TerminalProvider();provider.client.close()
    provider.client=httpx.Client(transport=httpx.MockTransport(transport))
    try:
        row=provider.stock_intraday('LIVE.SH.688066')
        assert row['source']=='东方财富公开分时' and row['fallback'] and row['error'] is None
        assert 'HTTP 501' in row['primary_error']
        assert [x['volume'] for x in row['points']]==[1000,2000]
        assert row['points'][-1]['cumulative_volume']==3000
        assert row['points'][-1]['average_price']=='6.2933'
        assert row['previous_close']=='6.28'
        provider.stock_intraday('LIVE.SH.688066')
        assert sum(r.url.host=='web.ifzq.gtimg.cn' for r in calls)==1
    finally:provider.close()


@pytest.mark.parametrize('failure',['both_failed','wrong_identity','mixed_dates','negative_volume','empty'])
def test_backup_rejects_invalid_series_without_fake_success(failure):
    def transport(request):
        if request.url.host=='web.ifzq.gtimg.cn' or failure=='both_failed':
            return httpx.Response(501)
        content={'code':'301015','market':0,'trends':['2026-11-03 09:30,25,25,25,25,10,25000,25']}
        if failure=='wrong_identity':content['code']='300502'
        if failure=='mixed_dates':content['trends'].append('2026-11-04 09:31,25,25,25,25,10,25000,25')
        if failure=='negative_volume':content['trends']=['2026-11-03 09:30,25,25,25,25,-10,25000,25']
        if failure=='empty':content['trends']=[]
        return httpx.Response(200,json={'rc':0,'data':content})
    provider=TerminalProvider();provider.client.close()
    provider.client=httpx.Client(transport=httpx.MockTransport(transport))
    try:
        with pytest.raises(ProviderError,match='腾讯分时.*东方财富分时'):
            provider.stock_intraday('LIVE.SZ.301015')
    finally:provider.close()


def test_eastmoney_trade_tape_validates_identity_and_maps_only_verified_fields():
    def transport(request):
        assert request.url.host == 'push2.eastmoney.com'
        assert request.url.params['secid'] == '0.301015'
        return httpx.Response(200, json={'rc':0,'data':{'code':'301015','market':0,'details':[
            '14:59:58,25.72,50,12,1','15:00:00,25.72,3762,235,2','15:00:01,25.71,3,1,9']}})
    provider=TerminalProvider();provider.client.close()
    provider.client=httpx.Client(transport=httpx.MockTransport(transport))
    try:
        result=provider.stock_trades('LIVE.SZ.301015')
        assert result['source']=='东方财富公开逐笔成交'
        assert result['trades']==[
            {'time':'14:59:58','price':'25.72','volume_lots':50,'side':'BUY'},
            {'time':'15:00:00','price':'25.72','volume_lots':3762,'side':'SELL'},
            {'time':'15:00:01','price':'25.71','volume_lots':3,'side':'UNKNOWN'},
        ]
        assert provider.client is not None
    finally:provider.close()


def test_trade_tape_endpoint_uses_read_only_provider(prepared):
    app,client=prepared
    class Trades:
        def stock_trades(self, security_id):
            assert security_id=='LIVE.SZ.301015'
            return {'security_id':security_id,'trades':[],'source':'固定测试','fetched_at':'2026-11-04T07:00:00Z'}
        def close(self): pass
    app.state.terminal.provider_factory=Trades
    response=client.get('/api/v1/market/trades?security_id=LIVE.SZ.301015')
    assert response.status_code==200
    assert response.json()['data']['source']=='固定测试'


def test_manual_retry_prioritizes_target_even_when_auto_disabled(prepared):
    app,client=prepared
    terminal=app.state.terminal
    terminal.activate('LIVE.SH.600519');terminal.configure({'enabled':False})
    terminal.manual=False
    response=client.post('/api/v1/market/refresh?security_id=LIVE.SH.600519',json={})
    assert response.status_code==200 and terminal.manual
    assert app.state.store.get('terminal_recent','LIVE.SH.600519')
    terminal.manual=False
    assert client.post('/api/v1/market/refresh?security_id=DEMO.SH.600519',json={}).status_code==422
    assert not terminal.manual
