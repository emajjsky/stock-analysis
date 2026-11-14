"""仅在独立浏览器拦截响应，验证行情不等待研究资料、首屏等待态和自动补齐。"""
from copy import deepcopy
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stock-detail'
BASE = 'http://127.0.0.1:8765'
KEY = 'LIVE.SZ.300502'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport={'width': 1600, 'height': 1000}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        security = page.request.get(f'{BASE}/api/v1/securities/{KEY}').json()
        intraday = page.request.get(f'{BASE}/api/v1/market/intraday?security_id={KEY}').json()
        profile = page.request.get(f'{BASE}/api/v1/securities/{KEY}/profile').json()
        assert intraday['data']['points'] and profile['data']['business']
        held_profiles = []
        mode = {'profile': 'hold', 'intraday': 0}
        pending = deepcopy(profile)
        pending['data'].update(business=None, facts=[], financials=[], evidence=[])
        pending['data']['research'].update(sections=[], auto_refresh={'enabled': True, 'pending': True})
        completed = deepcopy(profile)
        completed['data']['research']['auto_refresh'] = {'enabled': True, 'pending': False}

        def on_profile(route):
            if mode['profile'] == 'hold':
                held_profiles.append(route)
            else:
                route.fulfill(json=completed)

        def on_intraday(route):
            mode['intraday'] += 1
            payload = deepcopy(intraday)
            if mode['intraday'] == 1:
                payload['data']['points'] = []
            route.fulfill(json=payload)

        page.route(f'**/api/v1/securities/{KEY}/activate', lambda route: route.fulfill(json=security))
        page.route(f'**/api/v1/securities/{KEY}/profile', on_profile)
        page.route('**/api/v1/market/intraday?*', on_intraday)
        page.goto(f'{BASE}/#/stock/{KEY}', wait_until='domcontentloaded')
        expect(page.locator('.stock-chart-loading')).to_be_visible(timeout=10000)
        expect(page.locator('.stock-quote-primary strong')).to_have_text(security['data']['quote']['price'])
        expect(page.get_by_text('暂无分时数据', exact=True)).to_have_count(0)
        page.screenshot(path=str(OUT / '03-stock-loading.png'))
        expect(page.locator('[aria-label="分时与成交量图"] canvas').first).to_be_visible(timeout=8000)
        assert held_profiles, '未模拟慢公司资料请求'
        # 此刻公司资料仍未返回，行情图必须已经展示。
        assert mode['profile'] == 'hold'
        for route in held_profiles:
            route.fulfill(json=pending)
        mode['profile'] = 'complete'
        expect(page.get_by_text('正在获取公司概况，返回后自动显示…', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='自动更新中…')).to_be_disabled()
        expect(page.get_by_text(profile['data']['business'], exact=True)).to_be_visible(timeout=6000)
        expect(page.get_by_role('button', name='刷新资料', exact=True)).to_be_enabled()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT / '04-stock-intraday.png'), full_page=True)
        assert not errors, errors
        browser.close()
    result = dict(chart_before_slow_profile=True, initial_empty_is_loading=True,
                  research_pending_then_completed=True, errors=errors, data='浏览器响应拦截，不写正式库')
    (OUT / 'loading-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
