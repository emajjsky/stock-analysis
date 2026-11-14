"""验收个股紧凑五档、真实逐笔预览、筹码及自选组件兼容，不写业务数据。"""
from copy import deepcopy
import json
import re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8765'
KEY = 'LIVE.SZ.300502'
OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/stock-sidebar-density'


def facts(page, label):
    return page.locator('.quote-facts dl > div').filter(has=page.locator('dt', has_text=label)).locator('dd')


def dimensions(page, selector):
    return page.locator(selector).evaluate('''el=>{
        const overlaps=[...el.querySelectorAll('.quote-facts dl>div,.book-totals>div')].flatMap(row=>{
            const dt=row.querySelector('dt').getBoundingClientRect(),dd=row.querySelector('dd').getBoundingClientRect();
            return dt.right+2>dd.left ? [row.innerText] : [];
        });
        const sidebar=el.parentElement.getBoundingClientRect();
        const rect=el.getBoundingClientRect();
        const profile=el.querySelector('.chip-profile');
        const chipRows=[...el.querySelectorAll('.chip-row')];
        const firstChipRow=chipRows[0]?.getBoundingClientRect();
        const secondChipRow=chipRows[1]?.getBoundingClientRect();
        const lastChipRow=chipRows.at(-1)?.getBoundingClientRect();
        const chipTrackWidth=chipRows[0]?.querySelector('.chip-track').getBoundingClientRect().width;
        const priceLabels=chipRows.map(row=>row.querySelector('.chip-price').textContent).filter(Boolean).map(Number);
        return {height:el.clientHeight,scrollHeight:el.scrollHeight,width:el.clientWidth,
            horizontal:el.scrollWidth>el.clientWidth+1,overlaps,
            sidebarBottom:sidebar.bottom,panelBottom:rect.bottom,
            rowHeight:el.querySelector('.book-row')?.getBoundingClientRect().height,
            chipRowHeight:el.querySelector('.chip-row')?.getBoundingClientRect().height,
            chipRows:el.querySelectorAll('.chip-row').length,
            visibleChipBars:[...el.querySelectorAll('.chip-track i')].filter(bar=>bar.getBoundingClientRect().width>0).length,
            profileHeight:profile?.getBoundingClientRect().height,
            chipRowPitch:firstChipRow&&secondChipRow ? secondChipRow.top-firstChipRow.top : null,
            chipLayoutSpan:firstChipRow&&lastChipRow ? lastChipRow.bottom-firstChipRow.top : null,
            chipTrackWidth,priceLabels};
    }''')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results, errors = {'book':[], 'chip':[]}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width':1600, 'height':1080},locale='zh-CN')
        page.on('pageerror', lambda e:errors.append(str(e)))
        before = page.request.get(BASE+'/api/v1/watchlists').json()['data']
        security = page.request.get(BASE+'/api/v1/securities/'+KEY).json()
        trades = page.request.get(BASE+'/api/v1/market/trades?security_id='+KEY).json()
        page.route('**/api/v1/securities/'+KEY,lambda route:route.fulfill(json=security) if route.request.method=='GET' else route.continue_())
        # 固定这次正式服务真实返回的逐笔，避免轮询期间上游变化造成断言漂移。
        page.route('**/api/v1/market/trades?*',lambda route:route.fulfill(json=trades))
        page.goto(BASE+'/#/stock/'+KEY,wait_until='networkidle')
        expect(page.locator('.book-row')).to_have_count(10)
        expect(page.locator('.book-pressure')).to_be_visible()
        expect(page.locator('.quote-facts dd')).to_have_count(8)
        sidebar_labels = page.locator('.quote-facts dt').all_text_contents()
        assert set(sidebar_labels) == {'外盘','内盘','市净率','市盈TTM','市盈静','流通值','总股本','流通股'}
        top_labels = page.locator('.stock-quote-metrics span').all_text_contents()
        assert not set(sidebar_labels).intersection(top_labels)
        expect(page.get_by_role('heading',name='行情概览',exact=True)).to_have_count(0)
        expect(page.get_by_role('heading',name='成交与估值',exact=True)).to_have_count(1)
        book = security['data']['quote']['order_book']
        buy = sum(row['volume'] or 0 for row in book['bids'])
        sell = sum(row['volume'] or 0 for row in book['asks'])
        buy_text = f'{buy:.2f}手' if all(isinstance(row['volume'], (int,float)) for row in book['bids']) else '—'
        sell_text = f'{sell:.2f}手' if all(isinstance(row['volume'], (int,float)) for row in book['asks']) else '—'
        expect(page.locator('.book-totals dd').nth(0)).to_have_text(buy_text)
        expect(page.locator('.book-totals dd').nth(1)).to_have_text(sell_text)
        results['sidebar_distinct_from_header'] = sidebar_labels
        preview_count = min(5,len(trades['data']['trades']))
        expect(page.locator('.trade-preview .trade-row')).to_have_count(preview_count)
        expected = [t['time'] for t in reversed(trades['data']['trades'])][:5]
        assert page.locator('.trade-preview .trade-row time').all_text_contents() == expected
        for width,height in [(1920,1080),(1600,1000),(1366,768),(1093,700),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(150)
            d = dimensions(page,'.order-book')
            assert d['rowHeight'] == 28 and not d['overlaps'] and not d['horizontal'], d
            assert d['scrollHeight'] <= d['height'] + 2, d
            if width > 1080:
                assert abs(d['sidebarBottom']-d['panelBottom']) <= 2, d
            results['book'].append({'viewport':[width,height],**d})
            if width in [1920,1366,390]:
                page.locator('.stock-chart-sidebar').screenshot(path=str(OUT/f'book-{width}.png'))

        page.set_viewport_size({'width':1600,'height':1080})
        page.locator('.trade-preview').get_by_role('button',name='更多 ›',exact=True).click()
        expect(page.locator('.trade-tape:not(.trade-preview)')).to_be_visible()
        expect(page.locator('.trade-filter')).to_be_visible()
        expect(page.locator('.trade-summary > div')).to_have_count(2)
        expect(page.locator('.trade-row')).to_have_count(len(trades['data']['trades']))
        page.get_by_role('tab',name='买卖五档',exact=True).click()
        expect(page.locator('.trade-preview .trade-row')).to_have_count(preview_count)
        page.get_by_role('button',name='日 K',exact=True).click()
        page.get_by_role('tab',name='筹码分布',exact=True).click()
        expect(page.locator('.chip-profile')).to_be_visible(timeout=20000)
        expect(page.locator('.chip-panel .quote-facts')).to_be_visible()
        assert page.locator('.quote-facts dt').all_text_contents() == sidebar_labels
        expect(page.locator('.chip-source')).to_contain_text('不是原始持仓数据')
        expect(page.locator('.chip-unavailable-cost')).to_contain_text('未接入数据')
        assert page.locator('.chip-profile').evaluate('(el)=>el.clientHeight') == 300
        cost90 = page.locator('.chip-ranges > div').first.locator('strong').inner_text().split('–')
        cost90 = [float(value) for value in cost90]
        for width,height in [(1920,1080),(1600,1000),(1366,768),(1093,700),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(150)
            d = dimensions(page,'.chip-panel')
            assert d['chipRowHeight'] == 2 and d['chipRows'] == 140 and d['visibleChipBars'] > 0, d
            assert d['chipTrackWidth'] > 100, d
            assert d['profileHeight'] == 300 and d['chipRowPitch'] == 2, d
            assert d['chipLayoutSpan'] == 280, d
            assert min(d['priceLabels']) >= cost90[0] - 0.02 and max(d['priceLabels']) <= cost90[1] + 0.02, d
            assert not d['overlaps'] and not d['horizontal'], d
            assert d['scrollHeight'] <= d['height'] + 2, d
            results['chip'].append({'viewport':[width,height],**d})
            if width in [1920,1366,390]:
                page.locator('.stock-chart-sidebar').screenshot(path=str(OUT/f'chip-{width}.png'))

        # 600221 matches the user's screenshot's low-price distribution and float-share scale.
        page.goto('about:blank')
        page.goto(BASE+'/#/stock/LIVE.SH.600221',wait_until='networkidle')
        page.get_by_role('button',name='日 K',exact=True).click()
        page.get_by_role('tab',name='筹码分布',exact=True).click()
        expect(page.locator('.chip-profile')).to_be_visible(timeout=20000)
        expect(page.locator('.chip-heading span')).to_have_text(re.compile(r'\d{4}-\d{2}-\d{2}'))
        low90,high90=map(float,page.locator('.chip-ranges > div').first.locator('strong').inner_text().split('–'))
        profile_axis=page.locator('.chip-price').all_text_contents()
        profile_axis=[float(label) for label in profile_axis if label]
        assert len(profile_axis)>=8 and min(profile_axis)>=low90-0.02 and max(profile_axis)<=high90+0.02
        assert page.locator('.chip-track i').evaluate_all("bars=>bars.filter(bar=>parseFloat(bar.style.width)>0).length") >= 100
        results['reference_stock_600221']={'cost90':[low90,high90],'axisLabels':[min(profile_axis),max(profile_axis)],
            'visibleBars':page.locator('.chip-track i').evaluate_all("bars=>bars.filter(bar=>parseFloat(bar.style.width)>0).length")}
        page.locator('.stock-chart-sidebar').screenshot(path=str(OUT/'chip-600221.png'))

        page.set_viewport_size({'width':1600,'height':1000})
        page.locator('.app-sidebar').get_by_role('button',name='自选',exact=True).click()
        page.get_by_role('tab',name='五档',exact=True).click()
        expect(page.locator('.watch-detail .book-row')).to_have_count(10)
        expect(page.locator('.watch-detail .quote-facts')).to_have_count(0)
        expect(page.locator('.watch-detail .trade-preview')).to_have_count(0)
        results['watch_compact_unchanged'] = True

        # 浏览器响应替身：涨停无卖档和缺失数值不补零、不伪造委比。
        fixture = deepcopy(security)
        quote = fixture['data']['quote']
        for key in ['pb','pe_ttm','pe_static','pe_dynamic','total_market_cap','buy_volume','sell_volume','float_shares']:
            quote[key] = None
        quote['buy_volume'] = '1234500'
        quote['order_book']['asks'] = [{'level':i,'price':None,'volume':None} for i in range(1,6)]
        page.route('**/api/v1/securities/'+KEY,lambda route:route.fulfill(json=fixture) if route.request.method=='GET' else route.continue_())
        page.goto('about:blank')
        page.goto(BASE+'/#/stock/'+KEY,wait_until='networkidle')
        expect(page.locator('.book-pressure strong')).to_have_text('—')
        expect(page.locator('.book-row').first.locator('strong')).to_have_text('—')
        expect(facts(page,'市净率')).to_have_text('—')
        expect(facts(page,'外盘')).to_have_text('1.23万手')
        expect(facts(page,'内盘')).to_have_text('—')
        for index in [1,2,3]:
            expect(page.locator('.book-totals dd').nth(index)).to_have_text('—')
        page.get_by_role('button',name='日 K',exact=True).click()
        page.get_by_role('tab',name='筹码分布',exact=True).click()
        expect(page.locator('.chip-empty')).to_contain_text('行情源未提供有效流通股本')
        results['missing_and_lot_units'] = True

        # 逐笔源失效时仍保留真实报价和五档，显示错误，不生成假成交。
        page.unroute('**/api/v1/market/trades?*')
        page.route('**/api/v1/market/trades?*',lambda route:route.abort('failed'))
        page.reload(wait_until='networkidle')
        expect(page.locator('.trade-preview .trade-error')).to_be_visible()
        expect(page.locator('.trade-preview .trade-row')).to_have_count(0)
        expect(page.locator('.book-row')).to_have_count(10)
        results['trade_failure_visible'] = True
        after = page.request.get(BASE+'/api/v1/watchlists').json()['data']
        identity = lambda items:[(x['id'],x['security_id'],x['monitor_enabled']) for x in items]
        assert identity(before)==identity(after)
        assert not errors, errors
        results['business_records_unchanged'] = True
        results['page_errors'] = errors
        results['trade_source'] = trades['data']['source']
        browser.close()
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
