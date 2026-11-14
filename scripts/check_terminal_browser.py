"""真实行情页面验收：正式服务搜索、指数/个股图、目录分页与多视口。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/terminal-increment'
BASE = 'http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, failures, cases = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1600, 'height': 900}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda r: failures.append({'url': r.url, 'status': r.status})
                if '/api/' in r.url and r.status >= 400 else None)
        page.goto(BASE)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='市场行情', exact=True)).to_be_visible()
        expect(page.locator('.index-tile')).to_have_count(8)
        expect(page.locator('[aria-label="分时与成交量图"] canvas').first).to_be_visible(timeout=45000)
        expect(page.locator('.index-tile').first.locator('strong')).not_to_have_text('—')
        expect(page.locator('.ranking-scroll tbody tr')).to_have_count(100, timeout=45000)
        page.screenshot(path=str(OUT / '01-home-1600.png'), full_page=True)
        cases.append('首页8个真实指数、分时、100条榜单')

        for tile in page.locator('.index-tile').all():
            index_name=tile.locator('span').first.inner_text()
            tile.click()
            expect(tile).to_have_attribute('aria-selected','true')
            expect(page.locator('.index-panel h2')).to_have_text(index_name)
            expect(page.locator('[aria-label="分时与成交量图"] canvas').first).to_be_visible(timeout=30000)
        page.locator('.index-tile').first.click()
        for tf in ('日 K','周 K','月 K'):
            page.locator('.index-panel').get_by_role('button',name=tf,exact=True).click()
            expect(page.locator('[aria-label^="历史K线图"] canvas').first).to_be_visible(timeout=30000)
        page.locator('.index-panel').get_by_role('button',name='分时',exact=True).click()
        cases.append('八指数标签逐个切换及指数日周月图')

        for name in ('跌幅榜 Top100', '成交额榜 Top100', '涨幅榜 Top100'):
            page.get_by_role('button', name=name, exact=True).click()
            expect(page.locator('.ranking-scroll tbody tr')).to_have_count(100)
        dimensions = page.locator('.ranking-scroll').evaluate('e=>({client:e.clientHeight,scroll:e.scrollHeight})')
        assert dimensions['client'] <= 361 and dimensions['scroll'] > dimensions['client'], dimensions
        cases.append('三类Top100切换、内部滚动')

        for query in ('600519', '贵州茅台', 'guizhoumaotai', 'gzmt'):
            search = page.get_by_label('全局搜索股票')
            search.fill(query)
            expect(page.locator('.search-results button').first).to_contain_text('贵州茅台')
            search.press('Escape')
        cases.append('代码、中文、全拼、首字母四种搜索')

        search.fill('gzmt')
        search.press('Enter')
        expect(page).to_have_url(BASE + '/#/stock/LIVE.SH.600519')
        expect(page.locator('.stock-header h1')).to_contain_text('贵州茅台')
        expect(page.locator('[aria-label="分时与成交量图"] canvas').first).to_be_visible(timeout=60000)
        page.get_by_role('button', name='日 K', exact=True).click()
        expect(page.locator('[aria-label^="历史K线图"] canvas').first).to_be_visible(timeout=60000)
        for label in ('周 K', '月 K', '分时'):
            page.get_by_role('button', name=label, exact=True).click()
            if label != '分时':
                expect(page.locator('[aria-label^="历史K线图"] canvas').first).to_be_visible(timeout=30000)
        page.screenshot(path=str(OUT / '02-stock-intraday.png'), full_page=True)
        page.reload()
        page.wait_for_load_state('networkidle')
        expect(page.locator('.stock-header h1')).to_contain_text('贵州茅台')
        cases.append('回车打开个股、自动分时/日周月切换、刷新保持')

        page.locator('nav button').filter(has_text='市场').click()
        expect(page.locator('tbody tr')).to_have_count(100)
        next_button = page.get_by_role('button', name='下一页', exact=True)
        if next_button.count():
            first_code = page.locator('tbody tr').first.inner_text()
            next_button.click()
            expect(page.locator('tbody tr').first).not_to_have_text(first_code)
        cases.append('全市场目录分页读取')

        for width, height in ((1366,768),(1093,614),(390,760)):
            page.set_viewport_size({'width':width,'height':height})
            page.goto(BASE)
            page.wait_for_load_state('networkidle')
            expect(page.locator('.index-tile')).to_have_count(8)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), f'{width} 首页横向溢出'
            if width <= 760:
                page.get_by_role('button', name='展开导航', exact=True).click()
            settings = page.locator('.sidebar-footer').get_by_role('button',name='数据与设置',exact=True)
            settings.click()
            expect(page.get_by_role('heading', name='基础库与自动更新', exact=True)).to_be_visible()
            expect(page.locator('.catalog-count')).to_contain_text('5,222')
            expect(page.get_by_label('行情自动更新间隔秒数')).to_have_value('60')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), f'{width} 设置页横向溢出'
            page.screenshot(path=str(OUT / f'03-settings-{width}.png'), full_page=True)
            cases.append(f'{width}x{height}首页/设置可用，无整页横向溢出')
        browser.close()
    assert not errors, errors
    assert not failures, failures
    result=dict(checked_at=datetime.now(timezone.utc).isoformat(),base=BASE,cases=cases,
                page_errors=errors,api_errors=failures,account_or_order_actions=False,
                changes='仅激活已搜索证券并按已授权流程加载行情；未修改自选、监测、账户或订单')
    (OUT/'browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
