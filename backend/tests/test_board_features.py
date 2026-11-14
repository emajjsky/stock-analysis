"""扩展源身份、财报口径、期货单位与历史时点边界。"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.boards import BoardProvider
from backend.app import create_app
from backend.providers import CHINA_TZ


def test_news_html_unescape_and_external_links_rejected():
    items = [dict(code='1', date='2026-01-02 10:00:00', title='<em>农业</em> &amp; 新闻',
                  content='正文', url='https://evil.example.com/a', mediaName='媒体')]
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,
        text='cb(' + json.dumps(dict(code=0, result=dict(cmsArticleWebOld=items))) + ')'))))
    n = p.board_news('BK1000', '农业')['items'][0]
    assert n['title'] == '农业 & 新闻' and n['url'] is None
    assert datetime.fromisoformat(n['published_at']).hour == 2


def test_concept_dates_from_source_not_discovery_time():
    html = '<table><tr><td>2026-07-01</td><td><a href="/gn/detail/code/309268/">玻璃基板</a></td><td>新事件</td><td>--</td><td>66</td></tr></table>'
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,content=html.encode('gbk')))))
    row = p.concept_new()['rows'][0]
    assert row['id'] == 'THS.309268' and row['date'] == '2026-07-01'
    assert row['total'] == 66 and row['event'] == '新事件'


def test_financial_same_period_balance_and_sample_median():
    def response(request):
        if request.url.params['reportName'] == 'RPT_LICO_FN_CPD':
            data = [dict(SECURITY_CODE=c,SECURITY_NAME_ABBR=c,REPORTDATE='2026-09-30',WEIGHTAVG_ROE=v,
                         XSMLL=None,YSTZ=-5,SJLTZ=None) for c,v in [('600371',2),('600519',8)]]
        else:
            assert "(REPORT_DATE='2026-09-30')" in request.url.params['filter']
            data = [dict(SECURITY_CODE='600371',REPORT_DATE='2026-09-30',TOTAL_ASSETS=200,TOTAL_LIABILITIES=60)]
        return httpx.Response(200,json=dict(success=True,result=dict(data=data)))
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(response)))
    r = p.board_financial('BK1000',[{'code':c,'quote':{'amount':'100'}} for c in ['600371','600519']])
    assert Decimal(r['metrics']['roe']['value']) == 5
    assert r['metrics']['debt_ratio'] == {'value':'30.0','count':1}
    assert r['metrics']['margin']['value'] is None
    assert r['rows'][1].get('debt_ratio') is None


def test_future_open_interest_not_external_volume_and_no_main_contract():
    raw = dict(f12='AP701',f13=115,f14='苹果701',f2=6004,f5=546544,f6=32623211360,
               f34=284959,f108=161014,f210=166682,f163=-5668)
    payload = {'rc':0,'data':{'total':2,'diff':[raw,{**raw,'f12':'APM'}]}}
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))))
    r = p.futures()
    assert len(r['rows']) == 1 and r['volume_unit'] == 'CONTRACTS'
    f = r['rows'][0]
    assert f['open_interest'] == '161014' and f['volume'] == '546544'
    assert Decimal(f['open_interest']) - Decimal(f['previous_interest']) == Decimal(f['interest_change'])


def test_convertible_bonds_join_issue_underlying_quotes_without_inventing_conversion_terms():
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    today = now.astimezone(CHINA_TZ).date()
    expiry = (today + timedelta(days=365)).isoformat() + ' 00:00:00'
    recent = int(now.timestamp()) - 60
    bonds = [
        dict(f12='123456', f13=0, f14='甲转债', f2=121.5, f3=1.2, f6=1000000, f124=recent),
        dict(f12='113456', f13=1, f14='乙转债', f2=98.2, f3=-0.3, f6=500000, f124=recent),
    ]
    terms = [
        dict(SECURITY_CODE='123456', SECURITY_NAME_ABBR='甲转债', CONVERT_STOCK_CODE='600000',
             SECURITY_SHORT_NAME='甲股份', LISTING_DATE='2026-01-01 00:00:00', DELIST_DATE=None,
             INITIAL_TRANSFER_PRICE=10, TRANSFER_START_DATE=expiry, TRANSFER_END_DATE=expiry,
             ACTUAL_ISSUE_SCALE=5),
        dict(SECURITY_CODE='113456', SECURITY_NAME_ABBR='乙转债', CONVERT_STOCK_CODE='000001',
             SECURITY_SHORT_NAME='乙股份', LISTING_DATE='2026-01-01 00:00:00', DELIST_DATE=None,
             INITIAL_TRANSFER_PRICE=20, TRANSFER_START_DATE='2026-01-01 00:00:00',
             TRANSFER_END_DATE=expiry, ACTUAL_ISSUE_SCALE=8),
    ]
    stocks = [
        dict(f12='600000', f13=1, f14='甲股份', f2=12, f3=-0.8, f124=recent),
        dict(f12='000001', f13=0, f14='乙股份', f2=8, f3=None, f124=recent),
    ]

    def response(request):
        if request.url.host == 'push2delay.eastmoney.com' and request.url.path.endswith('/clist/get'):
            return httpx.Response(200, json=dict(rc=0, data=dict(total=2, diff=bonds)))
        if request.url.host == 'datacenter-web.eastmoney.com':
            return httpx.Response(200, json=dict(success=True, result=dict(data=terms)))
        if request.url.host == 'push2delay.eastmoney.com' and request.url.path.endswith('/ulist.np/get'):
            return httpx.Response(200, json=dict(rc=0, data=dict(total=2, diff=stocks)))
        raise AssertionError(request.url)

    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(response)))
    result = p.convertible_bonds()
    p.close()
    assert result['total'] == 2 and result['loaded'] == 2
    first, second = result['rows']
    assert first['stock_code'] == '600000' and first['conversion_state'] == 'BEFORE'
    assert Decimal(first['change_spread']) == Decimal('2.0')
    assert first['initial_conversion_price'] == '10' and 'conversion_value' not in first
    assert second['stock_code'] == '000001' and second['conversion_state'] == 'ACTIVE'
    assert second['stock_change_pct'] is None and second['change_spread'] is None
    assert '相关性' in result['relation_note']


def test_futures_chart_volume_is_contracts_not_stock_shares():
    payload = dict(rc=0,data=dict(code='lh2701',market=114,name='生猪',klines=['2026-01-02,10,11,12,9,123,123456,3,1.25,1,4']))
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))))
    assert p.chart('lh2701','daily',market=114)['bars'][0]['volume'] == 123


def test_future_night_session_next_trade_date_is_allowed_but_not_for_equities():
    day = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    payload = dict(rc=0,data=dict(code='SA701',market=115,name='纯碱',klines=[day+',10,11,12,9,123,123456,3,1.25,1,4']))
    p = BoardProvider(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))))
    assert p.chart('SA701','daily',market=115)['bars'][0]['time'] == day
    payload['data'].update(code='BK1000',market=90)
    with pytest.raises(ValueError,match='dates'):
        p.chart('BK1000','daily')


def test_rotation_history_never_copies_today_funds_into_past(tmp_path):
    app = create_app(tmp_path/'history.db',network_enabled=False)
    boards=app.state.boards
    listing=dict(id='list:industry',fetched_at=datetime.now(timezone.utc).isoformat(),rows=[
        dict(id='EM.BK1000',code='BK1000',name='行业A',kind='industry',net_inflow='999999',amount='999999',change_pct='9')])
    with app.state.store.lock, app.state.store.db:
        app.state.store.put('board_cache',listing)
    class Provider:
        def chart(self,code,period,limit):
            return dict(bars=[dict(time='2026-01-02',close='100',change_pct='-3',amount='123')])
        def close(self): pass
    boards.factory=Provider
    r=boards.historical_rotation('industry')
    row=r['days'][0]['rows'][0]
    assert row['amount']=='123' and row['change_pct']=='-3' and 'net_inflow' not in row
    boards.stop();app.state.store.db.close()


def test_extended_routes_obey_offline_setting_and_reject_unknown_future(tmp_path):
    app=create_app(tmp_path/'extended-api.db',network_enabled=False)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin']='http://127.0.0.1:8765'
        for suffix in ['boards/concepts/latest','boards/benchmark','futures','bonds/convertible','etfs','etfs/holdings']:
            r=client.get('/api/v1/market/'+suffix)
            assert r.status_code==200 and r.json()['data']['status']=='EMPTY'
            assert not r.json()['data']['enabled']
        assert client.get('/api/v1/market/futures/115.AP999/chart').status_code==422
        assert client.post('/api/v1/market/boards/refresh?section=bond',json={}).status_code == 200
        assert client.get('/api/v1/market/boards/rotation/history?kind=bad').status_code==422
        assert client.post('/api/v1/market/boards/refresh?section=bad',json={}).status_code==422
        assert not app.state.boards.pending
    app.state.store.db.close()


def test_etf_portfolio_only_latest_report_and_six_digit_stock_identity():
    content = "<h4>测试ETF 截止至：<font>2026-09-30</font></h4><table><tbody>"
    content += "<tr><td>1</td><td>600519</td><td>贵州茅台</td><td></td><td></td><td></td><td>3.09%</td><td>1</td><td>2</td></tr>"
    content += "<tr><td>2</td><td>00700</td><td>港股</td><td></td><td></td><td></td><td>2%</td><td>1</td><td>2</td></tr></tbody></table>"
    content += "<h4>旧报告 截止至：2026-06-30</h4><tbody><tr>旧报告不合并</tr></tbody>"
    def response(req):
        assert req.headers['Referer'] == 'https://fundf10.eastmoney.com/'
        assert req.url.params['code'] == '510300'
        return httpx.Response(200,text='var apidata={content:'+json.dumps(content)+',arryear:[2026]};')
    p=BoardProvider(httpx.Client(transport=httpx.MockTransport(response)))
    row=p.etf_portfolio('510300')
    assert row['report_date']=='2026-09-30'
    assert row['holdings']==[dict(code='600519',name='贵州茅台',weight='3.09')]
    with pytest.raises(ValueError,match='code'):p.etf_portfolio('../bad')


def test_etf_portfolio_partial_failure_preserves_previous_report():
    p=BoardProvider()
    def portfolio(code):
        if code=='510300':raise ValueError('upstream failed')
        return dict(code=code,report_date='2026-09-30',holdings=[dict(code='600519',name='贵州茅台',weight='3')])
    p.etf_portfolio=portfolio
    old=dict(code='510300',name='沪深300ETF',report_date='2026-06-30',holdings=[dict(code='600036',name='招商银行',weight='2')])
    result=p.etf_holdings([dict(code='510300',name='沪深300ETF',amount='100'),dict(code='512480',name='半导体ETF',amount='50')],[old])
    assert result['failed']==1 and result['total']==2
    preserved=next(r for r in result['rows'] if r['code']=='510300')
    assert preserved['report_date']=='2026-06-30' and preserved['stale']
    p.close()
