"""Offline protocol tests: fixtures are samples, never fetched by tests."""
import json
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256

import httpx
import pytest

from backend.providers import KLINE_URL, QUOTE_URL, ProviderError, TencentProvider, normalize_security_id, parse_tencent_daily, parse_eastmoney_daily, parse_tencent_quotes, download_tencent_history


def quote_fixture(code="600000", prefix="sh", price="9.82", change="0.20", pct="2.08", volume="807530", amount="78932"):
    fields = [""] * 39
    for index, value in {0:"1",1:"浦发银行",2:code,3:price,4:"9.62",5:"9.56",6:volume,30:"20261027161456",31:change,32:pct,33:"9.87",34:"9.53",35:f"{price}/{volume}/789320000",36:volume,37:amount,38:"0.24"}.items():
        fields[index] = value
    return (f'v_{prefix}{code}="' + "~".join(fields) + '";').encode("gbk")


def daily_fixture(rows, code="sz000001", key="day"):
    return json.dumps({"code":0,"data":{code:{key:rows}}}).encode()


@pytest.mark.parametrize("code,expected", [("600000",("SH.600000","sh600000")),("SZ.000001",("SZ.000001","sz000001")),("SH.688001",("SH.688001","sh688001"))])
def test_normalize_a_shares(code, expected):
    assert normalize_security_id(code) == expected


@pytest.mark.parametrize("code", ["430001","SH.000001","SZ.600000","https://evil/a","sh600000,q=xx","900001","200001","not-code"])
def test_reject_non_a_share_or_arbitrary_urls(code):
    with pytest.raises(ProviderError): normalize_security_id(code)


def test_quote_preserves_identity_gbk_timestamp_units_and_hash():
    raw = quote_fixture()
    item = parse_tencent_quotes(raw,["600000"],datetime(2026,10,27,tzinfo=timezone.utc))[0]
    assert item["security_id"] == "SH.600000" and item["name"] == "浦发银行"
    assert item["price"] == "9.82" and item["high"] == "9.87" and item["low"] == "9.53"
    assert item["volume"] == 80753000 and item["volume_unit"] == "SHARES"
    assert item["amount"] == "789320000" and item["amount_unit"] == "CNY"
    assert item["source_time"] == "2026-10-27T08:14:56Z"
    assert item["fetched_at"] == "2026-10-27T00:00:00Z"
    assert item["raw_hash"] == sha256(raw).hexdigest()


def test_star_volume_is_shares_and_negative_change_is_preserved():
    item=parse_tencent_quotes(quote_fixture("688001",price="9.80",change="-0.20",pct="-2.00",volume="12345"),["688001"])[0]
    assert item["volume"] == 12345 and item["change"] == "-0.20" and item["change_pct"] == "-2.00"


def test_quote_parses_optional_market_metrics_and_five_level_book_with_source_units():
    fields = [""] * 61
    for index, value in {0:"1",1:"新易盛",2:"300502",3:"173.36",4:"158.40",5:"159.10",
        30:"20261103151400",31:"14.96",32:"9.44",33:"174.20",34:"157.80",36:"1200",37:"987654",
        38:"2.47",39:"16.59",41:"180.0",42:"150.0",43:"18.94",44:"120.5",45:"160.2",
        46:"9.71",47:"190.08",48:"142.56",49:"1.37",52:"15.95",53:"25.37"}.items():
        fields[index] = value
    for level in range(5):
        fields[9 + level * 2], fields[10 + level * 2] = str(173.3 - level / 10), str(100 + level)
        fields[19 + level * 2], fields[20 + level * 2] = str(173.4 + level / 10), str(200 + level)
    quote = parse_tencent_quotes((f'v_sz300502="' + "~".join(fields) + '";').encode('gbk'), ['SZ.300502'])[0]
    assert quote['turnover_rate'] == '2.47' and quote['volume_ratio'] == '1.37'
    assert quote['amplitude'] == '18.94' and quote['pe_ttm'] == '16.59'
    assert quote['pe_dynamic'] == '15.95' and quote['pe_static'] == '25.37'
    assert quote['float_market_cap'] == '12050000000.0' and quote['total_market_cap'] == '16020000000.0'
    assert quote['order_book']['volume_unit'] == 'LOT'
    assert quote['order_book']['bids'][0] == {'level': 1, 'price': '173.3', 'volume': 100}
    assert quote['order_book']['asks'][4] == {'level': 5, 'price': '173.8', 'volume': 204}


