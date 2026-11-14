"""验证自选字体、代码分列、密度、万元口径及缓存刷新；不修改自选或算法配置。"""
from copy import deepcopy
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/watchlist-indicators'
BASE = 'http://127.0.0.1:8765'


def aligned_cards(page):
    return page.locator('.watchlist-layout').evaluate('''el => {
        const left=el.querySelector('.watchlist-table-panel').getBoundingClientRect();
        const right=el.querySelector('.watch-detail').getBoundingClientRect();
        const footer=el.querySelector('.watchlist-table-footer').getBoundingClientRect();
        return Math.abs(left.top-right.top)<1 && Math.abs(left.bottom-right.bottom)<1
            && Math.abs(footer.bottom-left.bottom)<=2;
    }''')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, calls, sizes = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width': 1600, 'height': 1000}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda req: calls.append((req.method, req.url)))
        watches = page.request.get(BASE+'/api/v1/watchlists').json()['data']
        flags = {w['id']: w['monitor_enabled'] for w in watches}
        page.goto(BASE+'/#/watch', wait_until='networkidle')
        expect(page.locator('.watchlist-table tbody tr')).to_have_count(len(watches))
        expect(page.locator('.watch-detail-chart canvas').first).to_be_visible(timeout=15000)
        expect(page.locator('.watchlist-title')).to_have_count(0)
        assert page.locator('.watchlist-table th[data-column]').evaluate_all("els=>els.map(el=>el.dataset.column)") == ['name','code','price','change_pct','change','amount','volume','turnover_rate','volume_ratio','amplitude']
        for forbidden in ['源延迟', '等待源更新', 'SELECTED', '未接入行业资料', 'QUOTE BOARD', '非持续实时订阅', '监测中', '已暂停']:
            assert forbidden not in page.locator('.watchlist-page').inner_text(), forbidden
        for row in page.locator('.watchlist-table tbody tr').all():
            code = row.locator('.watch-code').inner_text()
            security = next(w['security'] for w in watches if w['security']['code']==code)
            # 比较该轮源报价，后台动态变化时以合理数量级核验，避免逐股金额随行情更新导致误报。
            amount = row.locator('.watch-amount').inner_text().replace(',', '')
            if security.get('quote', {}).get('amount') is not None:
                expected = float(security['quote']['amount']) / 10000
                assert abs(float(amount)-expected) <= max(1, abs(expected)*0.03), (amount, expected)
        if len(watches)>1:
            target=watches[1]['security_id']
            page.locator('.watch-stock').nth(1).click()
            expect(page.locator('.watch-detail h2')).to_have_text(watches[1]['security']['name'])
            expect(page.locator('.watch-detail-chart canvas').first).to_be_visible(timeout=15000)
            assert any(method=='POST' and target+'/activate' in url for method,url in calls)
        page.wait_for_timeout(5500)
        assert sum('/api/v1/watchlists' in url and method=='GET' for method,url in calls)>=3
        typography = page.locator('.watchlist-page').evaluate('''el => {
            const size = s => parseFloat(getComputedStyle(el.querySelector(s)).fontSize);
            return {name:size('.watch-stock-name strong'), code:size('td.watch-code'),
                header:size('th'), amount:size('.watch-amount'), time:size('.watch-source-note > span'),
                metric:size('.watch-metric-grid dd'), group:size('.watchlist-groups button'),
                row:el.querySelector('tbody tr').getBoundingClientRect().height};
        }''')
        assert typography['row'] <= 44, typography
        assert all(typography[key] >= 15 for key in ['name','code','amount','time','metric','group']), typography
        assert typography['header'] >= 14, typography
        for width,height in [(1600,1000),(1366,900),(1920,1080),(1093,720),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(400)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            if width>=1366:
                assert page.locator('.watchlist-table-scroll').evaluate('el=>el.scrollWidth>=el.clientWidth'), width
                assert aligned_cards(page), ('card alignment', width)
            if width>760:
                assert page.locator('.watchlist-toolbar').evaluate('''el => {
                    const items=[el.querySelector('.watchlist-groups button'),el.querySelector('.watchlist-search'),
                        el.querySelector('.watch-session'),el.querySelector('.button')];
                    const centers=items.map(i=>{const r=i.getBoundingClientRect();return r.y+r.height/2;});
                    return Math.max(...centers)-Math.min(...centers)<2;
                }'''), ('toolbar single row',width)
            assert page.locator('.watch-metric-grid').evaluate('''el => [...el.querySelectorAll('div')].every(d => {
                const label=d.querySelector('dt').getBoundingClientRect(), value=d.querySelector('dd').getBoundingClientRect();
                return label.right<=value.left && value.right<=d.getBoundingClientRect().right+1;
            })'''), ('metric overlap', width)
            assert page.locator('.watchlist-table tbody tr').first.evaluate('''row => {
                const headers=[...row.closest('table').querySelectorAll('th')];
                return [...row.cells].every((cell,i) => Math.abs(cell.getBoundingClientRect().left-headers[i].getBoundingClientRect().left)<1
                    && getComputedStyle(cell).textAlign===getComputedStyle(headers[i]).textAlign);
            }'''), ('column alignment',width)
            page.screenshot(path=str(OUT/f'watch-{width}.png'),full_page=True)
            sizes.append(width)
        page.set_viewport_size({'width':1600,'height':1000})
        page.get_by_label('筛选自选股').fill('不存在的股票-布局检查')
        expect(page.locator('.watchlist-empty')).to_be_visible()
        assert aligned_cards(page), 'empty cards not aligned'
        page.screenshot(path=str(OUT/'watch-empty.png'),full_page=True)
        page.get_by_label('筛选自选股').fill('')
        expect(page.locator('.watch-detail-chart canvas').first).to_be_visible(timeout=15000)
        page.get_by_label('行情来源说明').click()
        expect(page.locator('.watch-source-note p')).to_be_visible()
        page.get_by_label('行情来源说明').click()
        # 在独立浏览器响应内模拟跨日分时，确保不会无提示地充当今天数据。
        payload=page.request.get(BASE+'/api/v1/market/intraday?security_id='+watches[0]['security_id']).json()
        old=deepcopy(payload)
        old['data']['trade_date']='2020-01-01'
        page.route('**/api/v1/market/intraday?*',lambda route:route.fulfill(json=old))
        page.locator('.watch-stock').first.click()
        expect(page.locator('.watch-chart-notice')).to_contain_text('2020-01-01')
        page.unroute('**/api/v1/market/intraday?*')
        # 读取失败保留原报价，且有短提示；不把异常静默隐藏。
        original_count=page.locator('.watchlist-table tbody tr').count()
        page.route('**/api/v1/watchlists', lambda route: route.fulfill(status=503,json={'error':{'code':'TEST_UNAVAILABLE','message_zh':'测试暂不可用'}}))
        expect(page.locator('.watch-update-error')).to_be_visible(timeout=9000)
        assert page.locator('.watchlist-table tbody tr').count()==original_count
        page.unroute('**/api/v1/watchlists')
        expect(page.locator('.watch-update-error')).to_have_count(0,timeout=9000)
        # 完整个股图仍采用原来的三层结构。
        page.locator('.watch-open-detail').click()
        expect(page.locator('.stock-chart-column canvas').first).to_be_visible(timeout=15000)
        assert page.locator('.stock-chart-column .secondary-heading').count()==1
        after=page.request.get(BASE+'/api/v1/watchlists').json()['data']
        assert flags=={w['id']:w['monitor_enabled'] for w in after}
        # 多股票仅在独立浏览器响应中模拟，不向正式自选库写入。
        fixture = []
        for i in range(30):
            item = deepcopy(watches[i % len(watches)])
            item['id'] = 'layout-fixture-'+str(i)
            fixture.append(item)
        dense = browser.new_page(viewport={'width':1600,'height':1000})
        dense.on('pageerror', lambda error: errors.append(str(error)))
        dense.route('**/api/v1/watchlists', lambda route: route.fulfill(json={'data':fixture}))
        dense.goto(BASE+'/#/watch',wait_until='networkidle')
        expect(dense.locator('.watchlist-table tbody tr')).to_have_count(30)
        expect(dense.locator('.watch-detail-chart canvas').first).to_be_visible(timeout=15000)
        assert aligned_cards(dense), 'dense cards not aligned'
        assert dense.locator('.watch-detail').evaluate('el=>el.getBoundingClientRect().height<750'), 'list enlarged the detail card'
        assert dense.locator('.watchlist-table-scroll').evaluate('el=>el.scrollHeight>el.clientHeight'), 'long list must scroll internally'
        density = dense.locator('.watchlist-table-scroll').evaluate('''el => {
            const header=el.querySelector('thead').getBoundingClientRect().height;
            const row=el.querySelector('tbody tr').getBoundingClientRect().height;
            return {row_height:row, visible_rows:Math.floor((el.clientHeight-header)/row),
                previous_visible_rows:Math.floor((el.clientHeight-header)/62)};
        }''')
        assert density['visible_rows'] > density['previous_visible_rows'], density
        dense.screenshot(path=str(OUT/'watch-many-1600.png'),full_page=True)
        dense.locator('.watchlist-table-scroll').evaluate('el=>el.scrollTop=100')
        dense.screenshot(path=str(OUT/'watch-many-scrolled.png'),full_page=True)
        dense.close()
        assert not errors, errors
        result=dict(watch_count=len(watches), tested_widths=sizes, amount_unit='万元',
                    no_redundant_labels=True, selection_activation=True, cache_poll_seconds=5,
                    stale_chart_date_visible=True, quote_failure_preserves_rows=True, full_stock_chart_preserved=True,
                    algorithm_flags_unchanged=True, toolbar_single_row=True, cards_aligned=True,
                    empty_cards_aligned=True, dense_cards_aligned=True,
                    typography=typography, density=density, page_errors=errors)
        (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        browser.close()


if __name__=='__main__':
    main()
