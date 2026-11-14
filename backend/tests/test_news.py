"""资讯协议、缓存隔离与调度测试，禁止访问外网。"""
from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.news_data import NewsProvider, safe_article_url
from backend.providers import ProviderError


def flash(rows=None):
    row = dict(id=123, rich_text='【测试标题】<b>公告内容</b><script>bad()</script>', create_time='2026-11-03 14:00:00',
               ext=json.dumps(dict(stocks=[dict(symbol='sh600519', key='贵州茅台'), dict(symbol='hk00700', key='港股')],
                                   docurl='https://finance.sina.com.cn/7x24/test.shtml')))
    return dict(result=dict(status=dict(code=0), data=dict(feed=dict(list=[row] if rows is None else rows))))


def announcement():
    return dict(data=dict(list=[dict(art_code='AN123456', title='贵州茅台:测试公告', notice_date='2026-11-03 00:00:00',
        codes=[dict(stock_code='600519', market_code='1', short_name='贵州茅台')])]))


def provider(payload):
    return NewsProvider(httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))))


def test_real_protocol_normalizes_safe_plain_text_time_stocks_and_source():
    p = provider(flash())
    rows = p.market()
    assert len(rows) == 1
    item = rows[0]
    assert item['title'] == '测试标题' and item['summary'] == '【测试标题】公告内容'
    assert item['published_at'] == '2026-11-03T06:00:00Z' and item['publication_precision'] == 'TIME'
    assert item['securities'] == [dict(id='LIVE.SH.600519', code='600519', name='贵州茅台')]
    assert item['source'] == '新浪财经' and len(item['raw_hash']) == 64
    p.client.close()


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://evil.com/a', 'https://finance.sina.com.cn.evil.com/a',
    'https://x:y@finance.sina.com.cn/a', 'http://finance.sina.com.cn/a', 'https://finance.sina.com.cn:wrong/a'])
def test_untrusted_source_links_are_never_published(url):
    assert safe_article_url(url) is None


def test_announcements_preserve_date_precision_and_verify_requested_identity():
    p = provider(announcement())
    rows = p.announcements(['LIVE.SH.600519'])
    assert rows[0]['publication_precision'] == 'DATE'
    assert rows[0]['published_at'] == '2026-11-02T16:00:00Z'
    assert rows[0]['url'] == 'https://data.eastmoney.com/notices/detail/600519/AN123456.html'
    assert p.announcements(['LIVE.SZ.000001']) == []
    p.client.close()


@pytest.mark.parametrize('payload', [{}, dict(result=dict(status=dict(code=1))), flash([])])
def test_invalid_news_is_not_a_successful_empty_refresh(payload):
    p = provider(payload)
    with pytest.raises(ProviderError):
        p.market()
    p.client.close()


def test_fixed_endpoints_request_limits_and_proxy_independence(monkeypatch):
    kwargs = {}
    class Client:
        def __init__(self, **options): kwargs.update(options)
        def close(self): pass
    monkeypatch.setattr('backend.news_data.httpx.Client', Client)
    p = NewsProvider()
    assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
    assert kwargs['timeout'] == 10
    p.close()


def test_requests_use_each_sources_referer_and_fixed_bounded_endpoints():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=flash() if request.url.host == 'zhibo.sina.com.cn' else announcement())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = NewsProvider(client)
    p.market()
    p.announcements(['LIVE.SH.600519', 'LIVE.SZ.000001'])
    assert seen[0].headers['referer'] == 'https://finance.sina.com.cn/'
    assert seen[0].url.params['page_size'] == '100'
    assert seen[1].headers['referer'] == 'https://data.eastmoney.com/'
    assert seen[1].url.params['stock_list'] == '000001,600519'
    assert seen[1].url.params['page_size'] == '50'
    client.close()