def test_optional_quote_fields_remain_unknown_when_source_fields_are_blank_or_zero():
    fields = [""] * 61
    for index, value in {0:"1",1:"新易盛",2:"300502",3:"173.36",4:"158.40",5:"159.10",
        30:"20261103151400",31:"14.96",32:"9.44",33:"174.20",34:"157.80",36:"1200",37:"987654"}.items():
        fields[index] = value
    fields[9:29] = ['0'] * 20
    quote = parse_tencent_quotes((f'v_sz300502="' + "~".join(fields) + '";').encode('gbk'), ['SZ.300502'])[0]
    assert quote['turnover_rate'] is None and quote['total_market_cap'] is None
    assert all(level['price'] is None and level['volume'] is None for level in quote['order_book']['bids'])


def test_quote_missing_or_identity_mismatch_is_error():
    for raw in (b'v_sh600000="";',quote_fixture().replace(b"~600000~",b"~600001~"),quote_fixture().replace(b"~9.82~",b"~NaN~",1)):
        with pytest.raises(ProviderError): parse_tencent_quotes(raw,["600000"])


def test_daily_excludes_today_future_and_preserves_unknown_amount():
    raw=daily_fixture([["2026-10-26","10","10.50","10.60","9.90","100"],["2026-10-27","10.5","11","11.2","10.4","200"],["2026-10-28","10.5","11","11.2","10.4","200"]])
    rows=parse_tencent_daily(raw,"SZ.000001",today=date(2026,10,27))
    assert len(rows)==1 and rows[0]["time"]=="2026-10-26"
    assert rows[0]["volume"]==10000 and rows[0]["amount"] is None
    assert rows[0]["amount_unit"]=="UNKNOWN" and rows[0]["source_time"]=="2026-10-26"
    assert rows[0]["complete"] is True and rows[0]["adjustment"]=="NONE"


def test_eastmoney_daily_parses_actual_turnover_without_inference():
    raw = json.dumps({"data":{"code":"301015","klines":[
        "2026-10-26,25.00,25.50,25.80,24.90,120000,3060000.00,2.10"
    ]}}).encode()
    rows = parse_eastmoney_daily(raw, "SZ.301015", today=date(2026, 10, 27))
    assert rows[0]["volume"] == 12000000
    assert rows[0]["amount"] == "3060000.00"
    assert rows[0]["amount_unit"] == "CNY"


def test_daily_star_volume_and_jsonp_adjustment_explicit():
    raw=daily_fixture([["2026-10-26","10","10.5","10.6","9.9","12345"]],code="sh688001",key="qfqday")
    rows=parse_tencent_daily(b"kline="+raw+b";","688001",today=date(2026,10,27),adjustment="qfq")
    assert rows[0]["volume"]==12345 and rows[0]["adjustment"]=="QFQ"


def test_qfq_allows_negative_display_prices_but_not_negative_raw_prices_or_volume():
    row = ['2002-06-18', '-2.3', '-2.1', '-2.0', '-2.4', '100']
    rows = parse_tencent_daily(daily_fixture([row], code='sh600510', key='qfqday'),
                              'SH.600510', adjustment='qfq')
    assert rows[0]['low'] == '-2.4' and rows[0]['close'] == '-2.1'
    with pytest.raises(ProviderError):
        parse_tencent_daily(daily_fixture([row], code='sh600510'), 'SH.600510')
    invalid = row[:]; invalid[5] = '-100'
    with pytest.raises(ProviderError):
        parse_tencent_daily(daily_fixture([invalid], code='sh600510', key='qfqday'),
                            'SH.600510', adjustment='qfq')
    eastmoney = json.dumps({'data': {'code':'600510', 'klines':[
        '2002-06-18,-2.3,-2.1,-2.0,-2.4,100,1000']}}).encode()
    assert parse_eastmoney_daily(eastmoney, 'SH.600510', adjustment='qfq')[0]['close'] == '-2.1'


def test_adjusted_history_for_old_stock_continues_beyond_eight_pages():
    start = date(2002, 1, 1)
    all_rows = [[(start+timedelta(days=i)).isoformat(), '10', '11', '12', '9', '100'] for i in range(5804)]
    calls = []
    def get(url, params):
        calls.append(params['param'])
        end = params['param'].split(',')[3]
        eligible = [row for row in all_rows if not end or row[0] <= end]
        return daily_fixture(eligible[-640:], code='sh600510', key='hfqday')
    result = download_tencent_history(get, 'SH.600510', adjustment='hfq')
    assert len(calls) == 10 and len(result) == 5804
    assert result[0]['time'] == all_rows[0][0] and result[-1]['time'] == all_rows[-1][0]


