from datetime import datetime, timezone
from decimal import Decimal
import threading
import time

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.board_positions import position_rows


def board(code='BK1000', **extra):
    return dict(id=code, code=code, name='测试行业', source_time='2026-11-06T07:00:00Z',
                net_inflow='100', amount='1000', ratio_3d=None, **extra)


def test_weighted_windows_use_real_trade_days_and_current_snapshot():
    history = {'BK1000': [dict(time='2026-11-04', net_inflow='-80', amount='800'),
                          dict(time='2026-11-05', net_inflow='10', amount='100'),
                          dict(time='2026-11-06', net_inflow='999', amount='1000')]}
    r = position_rows([board()], history, ['2026-11-04', '2026-11-05', '2026-11-06'])[0]
    assert Decimal(r['position_today']) == 10
    assert Decimal(r['position_2d']) == 10  # 当前日100覆盖历史999，非对百分比简单平均。
    assert abs(Decimal(r['position_3d']) - Decimal(30) / 1900 * 100) < Decimal('.000001')


def test_missing_day_never_skipped_and_missing_amount_never_zero_filled():
    rows = [board(), {**board('BK1001'), 'amount': None}, {**board('BK1002'), 'amount': '0'}]
    history = {'BK1000': [dict(time='2026-11-04', net_inflow='10', amount='100')]}
    result = position_rows(rows, history, ['2026-11-04', '2026-11-05', '2026-11-06'])
    assert result[0]['position_2d'] is None and result[0]['position_3d'] is None
    assert result[1]['position_today'] is None and result[2]['position_today'] is None


def test_monday_uses_friday_not_calendar_yesterday_and_equal_ranks_tie():
    a = {**board(), 'source_time': '2026-11-09T03:00:00Z'}
    b = {**board('BK1001'), 'source_time': a['source_time']}
    h = {a['code']: [dict(time='2026-11-06', net_inflow='-50', amount='500')]}
    result = position_rows([a, b], h, ['2026-11-05', '2026-11-06'])
    assert abs(Decimal(result[0]['position_2d']) - Decimal(50) / 1500 * 100) < Decimal('.000001')
    assert result[0]['rank_today'] == result[1]['rank_today'] == 1
    assert result[1]['position_2d'] is None and 'rank_2d' not in result[1]


def test_native_three_day_fallback_not_today_copied_as_history():
    r = position_rows([{**board(), 'ratio_3d': '-2.37'}], {}, [])[0]
    assert r['position_3d'] == '-2.37' and r['position_2d'] is None


def test_offline_route_returns_cached_live_ratios_and_rejects_kind(tmp_path):
    app = create_app(tmp_path/'positions.db', network_enabled=False)
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('board_cache', dict(id='list:industry', fetched_at=datetime.now(timezone.utc).isoformat(), rows=[board()]))
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin'] = 'http://127.0.0.1:8765'
        result = client.get('/api/v1/market/boards/positions').json()['data']
        assert Decimal(result['rows'][0]['position_today']) == 10
        assert result['rows'][0]['position_2d'] is None
        assert result['covered'] == 0 and not result['enabled'] and not app.state.boards.pending
        assert client.get('/api/v1/market/boards/positions?kind=invalid').status_code == 422
        assert client.post('/api/v1/market/boards/refresh?section=position', json={}).status_code == 200
        assert not app.state.boards.pending
    app.state.store.db.close()


def test_fill_is_bounded_persists_partial_and_keeps_failed_old_history(tmp_path):
    app = create_app(tmp_path/'fill.db', network_enabled=False)
    service, store = app.state.boards, app.state.store
    service.terminal.network_enabled = True
    service.terminal.config = lambda: {'enabled': True}
    rows = [board('BK' + str(1000+i)) for i in range(11)]
    stamp = datetime.now(timezone.utc).isoformat()
    with store.lock, store.db:
        store.put('board_cache', dict(id='list:industry', fetched_at=stamp, rows=rows))
        store.put('board_cache', dict(id='position-snapshot:industry', fetched_at=stamp,
            calendar=['2026-11-05'], rows=[dict(code='BK1005', days=[dict(time='2026-11-05',net_inflow='-1',amount='10')])]))
    active, maximum, lock = 0, 0, threading.Lock()
    class Provider:
        def chart(self, code, period, limit=30):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.01)
                if code == 'BK1005': raise ValueError('unavailable')
                if period == 'funds': return dict(flows=[dict(time='2026-11-05', net_inflow='10'),dict(time='2026-11-06',net_inflow='20')])
                return dict(bars=[dict(time='2026-11-05', amount='100'),dict(time='2026-11-06',amount='200')])
            finally:
                with lock: active -= 1
        def close(self): pass
    service.factory = Provider
    result = service.fill_position_history('industry')
    snapshot = store.get('board_cache', 'position-snapshot:industry', False)
    assert result['completed'] == 11 and result['failed'] == 1 and 2 <= maximum <= 4
    assert len(snapshot['rows']) == 11
    assert next(r for r in snapshot['rows'] if r['code']=='BK1005')['days'][0]['net_inflow']=='-1'
    service.stop(); store.db.close()
