"""动态图表使用快照，完成历史/算法输入不变；全部测试离线。"""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app, indicators
from backend.chart_data import chart_bars


NOW = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
QUOTE = dict(open='12', high='14.123', low='11', price='13', volume=300, amount='3900',
             source_time='2026-11-03T01:59:00Z', fetched_at='2026-11-03T01:59:01Z')
HISTORY = [dict(time=f'2026-10-{day}', open='10', high='11', low='9', close='10', volume=100, amount='1000')
           for day in range(26, 31)] + [dict(time='2026-11-02', open='10.5', high='12.3', low='10',
                                           close='12', volume=200, amount='2400')]


def test_dynamic_repeated_updates_do_not_duplicate_or_mutate_history():
    original = deepcopy(HISTORY)
    for price in ('13', '14'):
        rows, current = chart_bars(HISTORY, {**QUOTE, 'price': price}, '1d', at=NOW)
        assert len(rows) == len(HISTORY) + 1
        assert rows[-1] == dict(time='2026-11-03', open='12', high='14.123', low='11', close=price, volume=300, amount='3900')
        assert current['time'] == current['trade_date'] == '2026-11-03' and not current['stale']
    assert HISTORY == original
    final = HISTORY + [dict(rows[-1], close='13.5')]
    rows, current = chart_bars(final, QUOTE, '1d', at=NOW)
    assert rows[-1]['close'] == '13.5' and current is None  # 已入库完成日线优先。


@pytest.mark.parametrize('timeframe', ['1w', '1mo'])
def test_today_updates_last_period_with_exact_ohlc_and_cumulative_volume(timeframe):
    rows, current = chart_bars(HISTORY, QUOTE, timeframe, at=NOW)
    assert len(rows) == 2
    assert rows[-1] == dict(time='2026-11-02', open='10.5', high='14.123', low='10', close='13', volume=500, amount='6300')
    assert current['time'] == '2026-11-02' and current['trade_date'] == '2026-11-03'
    rows, current = chart_bars(HISTORY[:-1], QUOTE, timeframe, at=NOW)
    assert rows[-1]['time'] == current['time'] == '2026-11-03' and rows[-1]['volume'] == 300


@pytest.mark.parametrize('changes', [
    {'source_time': '2026-11-02T07:00:00Z'}, {'source_time': '2026-11-04T01:30:00Z'},
    {'source_time': '2026-11-03T02:02:00Z'}, {'source_time': '2026-11-03T01:25:00Z'},
    {'source_time': '2026-11-03T09:59:00'}, {'source_time': 'invalid'}, {'source_time': None},
    {'open': '0'}, {'high': '12.9'}, {'low': '13'}, {'price': 'NaN'}, {'open': None},
    {'volume': 0}, {'volume': -1}, {'volume': 1.5},
])
def test_invalid_or_non_today_quote_cannot_create_a_bar(changes):
    rows, current = chart_bars(HISTORY, {**QUOTE, **changes}, '1d', at=NOW)
    assert rows == HISTORY and current is None


def test_old_today_quote_is_explicitly_stale_and_unknown_units_remain_unknown():
    rows, current = chart_bars(HISTORY, {**QUOTE, 'source_time': '2026-11-03T01:30:00Z', 'amount': None, 'volume': None}, '1w', at=NOW)
    assert current['stale'] and rows[-1]['amount'] is None and rows[-1]['volume'] is None
    rows, current = chart_bars([], {**QUOTE, 'source_time': '2026-11-07T01:30:00Z'}, '1d', at=datetime(2026, 11, 7, 2, tzinfo=timezone.utc))
    assert rows == [] and current is None


@pytest.mark.parametrize('kind', ['index', 'stock'])
def test_real_chart_apis_include_today_and_indicators_but_saved_inputs_stay_complete(tmp_path, monkeypatch, kind):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr('backend.chart_data.datetime', Clock)
    app = create_app(tmp_path / 'chart.db')
    store = app.state.store
    sid = 'LIVE.SH.600519'
    with store.lock, store.db:
        store.put('index_daily', dict(id='sh000001', bars=HISTORY))
        store.put('index_quote', dict(QUOTE, id='sh000001'))
        store.put('security', dict(id=sid, code='600519', name='测试', exchange='SSE'))
        store.put('market_snapshot', dict(QUOTE, id=sid))
        for row in HISTORY:
            store.db.execute('INSERT INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('tencent', sid, row['time'], row['open'], row['high'], row['low'], row['close'],
                 row['volume'], row['amount'], 'test', row['time'], 'test', 'hash', 'NONE'))
    saved = deepcopy(store.bars(sid))
    path = '/api/v1/market/indices/sh000001/bars' if kind == 'index' else '/api/v1/market/bars'
    try:
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            client.get('/api/v1/session')
            for tf in ('1d', '1w', '1mo'):
                response = client.get(path, params=dict(timeframe=tf, security_id=sid))
                assert response.status_code == 200, response.text
                chart = response.json()['data']
                assert chart['bars'][-1]['close'] == '13'
                assert chart['current_bar']['trade_date'] == '2026-11-03'
                base = indicators(chart['bars'])
                assert {key: chart['indicators'][key] for key in base} == base
                assert all(len(values) == len(chart['bars']) for values in chart['indicators'].values())
                assert {'boll_mid','sar','pdi','obv','bbi'} <= chart['indicators'].keys()
                assert all(len(values) == len(chart['bars']) for values in chart['indicators'].values())
                if tf == '1d':
                    assert chart['indicators']['ma5'][-1] == '11.00'
            store.put('market_snapshot', dict(QUOTE, id='DEMO.SH.600519'))
            store.put('security', dict(id='DEMO.SH.600519', code='600519', name='演示', exchange='SSE'))
            demo = client.get('/api/v1/market/bars?security_id=DEMO.SH.600519').json()['data']
            assert demo['bars'] == [] and demo['current_bar'] is None
            app.state.terminal.configure({'enabled': False})
            app.state.terminal.manual = False
            app.state.terminal.stock_queued_at.clear()
            for _ in range(3):
                assert client.get(path, params=dict(security_id=sid)).status_code == 200
            assert not app.state.terminal.manual
        assert store.bars(sid) == saved
        assert store.get('index_daily', 'sh000001')['bars'] == HISTORY
    finally:
        store.db.close()
