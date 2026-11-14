"""目录快照持久化、缓存读取、后台限量和故障隔离。"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.catalog_quotes import public_quote, save_quote
from backend.providers import ProviderError


@pytest.fixture
def prepared(tmp_path):
    app = create_app(tmp_path / 'quotes.db')
    store, terminal = app.state.store, app.state.terminal
    terminal.catalog.import_rows([dict(code=f'{i:06}', name=f'证券{i}', market=0)
                                  for i in range(1, 121)], '固定目录', minimum=1)
    worker = terminal.catalog_quotes
    worker.enabled = lambda: True
    worker.interval = lambda: 30
    worker.market_open = lambda: True
    calls = []

    class Source:
        def quotes(self, ids):
            calls.append(ids)
            return [quote(sid) for sid in ids]
        def close(self):
            pass

    terminal.market_data.provider_factory = Source
    yield app, store, worker, calls
    store.db.close()


def quote(sid, *, seconds=0):
    at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return dict(security_id=sid, code=sid[-6:], name='固定证券', price='12.50', change_pct='1.2',
                amount='1234500', volume=10000, pe_ttm='10.2', quote_schema_version=2,
                fetched_at=at, source_time=at)


def test_full_catalog_backfill_batched_persisted_without_business_side_effects(prepared):
    app, store, worker, calls = prepared
    assert [worker.refresh_once() for _ in range(3)] == [50, 50, 20]
    assert worker.refresh_once() == 0
    assert max(map(len, calls)) == 50
    assert worker.status()['covered'] == 120
    for kind in ('security', 'watch', 'terminal_recent', 'market_sync_run', 'market_history', 'signal', 'account'):
        assert store.all(kind) == []
    assert store.db.execute('SELECT count(*) FROM provider_bars').fetchone()[0] == 0
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = create_app(path)
    assert reopened.state.terminal.catalog_quotes.status()['covered'] == 120
    assert reopened.state.store.get('market_snapshot', 'LIVE.SZ.000120')['price'] == '12.50'
    reopened.state.store.db.close()


def test_visible_page_first_and_repeated_get_only_reads_cache(prepared):
    app, store, worker, calls = prepared
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        for _ in range(3):
            r = client.get('/api/v1/securities?catalog=true&limit=20&offset=100').json()
            assert r['data'][0]['quote'] is None
        assert calls == []
        assert worker.refresh_once() == 50
        assert calls[0][:20] == [f'SZ.{i:06}' for i in range(101, 121)]
        row = client.get('/api/v1/securities?catalog=true&limit=20&offset=100').json()
        assert row['data'][0]['quote']['as_of']
        assert row['meta']['catalog_quotes']['covered'] == 50
        client.get('/api/v1/securities?q=000101')
        assert len(calls) == 1


def test_closed_auto_and_stopped_worker_never_fetch(prepared):
    _, store, worker, calls = prepared
    worker.enabled = lambda: False
    worker.request([{'id': 'LIVE.SZ.000001'}])
    assert not worker.visible
    assert worker.refresh_once() == 0 and not calls
    worker.enabled = lambda: True
    worker.stopping.set()
    assert worker.refresh_once() == 0 and not calls


def test_network_failure_keeps_cache_and_repeated_get_does_not_bypass_backoff(prepared):
    app, store, worker, calls = prepared
    saved = quote('SZ.000001', seconds=-400)
    save_quote(store, saved)
    def fail():
        calls.append('failed')
        raise ProviderError('NETWORK', '固定断网')
    app.state.market_data.provider_factory = fail
    assert worker.refresh_once() == 0
    for _ in range(3):
        worker.request([{'id': 'LIVE.SZ.000001'}])
        assert worker.refresh_once() == 0
    assert calls == ['failed']
    assert store.get('market_snapshot', 'LIVE.SZ.000001')['price'] == saved['price']
    assert worker.status()['error']


def test_bad_symbol_does_not_block_the_other_quotes(prepared):
    app, store, worker, calls = prepared
    original = app.state.market_data.provider_factory
    class WithUnavailable(original):
        def quotes(self, ids):
            if 'SZ.000001' in ids:
                calls.append(ids)
                raise ProviderError('QUOTE_MISSING', '腾讯未返回有效快照: SZ.000001')
            return super().quotes(ids)
    app.state.market_data.provider_factory = WithUnavailable
    assert worker.refresh_once() == 0
    assert worker.refresh_once() == 50
    assert 'SZ.000001' not in calls[-1]
    assert store.get('market_snapshot', 'LIVE.SZ.000002')['price'] == '12.50'


def test_current_page_refreshes_at_30_seconds_and_other_cached_rows_at_60(prepared):
    _, store, worker, calls = prepared
    for i in range(1, 121):
        save_quote(store, quote(f'SZ.{i:06}', seconds=-40))
    worker.request([{'id': 'LIVE.SZ.000120'}])
    assert worker.refresh_once() == 1
    assert calls == [['SZ.000120']]
    worker.market_open = lambda: False
    worker.request([{'id': 'LIVE.SZ.000119'}])
    assert worker.refresh_once() == 0
    assert len(calls) == 1


def test_visible_queue_bounded_deduplicated_and_stale_snapshot_cannot_overwrite(prepared):
    _, store, worker, _ = prepared
    worker.request([{'id': f'LIVE.SZ.{i:06}'} for i in range(1, 501)])
    assert len(worker.visible) == 300
    worker.request([{'id': 'LIVE.SZ.000001'}] * 10)
    assert len(worker.visible) == 300
    fresh = quote('SZ.000001')
    assert save_quote(store, fresh)
    assert not save_quote(store, {**quote('SZ.000001', seconds=-60), 'price': '1.00'})
    assert store.get('market_snapshot', 'LIVE.SZ.000001')['price'] == fresh['price']


def test_public_quote_same_for_catalog_search_and_watch(prepared):
    app, store, worker, calls = prepared
    worker.refresh_once()
    with store.lock, store.db:
        store.put('security', app.state.terminal.catalog.find('LIVE.SZ.000001'))
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        paged = client.get('/api/v1/securities?catalog=true&limit=1').json()['data'][0]
        searched = client.get('/api/v1/securities?q=000001').json()['data'][0]
        materialized = store.security('LIVE.SZ.000001')
        assert paged['quote'] == searched['quote'] == materialized['quote']
        assert paged['quote']['is_realtime'] is False
        assert paged['quote']['pe_ttm'] == '10.2'


def test_old_quote_schema_and_invalid_timestamp_read_safely():
    mapped = public_quote({'pe_dynamic': '20', 'source_time': 'bad'})
    assert mapped['pe_ttm'] == '20' and mapped['pe_dynamic'] is None
    assert mapped['stale'] is True


def test_snapshot_list_does_not_load_years_of_daily_bars(prepared, monkeypatch):
    app, store, worker, _ = prepared
    worker.refresh_once()
    with store.lock, store.db:
        store.put('security', app.state.terminal.catalog.find('LIVE.SZ.000001'))
    def forbidden(*args):
        raise AssertionError('快照列表不能加载历史日线')
    monkeypatch.setattr(store, 'bars', forbidden)
    assert store.security('LIVE.SZ.000001')['quote']['price'] == '12.50'