class Source:
    calls = []
    broken = False
    def market(self):
        self.calls.append('market')
        if self.broken: raise ProviderError('FAILED', 'test')
        return [dict(id='news:1', title='测试快讯', published_at='2026-11-03T06:00:00Z',
            securities=[dict(id='LIVE.SH.600519', code='600519', name='贵州茅台')])]
    def announcements(self, ids=None):
        self.calls.append(ids or 'all')
        if self.broken: raise ProviderError('FAILED', 'test')
        return [dict(id='ann:1', title='测试公告', published_at='2026-11-02T16:00:00Z',
            securities=[dict(id='LIVE.SH.600519', code='600519', name='贵州茅台')])]
    def close(self): pass


@pytest.fixture
def prepared(tmp_path):
    app = create_app(tmp_path / 'news.db')
    Source.calls, Source.broken = [], False
    app.state.news.provider_factory = Source
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.get('/api/v1/session')
        client.headers['Origin'] = 'http://127.0.0.1:8765'
        yield app, client
    app.state.store.db.close()


def test_get_reads_only_and_refresh_is_bounded_cached_and_not_research(prepared):
    app, client = prepared
    news = app.state.news
    for _ in range(10):
        assert client.get('/api/v1/market/news').status_code == 200
    assert Source.calls == []
    news.refresh_once()
    assert Source.calls == ['market', 'all']
    chart = client.get('/api/v1/market/news').json()['data']
    assert chart['items'][0]['id'] == 'news:1' and chart['status'] == 'READY'
    for _ in range(10): news.refresh_once()
    assert Source.calls == ['market', 'all']
    for kind in ('research_current', 'research_snapshot', 'review', 'signal', 'watch', 'sim_account', 'order'):
        assert app.state.store.all(kind) == []
    assert app.state.store.bars('LIVE.SH.600519') == []
    assert client.get('/api/v1/market/news?tab=invalid').status_code == 422
    assert client.get('/api/v1/market/news?security_id=DEMO.SH.600519').status_code == 422
    assert client.get('/api/v1/market/news?security_id=https://evil.com').status_code == 422


def test_pause_explicit_retry_throttle_and_failure_keeps_cache(prepared):
    app, client = prepared
    news = app.state.news
    news.request()
    news.refresh_once()
    before = deepcopy(app.state.store.get('news_feed', 'market'))
    app.state.terminal.configure(dict(enabled=False))
    news.next_poll.clear()
    news.refresh_once()
    assert len(Source.calls) == 2
    Source.broken = True
    client.post('/api/v1/market/news/refresh', json={})
    news.refresh_once()
    assert len(Source.calls) == 4
    assert app.state.store.get('news_feed', 'market') == before
    feed = client.get('/api/v1/market/news').json()['data']
    assert feed['error'] and feed['items'] and not feed['enabled']
    for _ in range(5):
        client.post('/api/v1/market/news/refresh', json={})
        news.refresh_once()
    assert len(Source.calls) == 4


def test_watch_exact_identity_and_selected_announcements(prepared):
    app, client = prepared
    store, news = app.state.store, app.state.news
    store.put('watch', dict(id='w1', security_id='LIVE.SZ.000001'))
    news.request()
    news.refresh_once()
    assert ['LIVE.SZ.000001'] in Source.calls
    response = client.get('/api/v1/market/news?tab=watch').json()['data']
    assert response['items'] == []  # 不能把茅台内容当作平安银行相关新闻。
    client.get('/api/v1/market/news?tab=announcements&security_id=LIVE.SH.600519')
    news.refresh_once()
    response = client.get('/api/v1/market/news?tab=announcements&security_id=LIVE.SH.600519').json()['data']
    assert response['items'][0]['id'] == 'ann:1'
    assert Source.calls.count(['LIVE.SH.600519']) == 1
    assert response['scope'] == 'LIVE.SH.600519'


def test_cache_survives_offline_reopen(prepared, tmp_path):
    app, client = prepared
    client.get('/api/v1/market/news')
    app.state.news.refresh_once()
    second = create_app(tmp_path / 'news.db')
    try:
        assert second.state.news.feed('market')['items'][0]['id'] == 'news:1'
        assert second.state.news.thread is None
    finally:
        second.state.store.db.close()