@pytest.mark.parametrize('fault', ['http', 'invalid_prices'])
def test_adjusted_history_falls_back_to_one_complete_source_with_real_provenance(fault):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == 'web.ifzq.gtimg.cn':
            return httpx.Response(501) if fault == 'http' else httpx.Response(200, content=
                daily_fixture([['2026-10-20','NaN','10','11','9','100']], code='sh600510', key='qfqday'))
        return httpx.Response(200, json={'data': {'code':'600510', 'market':1, 'dktotal':2, 'klines':[
            '2002-06-18,2.61,2.82,3.14,2.50,100,1000',
            '2026-10-20,6.61,6.36,6.70,6.30,200,1200']}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = TencentProvider(client).full_history('SH.600510', adjustment='qfq')
    assert len(calls) == 2 and calls[-1].url.params['fqt'] == '1'
    assert len(result) == 2 and all('东方财富' in row['source'] and '备用源' in row['source'] for row in result)
    assert result[0]['close'] == '2.82' and result[-1]['amount'] == '1200'
    assert all(row['adjustment'] == 'QFQ' for row in result)


@pytest.mark.parametrize('fault', ['incomplete', 'wrong_identity', 'missing_price', 'timeout'])
def test_adjusted_fallback_rejects_incomplete_or_invalid_series(fault):
    def handler(request):
        if request.url.host == 'web.ifzq.gtimg.cn': return httpx.Response(501)
        if fault == 'timeout': raise httpx.ReadTimeout('timeout', request=request)
        return httpx.Response(200, json={'data': {
            'code':'600519' if fault == 'wrong_identity' else '600510', 'dktotal':2 if fault == 'incomplete' else 1,
            'klines':['2002-06-18,NaN,2.82,3.14,2.50,100,1000' if fault == 'missing_price'
                      else '2002-06-18,2.61,2.82,3.14,2.50,100,1000']}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            TencentProvider(client).full_history('SH.600510', adjustment='qfq')
    assert error.value.code == 'HISTORY_UNAVAILABLE'


def test_amount_supplement_timeout_preserves_valid_tencent_history():
    def handler(request):
        if request.url.host == 'web.ifzq.gtimg.cn':
            return httpx.Response(200, content=daily_fixture([
                ['2026-10-20','10','11','12','9','100']], code='sh600510', key='qfqday'))
        raise httpx.ReadTimeout('timeout', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = TencentProvider(client).full_history('SH.600510', adjustment='qfq')
    assert len(rows) == 1 and rows[0]['amount'] is None and rows[0]['close'] == '11'


@pytest.mark.parametrize('adjustment,key', [('none','day'),('qfq','qfqday'),('hfq','hfqday')])
def test_history_pagination_keeps_requested_adjustment_on_every_page(adjustment, key):
    requests=[]
    start=date(2010,1,1)
    rows=[[(start+timedelta(days=i)).isoformat(), '10', '10.5', '10.6', '9.9', '100'] for i in range(2000)]
    def get(url, params):
        requests.append(params['param'])
        earlier=[(start-timedelta(days=1)).isoformat(), '10', '10.5', '10.6', '9.9', '100']
        return json.dumps({'code':0,'data':{'sh600000':{key:rows if len(requests)==1 else [earlier]}}}).encode()
    result=download_tencent_history(get,'600000',adjustment=adjustment)
    assert all(item['adjustment']==adjustment.upper() for item in result)
    assert requests[0].endswith(',' + ('' if adjustment == 'none' else adjustment))
    if adjustment != 'none':
        with pytest.raises(ProviderError): download_tencent_history(get,'600000',adjustment='invalid')


@pytest.mark.parametrize("row",[["2026-10-26","10","10.5","9","11","100"],["2026-10-26","NaN","10.5","11","9","100"],["2026-10-26","10","10.5","11","9","-1"]])
def test_daily_invalid_rows_fail_without_partial_success(row):
    with pytest.raises(ProviderError): parse_tencent_daily(daily_fixture([row]),"000001",today=date(2026,10,27))


def test_index_history_repairs_rounding_but_skips_materially_invalid_source_bars():
    diagnostics=[]
    rows=parse_tencent_daily(daily_fixture([
        ['2026-10-20','2663.882','2559.931','2663.880','2557.240','100'],
        ['2026-10-21','8586.403','8710.291','8715.285','8715.285','100'],
    ],code='sh000001'), 'SH.000001', today=date(2026,10,27), allow_index=True, diagnostics=diagnostics)
    assert len(rows)==1 and rows[0]['high']=='2663.882'
    assert diagnostics==[
        {'date':'2026-10-20','action':'ROUNDING_CLAMP_HIGH'},
        {'date':'2026-10-21','action':'INVALID_SOURCE_ROW_SKIPPED'},
        {'action':'SOURCE_PAGE_COUNT','count':2},
    ]


def test_daily_rejects_invalid_json_or_adjustment():
    with pytest.raises(ProviderError) as exc: parse_tencent_daily(b"{}","600000",adjustment="bad")
    assert exc.value.code=="INVALID_ADJUSTMENT"
    with pytest.raises(ProviderError) as exc: parse_tencent_daily(b"not-json","600000")
    assert exc.value.code=="INVALID_RESPONSE"


def test_fixed_urls_requests_and_no_retry_on_http_error():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(503,request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider=TencentProvider(client)
        with pytest.raises(ProviderError): provider.quotes(["600000"])
        with pytest.raises(ProviderError): provider.daily("600000",count=120)
    assert len(requests)==2
    assert str(requests[0].url)==QUOTE_URL+"sh600000"
    assert str(requests[1].url).startswith(KLINE_URL) and requests[1].url.params["param"]=="sh600000,day,,,120,"


def test_daily_history_limit_matches_verified_tencent_capacity():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(503,request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider=TencentProvider(client)
        with pytest.raises(ProviderError): provider.daily("600000")
        assert requests[0].url.params["param"]=="sh600000,day,,,2000,"
        with pytest.raises(ProviderError) as exc: provider.daily("600000",count=2001)
        assert exc.value.code=="INVALID_REQUEST"


def test_full_history_pages_backwards_and_keeps_page_provenance():
    start = date(2010, 1, 1)
    first = [[(start + timedelta(days=i)).isoformat(), '10', '11', '12', '9', '100'] for i in range(2000)]
    older = [[(start - timedelta(days=1)).isoformat(), '9', '10', '11', '8', '50']]
    calls = []
    def get(url, params):
        calls.append(params['param'])
        return daily_fixture(first if len(calls) == 1 else older, code='sh000001')
    rows = download_tencent_history(get, 'SH.000001', allow_index=True)
    assert calls == ['sh000001,day,,,2000,', 'sh000001,day,,2009-12-31,2000,']
    assert len(rows) == 2001 and rows[0]['time'] == '2009-12-31'
    assert len({row['time'] for row in rows}) == len(rows)
    assert rows[0]['raw_hash'] != rows[-1]['raw_hash']


@pytest.mark.parametrize('adjustment', ['qfq', 'hfq'])
def test_adjusted_full_history_respects_actual_page_limit(adjustment):
    from backend.providers import download_tencent_history
    first = [[(date(2020, 1, 1)+timedelta(days=i)).isoformat(), '10', '11', '12', '9', '100'] for i in range(640)]
    older = [['2019-12-30','10','11','12','9','100'], ['2019-12-31','10','11','12','9','100']]
    calls = []
    def get(url, params):
        calls.append(params['param'])
        return json.dumps({'data':{'sz300502':{adjustment+'day':first if len(calls)==1 else older}}}).encode()
    result = download_tencent_history(get, 'SZ.300502', adjustment=adjustment)
    assert len(result) == 642
    assert result[0]['time'] == '2019-12-30'
    assert calls == [f'sz300502,day,,,640,{adjustment}', f'sz300502,day,,2019-12-31,640,{adjustment}']


def test_full_history_rejects_non_progressing_pages():
    first = [[(date(2010, 1, 1) + timedelta(days=i)).isoformat(), '10', '11', '12', '9', '100'] for i in range(2000)]
    with pytest.raises(ProviderError) as exc:
        download_tencent_history(lambda *_: daily_fixture(first, code='sh000001'), 'SH.000001', allow_index=True)
    assert exc.value.code == 'HISTORY_PAGINATION'


def test_http_timeout_is_provider_error_and_bad_input_never_requests():
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout",request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider=TencentProvider(client)
        with pytest.raises(ProviderError) as exc: provider.quotes(["600000"])
        assert exc.value.code=="UPSTREAM_UNAVAILABLE"
        with pytest.raises(ProviderError): provider.quotes(["https://example.com"])
    assert len(calls)==1
