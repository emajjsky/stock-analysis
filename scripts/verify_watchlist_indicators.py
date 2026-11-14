"""自选指标、排序、列偏好和盘口交互验收；测试数据仅在浏览器响应中替换。"""
from copy import deepcopy
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8765'
OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/watchlist-indicators'
DEFAULT = ['name','code','price','change_pct','change','amount','volume','turnover_rate','volume_ratio','amplitude']


def columns(page):
    return page.locator('th[data-column]').evaluate_all('els=>els.map(el=>el.dataset.column)')


def codes(page):
    return page.locator('td[data-column=code]').all_text_contents()


def sort(page, key):
    page.locator('.watchlist-table-scroll').evaluate('el=>el.scrollLeft=0')
    page.locator(f'th[data-column={key}] button').click()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, writes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width':1600,'height':1000},locale='zh-CN')
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda req:writes.append((req.method,req.url)) if req.method not in ['GET','HEAD'] else None)
        envelope = page.request.get(BASE+'/api/v1/watchlists').json()
        live = envelope['data']
        before = [(w['id'],w['security_id'],w['monitor_enabled']) for w in live]
        page.goto(BASE+'/#/watch',wait_until='networkidle')
        expect(page.locator('.watch-detail canvas').first).to_be_visible(timeout=15000)
        assert columns(page)==DEFAULT
        # 核实实际行情换算，避免把上游手数当成股数再除一次。
        for item in live:
            row=page.locator('tbody tr').filter(has=page.locator('td[data-column=code]',has_text=item['security']['code']))
            quote=item['security']['quote']
            for key,divisor in [('volume',100),('amount',10000)]:
                actual=row.locator(f'td[data-column={key}]').inner_text().replace(',','')
                if quote.get(key) is not None:
                    assert abs(float(actual)-float(quote[key])/divisor)<=max(1,abs(float(actual))*.03)
        selected=page.locator('.watch-detail h2').inner_text()
        sort(page,'change_pct')
        values=[float(v.replace('%','').replace(',','')) for v in page.locator('td[data-column=change_pct]').all_text_contents() if v!='—']
        assert values==sorted(values,reverse=True)
        expect(page.locator('.watch-detail h2')).to_have_text(selected)
        page.wait_for_timeout(5600)
        values=[float(v.replace('%','').replace(',','')) for v in page.locator('td[data-column=change_pct]').all_text_contents() if v!='—']
        assert values==sorted(values,reverse=True), '刷新后排序丢失'
        page.screenshot(path=str(OUT/'sorted-live.png'),full_page=True)
        sort(page,'change_pct')
        sort(page,'change_pct')
        assert codes(page)==[w['security']['code'] for w in live]
        page.get_by_role('tab',name='五档',exact=True).click()
        expect(page.locator('.watch-detail .book-row')).to_have_count(10)
        page.screenshot(path=str(OUT/'book-live.png'),full_page=True)
        page.get_by_role('tab',name='分时',exact=True).click()
        expect(page.locator('.watch-detail canvas').first).to_be_visible(timeout=15000)

        # 完整列表模式与展示偏好持久化。
        page.get_by_label('收起右侧详情').click()
        expect(page.locator('.watch-detail')).to_be_hidden()
        assert page.locator('.watchlist-table-panel').evaluate('el=>el.clientWidth>1200')
        page.screenshot(path=str(OUT/'full-list-live.png'),full_page=True)
        page.reload(wait_until='networkidle')
        expect(page.locator('.watch-detail')).to_be_hidden()
        page.get_by_label('展开右侧详情').click()

        page.get_by_label('列设置',exact=True).click()
        expect(page.get_by_role('checkbox',name='股票名称',exact=True)).to_be_disabled()
        page.screenshot(path=str(OUT/'column-settings.png'),full_page=True)
        for label in ['买一价','卖一价','今开','最高','最低','昨收','市盈率','流通市值','报价时间']:
            page.get_by_role('checkbox',name=label,exact=False).check()
        assert len(columns(page))==19
        page.keyboard.press('Escape')
        expect(page.locator('.watch-column-options')).to_be_hidden()
        page.reload(wait_until='networkidle')
        assert len(columns(page))==19
        page.locator('.watchlist-table-scroll').evaluate('el=>{el.scrollLeft=el.scrollWidth;el.scrollTop=200;}')
        fixed=page.locator('.watchlist-table-scroll').evaluate('''el=>{
            const left=el.getBoundingClientRect().left;
            const name=el.querySelector('tbody .watch-name').getBoundingClientRect();
            const code=el.querySelector('tbody .watch-code').getBoundingClientRect();
            const header=el.querySelector('thead .watch-name').getBoundingClientRect();
            return Math.abs(name.left-left)<2 && Math.abs(name.right-code.left)<2 && Math.abs(header.top-el.getBoundingClientRect().top)<2;
        }''')
        assert fixed, '滚动时名称代码或表头未固定'
        page.screenshot(path=str(OUT/'optional-columns-scrolled.png'),full_page=True)
        page.get_by_label('列设置',exact=True).click()
        page.get_by_text('恢复默认',exact=True).click()
        assert columns(page)==DEFAULT
        page.locator('.watchlist-groups button').first.click()
        expect(page.locator('.watch-column-options')).to_be_hidden()

        # 浏览器专用固定样本，覆盖负数、平值、缺失与后续报价重排。
        fixture=deepcopy(live[:6])
        assert len(fixture)==6
        for item,amount in zip(fixture,['90000','1000000',None,'0','90000','-20000']):
            item['security']['quote']['amount']=amount
        fixture[2]['security']['quote']['volume']=None
        fixture[3]['security']['quote']['volume']=0
        fixture[2]['security']['quote']['order_book']=None
        test=browser.new_page(viewport={'width':1366,'height':900},locale='zh-CN')
        test.on('pageerror',lambda e:errors.append(str(e)))
        test.route('**/api/v1/watchlists',lambda route:route.fulfill(json={'data':fixture,'meta':envelope['meta']}))
        test.route('**/api/v1/securities',lambda route:route.fulfill(json={'data':[w['security'] for w in fixture],'meta':envelope['meta']}))
        test.goto(BASE+'/#/watch',wait_until='networkidle')
        sort(test,'amount')
        assert codes(test)==[fixture[i]['security']['code'] for i in [1,0,4,3,5,2]]
        sort(test,'amount')
        assert codes(test)==[fixture[i]['security']['code'] for i in [5,3,0,4,1,2]]
        # 选中股票在新报价重排时保持选中。
        test.locator('.watch-stock').nth(2).click()
        expected_name=test.locator('.watch-detail h2').inner_text()
        fixture[0]['security']['quote']['amount']='-30000'
        expect(test.locator('td[data-column=code]').first).to_have_text(fixture[0]['security']['code'],timeout=9000)
        expect(test.locator('.watch-detail h2')).to_have_text(expected_name)
        sort(test,'amount')
        assert codes(test)==[w['security']['code'] for w in fixture]
        assert test.locator('td[data-column=volume]').nth(2).inner_text()=='—'
        assert test.locator('td[data-column=volume]').nth(3).inner_text()=='0'
        test.close()

        # 每种宽度分别检查展开、收起、菜单，避免只在默认列数下通过。
        tested=[]
        for width,height in [(1920,1080),(1600,1000),(1366,900),(1093,720),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(250)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            page.get_by_label('列设置',exact=True).click()
            bounds=page.locator('.watch-column-options').bounding_box()
            assert bounds['x']>=0 and bounds['x']+bounds['width']<=width+1,(width,bounds)
            page.keyboard.press('Escape')
            page.screenshot(path=str(OUT/f'indicators-{width}.png'),full_page=True)
            page.get_by_label('收起右侧详情').click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            page.get_by_label('展开右侧详情').click()
            tested.append(width)
        after=page.request.get(BASE+'/api/v1/watchlists').json()['data']
        assert before==[(w['id'],w['security_id'],w['monitor_enabled']) for w in after]
        assert not any('/watchlists' in url or '/monitors' in url for _,url in writes),writes
        assert not errors,errors
        result=dict(default_indicators=10,selectable_columns=19,numeric_sort=True,missing_values_last=True,
                    sort_survives_refresh=True,selection_survives_reorder=True,fixed_name_code_and_headers=True,
                    preferences_persist=True,reset_columns=True,collapse_detail=True,book_rows=10,
                    correct_volume_lots=True,correct_amount_wan=True,tested_widths=tested,
                    watchlist_and_monitor_records_unchanged=True,page_errors=errors)
        (OUT/'interaction-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        browser.close()


if __name__=='__main__':
    main()
