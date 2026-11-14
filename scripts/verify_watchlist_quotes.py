"""在现有正式服务验证自选行情与算法监测分离；不修改监测配置。"""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/watchlist-quotes'
BASE = 'http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width': 1600, 'height': 1000}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.method, request.url)))
        watches = page.request.get(BASE + '/api/v1/watchlists').json()['data']
        flags = {item['id']: item['monitor_enabled'] for item in watches}
        assert watches, '正式库需要至少一只自选股以验证行情'
        page.goto(BASE + '/#/watch', wait_until='networkidle')
        expect(page.locator('.watchlist-table tbody tr')).to_have_count(len(watches))
        assert any('/market/intraday?' in url for _, url in requests), '首屏没有立即读取分时'
        page.wait_for_timeout(1200)
        headers = page.locator('.watchlist-table th[data-column]').evaluate_all("els=>els.map(el=>el.dataset.column)")
        assert headers == ['name','code','price','change_pct','change','amount','volume','turnover_rate','volume_ratio','amplitude'], headers
        watch_text = page.locator('.watchlist-page').inner_text()
        for text in ['监测中', '已暂停', '监测设置', '管理监测规则', '暂无信号', '策略信号']:
            assert text not in watch_text, text
        quote_rows = page.locator('.watchlist-table tbody tr').all_text_contents()
        for item in watches:
            assert any(item['security']['code'] in row for row in quote_rows)
        paused = [item for item in watches if not item['monitor_enabled']]
        for item in paused:
            row = page.locator('.watchlist-table tbody tr').filter(has_text=item['security']['code'])
            if item['security'].get('quote', {}).get('price') is not None:
                assert row.locator('.quote-price').inner_text() != '—'
        if len(watches) > 1:
            page.locator('.watch-stock').nth(1).click()
            expect(page.locator('.watch-detail h2')).to_have_text(watches[1]['security']['name'])
            page.locator('.watch-stock').first.click()
            expect(page.locator('.watch-detail h2')).to_have_text(watches[0]['security']['name'])
        page.wait_for_timeout(11000)
        cache_reads = [url for method, url in requests if method == 'GET' and url.endswith('/api/v1/securities')]
        assert len(cache_reads) >= 2, '自选页没有持续检查报价缓存'
        page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '移动页面溢出'
        page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        flags_after = {item['id']: item['monitor_enabled'] for item in page.request.get(BASE + '/api/v1/watchlists').json()['data']}
        assert flags_after == flags, '验收不应变更算法监测配置'
        monitor_writes = [url for method, url in requests if method != 'GET' and any(path in url for path in ['/monitors', '/automation', '/watchlists'])]
        assert not monitor_writes, monitor_writes
        assert not errors, errors
        result = dict(watch_count=len(watches), paused_algorithm_rows_with_quotes=len(paused),
                      initial_intraday_request=True, quote_cache_reads=len(cache_reads),
                      removed_monitor_and_signal_placeholders=True, selection_linkage=True,
                      mobile_no_page_overflow=True, monitor_flags_unchanged=True,
                      browser_errors=errors, monitor_writes=monitor_writes)
        (OUT / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == '__main__':
    main()
