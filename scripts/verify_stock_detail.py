"""Verify the individual-stock layout against the existing local service."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stock-detail'
BASE = 'http://127.0.0.1:8765'
SECURITY = 'LIVE.SZ.300502'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'errors': [], 'viewports': [], 'api': {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport={'width': 1920, 'height': 1080}, locale='zh-CN')
        page.on('pageerror', lambda error: result['errors'].append(str(error)))
        response = page.request.get(f'{BASE}/api/v1/securities/{SECURITY}')
        assert response.status == 200
        security = response.json()['data']
        quote = security['quote']
        assert quote['order_book'] and len(quote['order_book']['bids']) == 5 and len(quote['order_book']['asks']) == 5
        assert all(quote.get(key) is not None for key in ('turnover_rate', 'amplitude', 'volume_ratio', 'total_market_cap'))
        result['api'] = {'name': security['name'], 'source_time': quote['source_time'], 'stale': quote['stale'],
                         'five_bids': len(quote['order_book']['bids']), 'five_asks': len(quote['order_book']['asks']),
                         'turnover_rate': quote['turnover_rate'], 'volume_ratio': quote['volume_ratio'],
                         'total_market_cap': quote['total_market_cap']}
        page.goto(f'{BASE}/#/stock/{SECURITY}')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='新易盛', exact=False)).to_be_visible(timeout=20000)
        expect(page.get_by_role('tab', name='买卖五档')).to_be_visible()
        expect(page.get_by_role('button',name='复权方式')).to_contain_text('除权 / 不复权')
        expect(page.get_by_text('算法信号')).to_have_count(0)
        expect(page.locator('.stock-quote-primary')).to_have_count(1)
        expect(page.locator('.stock-header-quote')).to_have_count(0)
        expect(page.locator('.stock-quote-primary small')).to_have_count(0)
        expect(page.locator('.book-current')).to_have_count(0)
        expect(page.locator('.stock-quote-metrics > div')).to_have_count(11)
        expect(page.locator('.book-row')).to_have_count(10)
        page.get_by_role('button', name='日 K').click()
        page.get_by_role('button', name='复权方式').click()
        for adjustment in ('除权 / 不复权', '前复权', '后复权'):
            expect(page.get_by_role('option', name=adjustment, exact=False)).to_be_visible()
        page.keyboard.press('Escape')
        page.get_by_role('button', name='新闻与公告').click()
        expect(page.locator('.news-panel')).to_be_visible()
        page.locator('.news-panel').get_by_role('button', name='公司公告', exact=True).click()
        expect(page.locator('.news-tabs button').first).to_have_text('公司公告')
        for width, height in [(1920, 1080), (1366, 768), (1093, 700), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_timeout(250)
            page.evaluate('window.scrollTo(0, 0)')
            dims = page.evaluate('''() => {
              const grid = document.querySelector('.stock-chart-market-grid');
              const chart = grid.querySelector('.stock-chart-column').getBoundingClientRect();
              const sidebar = grid.querySelector('.stock-chart-sidebar').getBoundingClientRect();
              const book = grid.querySelector('.order-book').getBoundingClientRect();
              return {width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                chart: {x: chart.x, y: chart.y, width: chart.width, height: chart.height, bottom:chart.bottom},
                sidebar: {x: sidebar.x, y: sidebar.y, width: sidebar.width, height: sidebar.height, bottom:sidebar.bottom},
                book: {x: book.x, y: book.y, width: book.width, height:book.height, bottom:book.bottom},
                metricFont: getComputedStyle(document.querySelector('.stock-quote-metrics strong')).fontSize};
            }''')
            assert dims['scrollWidth'] <= width, dims
            if width > 1080:
                assert dims['sidebar']['x'] > dims['chart']['x'] and abs(dims['sidebar']['y'] - dims['chart']['y']) < 5, dims
                assert abs(dims['book']['bottom'] - dims['chart']['bottom']) < 2, dims
            else:
                assert dims['book']['y'] >= dims['chart']['y'] + 300, dims
            result['viewports'].append(dims)
            if width == 1920:
                page.screenshot(path=str(OUT / '01-stock-detail-desktop.png'), full_page=True)
            elif width == 390:
                page.screenshot(path=str(OUT / '02-stock-detail-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1600, 'height': 1000})
        page.get_by_role('button', name='分时', exact=True).click()
        page.get_by_role('button', name='公司资料', exact=True).click()
        expect(page.locator('[aria-label="分时与成交量图"] canvas').first).to_be_visible()
        expect(page.locator('.facts-grid small')).to_have_count(0)
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT / '05-stock-intraday-live.png'), full_page=True)
        assert not result['errors'], result['errors']
        browser.close()
    (OUT / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
