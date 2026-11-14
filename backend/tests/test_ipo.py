from types import SimpleNamespace
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.ipo_data import IpoProvider, normalize, number, security_id, document_url


def share(**values):
    return dict(SECUCODE='688827.SH', SECURITY_CODE='688827', SECURITY_NAME_ABBR='测试新股',
        APPLY_CODE='787827', APPLY_DATE='2026-10-29 00:00:00', LISTING_DATE='2026-11-10 00:00:00',
        ISSUE_NUM=1712.86, ONLINE_ISSUE_NUM=5481000, ONLINE_APPLY_UPPER=4000,
        TOP_APPLY_MARKETCAP=4, ISSUE_PRICE=45.37, **values)


def test_share_units_and_unlisted_quote_are_not_fake_prices():
    r = normalize(share(LATELY_PRICE=45.37, CHANGE_RATE=0), 'apply', '2026-11-09')
    assert r['issue_shares'] == '17128600.00'
    assert r['online_shares'] == '5481000' and r['apply_limit'] == '4000'
    assert r['required_cap'] == '40000'
    assert r['price'] is None and r['security_id'] is None
    assert r['apply_code'] != r['code']
    assert r['status'] == '待上市'


def test_beijing_cash_and_return_units_are_separate_from_shanghai_lottery():
    row = share(IS_BEIJING=1, APPLY_AMT_UPPER=1436.5425, PER_SHARES_INCOME=2801.62, PROFIT=9999)
    row.update(SECUCODE='920085.BJ', SECURITY_CODE='920085', LISTING_DATE='2026-11-06 00:00:00')
    r = normalize(row, 'apply', '2026-11-09')
    assert r['required_cap'] is None and r['required_cash'] == '14365425.0000'
    assert r['first_profit'] is None and r['profit_per_100'] is None
    row.update(CLOSE_PRICE=39.25,ISSUE_PRICE=17.79)
    assert normalize(row,'apply','2026-11-09')['profit_per_100']=='2146.00'
    assert r['security_id'] is None
    assert security_id('920085.SZ') is None
    assert security_id('A26221.SH') is None
    assert security_id('688827.SH') == 'LIVE.SH.688827'
    assert document_url('javascript:alert(1)') is None


def test_lottery_return_uses_actual_prices_and_missing_is_unknown():
    row = share(LATELY_PRICE=50, PROFIT=9999, EACHBALLOT_SHARES=500, CLOSE_PRICE=50)
    r = normalize(row, 'listed', '2026-11-11')
    assert r['first_profit'] == '2315.00' and r['ballot_shares'] == '500'
    assert r['total_return'] == '10.2050'
    assert number(None) is None and number('NaN') is None and number(True) is None


def test_quote_join_units_source_time_and_first_profit_are_independent():
    row=share(f2=50, f3=2.5, f5=109255, f6=363430383.07, f8=58.66, f9=69.54, f20=2424400000,
        f100='专用设备', f124=1794209639, EACHBALLOT_SHARES=500, CLOSE_PRICE=49, PROFIT=9999)
    r=normalize(row,'listed','2026-11-11')
    assert r['volume_lots']=='109255' and r['amount']=='363430383.07'
    assert r['price']=='50' and r['turnover_rate']=='58.66' and r['market_cap']=='2424400000'
    assert r['source_time'].endswith('Z') and r['source_date'] is None
    assert r['first_profit']=='1815.00' and r['source_ipo_profit']=='9999'


def test_provider_uses_fixed_report_filters_and_rejects_invalid_response():
    def respond(request):
        p = request.url.params
        assert p['reportName'] == 'RPTA_APP_IPOAPPLY'
        assert '069001001006' in p['filter'] and 'LISTING_DATE' in p['filter']
        return httpx.Response(200, json={'success': True, 'result': {'data': [share()], 'count': 1, 'pages': 1}})
    p = IpoProvider(httpx.Client(transport=httpx.MockTransport(respond)))
    assert len(p.fetch('listed', 'star', 1)['rows']) == 1
    p.close()


def test_cache_failure_preserves_data_and_disabled_get_does_not_fetch(tmp_path):
    app = create_app(tmp_path/'ipo.db', network_enabled=False)
    ipo = app.state.ipo
    saved = dict(id='apply:all:1', rows=[{'id':'test', 'name':'原资料'}], fetched_at='2020-01-01T00:00:00Z')
    with app.state.store.lock, app.state.store.db: app.state.store.put('ipo_cache', saved)
    def fail(): raise ValueError('source failed')
    ipo.factory = fail
    ipo.refresh('apply:all:1', 'apply', 'all', 1)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        data = client.get('/api/v1/market/ipo').json()['data']
        assert data['rows'] == saved['rows'] and data['error'] and not data['refreshing']
        assert not data['enabled']
        for query in ['section=bad', 'board=bad', 'page=101', 'page=0']:
            assert client.get('/api/v1/market/ipo?'+query).status_code == 422
    app.state.store.db.close()
