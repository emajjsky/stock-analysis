"""有界公开榜单协议测试；不访问外网。"""
import httpx
import pytest

from backend.market_rankings import RANKING_URL, SinaRankingProvider
from backend.providers import ProviderError


def sample(index, metric='changepercent', asc=0, prefix='sz', code=None):
    value = index if asc else 1000-index
    return dict(symbol=prefix+(code or f'000{index:03}'), code=code or f'000{index:03}',
                name='示例证券', trade='12.30', changepercent=value if metric == 'changepercent' else '-1.2',
                amount=value if metric == 'amount' else '472972366', volume=15125599, ticktime='15:35:45')


def provider(handler):
    return SinaRankingProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def test_three_rankings_fixed_https_parameters_units_and_unknown_source_date():
    requests=[]
    def handler(request):
        requests.append(request)
        q=request.url.params
        return httpx.Response(200, json=[sample(i, q['sort'], int(q['asc'])) for i in range(100)])
    api=provider(handler)
    result=api.rankings()
    assert set(result)=={'gainers','losers','amount'}
    assert all(len(rows)==100 for rows in result.values())
    assert all(str(r.url).startswith(RANKING_URL+'?') and r.url.params['node']=='hs_a' for r in requests)
    assert [(r.url.params['sort'],r.url.params['asc']) for r in requests]==[
        ('changepercent','0'),('changepercent','1'),('amount','0')]
    row=result['gainers'][0]
    assert row['id']=='LIVE.SZ.000000' and row['exchange']=='SZSE' and row['rank']==1
    quote=row['quote']
    assert quote['volume']==15125599 and quote['volume_unit']=='SHARES'
    assert quote['amount']=='472972366' and quote['amount_unit']=='CNY'
    assert quote['source_time'] is None and quote['as_of'] is None
    assert quote['source_time_raw']=='15:35:45' and quote['fetched_at'].endswith('Z')
    assert quote['mode']=='LIVE' and quote['is_realtime'] is False


def test_beijing_filter_pages_to_full_100_and_supports_302():
    requests=[]
    def handler(request):
        page=int(request.url.params['page']);requests.append(page)
        if page==1:
            rows=[sample(i) for i in range(100)]
            rows[0]=sample(0,prefix='bj',code='920000')
            rows[1]=sample(1,code='302132')
        else: rows=[sample(i) for i in range(100,200)]
        return httpx.Response(200,json=rows)
    rows=provider(handler).ranking('gainers')
    assert requests==[1,2] and len(rows)==100
    assert rows[0]['id']=='LIVE.SZ.302132' and rows[-1]['rank']==100
    assert all(not row['id'].startswith('LIVE.BJ') for row in rows)


@pytest.mark.parametrize('price',[None,'-','0'])
def test_unknown_price_never_fabricated_and_missing_units_remain_unknown(price):
    rows=[sample(i) for i in range(100)]
    rows[0].update(trade=price,volume=None,amount=None)
    quote=provider(lambda _:httpx.Response(200,json=rows)).ranking('gainers')[0]['quote']
    assert quote['price'] is None and quote['volume'] is None and quote['amount'] is None
    assert quote['volume_unit']=='UNKNOWN' and quote['amount_unit']=='UNKNOWN'


@pytest.mark.parametrize('changes',[
    {'code':'600519'}, {'symbol':'https://evil/000001'}, {'name':''}, {'trade':'NaN'},
    {'trade':'-1'}, {'volume':-1}, {'volume':'1.2'}, {'amount':'-1'},
    {'changepercent':True}, {'ticktime':'2026-10-29T15:00:00'},
    {'volume':{}}, {'amount':'Infinity'},
])
def test_invalid_identity_or_numbers_fail_without_partial_result(changes):
    rows=[sample(i) for i in range(100)];rows[1].update(changes)
    with pytest.raises(ProviderError) as exc:
        provider(lambda _:httpx.Response(200,json=rows)).ranking('gainers')
    assert exc.value.code=='RANKING_INVALID'


@pytest.mark.parametrize('payload',[None,{},[],[None],[sample(0)]*101])
def test_invalid_response_structure(payload):
    with pytest.raises(ProviderError):
        provider(lambda _:httpx.Response(200,json=payload)).ranking('amount')


def test_out_of_order_or_unknown_sort_fails():
    rows=[sample(i) for i in range(100)];rows[1]['changepercent']=2000
    with pytest.raises(ProviderError):
        provider(lambda _:httpx.Response(200,json=rows)).ranking('gainers')
    with pytest.raises(ProviderError) as exc:
        provider(lambda _:pytest.fail('must not request')).ranking('unknown')
    assert exc.value.code=='INVALID_REQUEST'


def test_duplicate_pages_not_counted_and_no_more_than_five_requests():
    calls=[]
    def handler(request):
        calls.append(request)
        rows=[sample(i) for i in range(100)]
        for row in rows:row['changepercent']='1'
        rows[0]['symbol']='bj920000';rows[0]['code']='920000'
        return httpx.Response(200,json=rows)
    with pytest.raises(ProviderError) as exc:provider(handler).ranking('gainers')
    assert exc.value.code=='RANKING_INCOMPLETE' and len(calls)==5


def test_transport_and_http_errors_are_safe():
    with pytest.raises(ProviderError) as exc:
        provider(lambda _:httpx.Response(503)).rankings()
    assert exc.value.code=='RANKING_UNAVAILABLE'
    def fail(request):raise httpx.ReadTimeout('private transport info',request=request)
    with pytest.raises(ProviderError) as exc:provider(fail).ranking('losers')
    assert 'private' not in exc.value.message


def test_caller_owned_client_remains_open_and_timeout_is_bounded():
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(503)))
    SinaRankingProvider(client).close()
    assert not client.is_closed
    client.close()
    for timeout in [0,-1,31]:
        with pytest.raises(ProviderError):SinaRankingProvider(timeout=timeout)
