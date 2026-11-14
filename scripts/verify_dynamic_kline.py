"""复用正式8765验证动态K线；更新夹具仅拦截独立测试浏览器响应。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/dynamic-kline'
BASE = 'http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = dict(api=[], browser=[], errors=[])
    with httpx.Client(base_url=BASE, trust_env=False, timeout=15) as client:
        client.get('/api/v1/session').raise_for_status()
        def get(path):
            response = client.get('/api/v1' + path)
            response.raise_for_status()
            return response.json()
        status = get('/data/refresh')['data']
        results['refresh'] = status
        overview = get('/market/overview')['data']
        for symbol in [x['symbol'] for x in overview['indices']] + ['LIVE.SH.600519']:
            for timeframe in ('1d', '1w', '1mo'):
                path = (f'/market/bars?security_id={symbol}&' if symbol.startswith('LIVE.')
                        else f'/market/indices/{symbol}/bars?') + f'timeframe={timeframe}'
                chart = get(path)['data']
                assert chart['current_bar'], (symbol, timeframe, chart['bars'][-1:])
                assert chart['current_bar']['trade_date'] == '2026-11-03'
                assert all(len(values) == len(chart['bars']) for values in chart['indicators'].values())
                assert len({row['time'] for row in chart['bars']}) == len(chart['bars'])
                with sqlite3.connect(f'file:{ROOT / ".local/workstation.db"}?mode=ro', uri=True) as db:
                    kind, key = ('market_snapshot', symbol) if symbol.startswith('LIVE.') else ('index_quote', symbol)
                    quote = json.loads(db.execute('select payload from documents where kind=? and id=?', (kind, key)).fetchone()[0])
                matched = quote['source_time'] == chart['current_bar']['source_time']
                if matched:
                    assert chart['bars'][-1]['close'] == quote['price']
                    if timeframe == '1d':
                        assert all(chart['bars'][-1][field] == quote[field] for field in ('open', 'high', 'low', 'volume', 'amount'))
                results['api'].append(dict(symbol=symbol, timeframe=timeframe, count=len(chart['bars']),
                    last=chart['bars'][-1], current=chart['current_bar'], quote_verified=matched))
        fixture = get('/market/indices/sh000001/bars?timeframe=1d')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport=dict(width=1600, height=1000), locale='zh-CN')
        page.on('pageerror', lambda error: results['errors'].append(str(error)))
        page.goto(BASE)
        page.wait_for_load_state('networkidle')
        panel = page.locator('.index-panel')
        for name, filename in [('日 K', '01-live-daily.png'), ('周 K', '02-live-weekly.png'), ('月 K', '03-live-monthly.png')]:
            panel.get_by_role('button', name=name, exact=True).click()
            expect(panel.locator('.chart-legend .badge')).to_contain_text('当日动态')
            expect(panel.locator('.stock-chart canvas').first).to_be_visible()
            panel.scroll_into_view_if_needed()
            page.mouse.move(5, 5)
            expect(panel.locator('.chart-legend .badge')).to_contain_text('当日动态')
            assert '最新' in panel.locator('.chart-legend').first.inner_text()
            panel.screenshot(path=str(OUT / filename))
            results['browser'].append(dict(case=name, legend=panel.locator('.chart-legend').first.inner_text()))
        page.set_viewport_size(dict(width=1366, height=768))
        search = page.get_by_label('全局搜索股票')
        search.fill('600519')
        page.locator('.search-results button').first.click()
        page.get_by_role('button', name='日 K', exact=True).click()
        expect(page.locator('.chart-legend .badge')).to_contain_text('当日动态')
        page.locator('.chart-legend').first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / '04-live-stock-1366.png'))
        results['browser'].append(dict(case='个股日K1366', legend=page.locator('.chart-legend').first.inner_text()))

        # 以下是前端轮询回归夹具，不代表真实涨价，不写正式库。
        page2 = browser.new_page(viewport=dict(width=1600, height=1000), locale='zh-CN')
        page2.on('pageerror', lambda error: results['errors'].append(str(error)))
        counter = [0]
        update = [False]
        def route_chart(route):
            payload = deepcopy(fixture)
            if update[0]:
                payload['data']['bars'][-1].update(close='4000.01', high='4000.01')
            counter[0] += 1
            route.fulfill(json=payload)
        page2.route('**/api/v1/market/indices/sh000001/bars?timeframe=1d', route_chart)
        page2.goto(BASE)
        page2.wait_for_load_state('networkidle')
        page2.locator('.index-panel').get_by_role('button', name='日 K', exact=True).click()
        canvas = page2.locator('.stock-chart canvas').first.element_handle()
        # 悬停当前棒，再等页面自身10秒轮询；图例也必须同步更新。
        chart_rect = page2.locator('.stock-chart').bounding_box()
        # 根据真实图例定位当天棒，避免把前几天误当成最后一根。
        for offset in range(110, 25, -2):
            page2.mouse.move(chart_rect['x'] + chart_rect['width'] - offset, chart_rect['y'] + 120)
            if page2.locator('.chart-date').inner_text() == '2026-11-03':
                break
        assert page2.locator('.chart-date').inner_text() == '2026-11-03'
        update[0] = True
        expect(page2.locator('.chart-legend').first).to_contain_text('4000.01', timeout=18000)
        assert canvas.evaluate('(element) => element.isConnected')
        assert counter[0] >= 2
        results['browser'].append(dict(case='隔离夹具：页面轮询更新当前棒，保留canvas实例', responses=counter[0]))
        browser.close()

    db = sqlite3.connect(f'file:{ROOT / ".local/workstation.db"}?mode=ro', uri=True)
    before = json.loads((ROOT / '.runtime/dynamic-kline-before.json').read_text(encoding='utf-8'))
    kinds = ('index_quote', 'index_intraday', 'market_snapshot', 'terminal_recent', 'market_sync_run', 'terminal',
             'terminal_history', 'market_history', 'index_daily', 'stock_intraday', 'security', 'catalog')
    protected = db.execute('select kind,id,payload from documents where kind not in (' + ','.join('?' for _ in kinds) + ') order by kind,id', kinds).fetchall()
    protected_hash = hashlib.sha256(json.dumps(protected, ensure_ascii=False).encode()).hexdigest()
    assert protected_hash == before['protected_hash']
    after = {x[0]: len(json.loads(x[1])['bars']) for x in db.execute('select id,payload from documents where kind=?', ('index_daily',))}
    assert after == before['index_daily']
    assert db.execute('select count(*) from provider_bars').fetchone()[0] == before['provider_count']
    results['history_unchanged'] = dict(index_counts=after, provider_count=before['provider_count'], protected_hash=protected_hash)
    assert not results['errors'], results['errors']
    (OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(api_checks=len(results['api']), browser=results['browser'], errors=results['errors'], history_unchanged=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
