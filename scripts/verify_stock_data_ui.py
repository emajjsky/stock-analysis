"""正式服务上的指标、双轴、复权、资料与盘口验收。"""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/evidence/stock-data-audit'
KEY = 'LIVE.SZ.300502'
BASE = 'http://127.0.0.1:8765'


def plot(page, label):
    chart=page.locator(f'[aria-label="{label}"]')
    canvas=max(chart.locator('canvas').all(),key=lambda c:c.evaluate('(e)=>e.clientWidth*e.clientHeight'))
    return canvas.screenshot()


def main():
    result={'errors':[],'main':[],'secondary':[],'intraday':[],'viewports':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page=browser.new_page(viewport={'width':1600,'height':1000},locale='zh-CN')
        page.on('pageerror',lambda e:result['errors'].append(str(e)))
        page.goto(BASE+'/#/stock/'+KEY)
        expect(page.get_by_role('combobox',name='分时副图')).to_be_visible(timeout=20000)
        expect(page.locator('.chart-legend').get_by_text('179.84',exact=True)).to_be_visible()
        png=plot(page,'分时与成交量图')
        image=Image.open(io.BytesIO(png)).convert('RGB')
        blue=gold=0
        for r,g,b in image.getdata():
            blue+=r<80 and 60<g<125 and 130<b<210
            gold+=140<r<220 and 90<g<180 and b<70
        assert blue>100 and gold>100, (blue,gold)
        result['real_price_and_average_pixels']={'price':blue,'average':gold}
        for value in ['VOL','MACD','RSI']:
            page.get_by_role('combobox',name='分时副图').select_option(value)
            page.wait_for_timeout(180)
            if value!='VOL':
                expect(page.locator('.chart-legend').last).not_to_contain_text('—')
            result['intraday'].append(value)
        page.get_by_role('combobox',name='分时副图').select_option('VOL')
        page.get_by_role('tab',name='估值与股本',exact=True).click()
        for value in ['16.59','15.95','25.37']:
            expect(page.locator('.book-facts')).to_contain_text(value)
        page.screenshot(path=str(OUT/'01-intraday-valuation.png'),full_page=True)
        page.get_by_role('tab',name='五档',exact=True).click()
        page.get_by_role('button',name='日 K',exact=True).click()
        main=page.get_by_role('combobox',name='主图指标',exact=True)
        expect(main).to_be_visible()
        for value in ['MA','BOLL','EXPMA','BBI','SAR']:
            main.select_option(value)
            page.wait_for_timeout(180)
            png=plot(page,'K线图，支持缩放、拖动、均线和技术指标')
            assert len(png)>10000
            result['main'].append({'indicator':value,'canvas_sha256':hashlib.sha256(png).hexdigest()})
        assert len({v['canvas_sha256'] for v in result['main']})==5
        main.select_option('BOLL')
        second=page.get_by_role('combobox',name='副图指标选择')
        for value in ['MACD','KDJ','RSI','OBV','W&R','MTM','VR','ARBR','DMI','BIAS','DMA','ASI','TRIX','DPO']:
            second.select_option(value)
            page.wait_for_timeout(120)
            for number in page.locator('.chart-legend').last.locator('strong').all():
                expect(number).not_to_have_text('—')
            result['secondary'].append(value)
        second.select_option('MACD')
        for value in ['前复权','后复权','不复权']:
            page.get_by_role('button',name=value,exact=True).click()
            expect(page.get_by_role('button',name=value,exact=True)).to_have_attribute('aria-pressed','true')
            expect(page.locator('.chart-legend').last).to_contain_text('2,590',timeout=15000)
            expect(main).to_be_visible()
        page.get_by_role('button',name='财务摘要',exact=True).click()
        expect(page.locator('.research-panel')).to_contain_text('92.97')
        expect(page.locator('.research-panel')).to_contain_text('79.74')
        page.get_by_role('button',name='财报与分红',exact=True).click()
        expect(page.locator('.corporate-actions')).not_to_have_count(0)
        expect(page.locator('.research-panel')).to_contain_text('2026-06-11')
        expect(page.locator('.research-panel')).to_contain_text('10转4股派10.00元')
        main.select_option('EXPMA')
        page.wait_for_timeout(180)
        # 事件标记确实绘制到canvas，非仅接口存在。紫色只用于财报/除权标记。
        png=plot(page,'K线图，支持缩放、拖动、均线和技术指标')
        event_pixels=sum(100<r<165 and 55<g<110 and 115<b<190 for r,g,b in Image.open(io.BytesIO(png)).convert('RGB').getdata())
        assert event_pixels>10,event_pixels
        result['event_marker_pixels']=event_pixels
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT/'02-kline-corporate-actions.png'),full_page=True)
        for width,height in [(1920,1080),(1600,900),(1366,768),(1093,614),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(200)
            for tab in ['五档','估值与股本']:
                page.get_by_role('tab',name=tab,exact=True).click()
                dims=page.evaluate('''() => {
                  const book=document.querySelector('.order-book'), chart=document.querySelector('.stock-chart-column');
                  const b=book.getBoundingClientRect(),c=chart.getBoundingClientRect();
                  return {width:innerWidth,scroll:document.documentElement.scrollWidth,bookHeight:b.height,chartHeight:c.height,
                    bottomGap:Math.abs(b.bottom-c.bottom),bookOverflow:book.scrollHeight-book.clientHeight};
                }''')
                assert dims['scroll']<=width,dims
                if width>1080:
                    assert dims['bottomGap']<2,dims
                    assert dims['bookOverflow']<3,{'tab':tab,**dims}
                result['viewports'].append({'tab':tab,**dims})
        # 独立浏览器夹具：过期复权缓存自动补齐；失败退避且可显式重试。
        page.set_viewport_size({'width':1600,'height':1000})
        state={'attempts':0}
        def stale_bars(route):
            response=route.fetch()
            body=response.json()
            body['data']['history_refresh_due']=True
            route.fulfill(response=response,json=body)
        def fail_sync(route):
            state['attempts']+=1
            route.fulfill(status=422,json={'error':{'code':'TEST_UNAVAILABLE','message_zh':'测试源临时不可用'}})
        page.route('**/api/v1/market/bars?*adjustment=qfq',stale_bars)
        page.route('**/api/v1/securities/*/history/sync?adjustment=qfq',fail_sync)
        page.get_by_role('button',name='前复权',exact=True).click()
        expect(page.locator('.error-line')).to_contain_text('测试源临时不可用')
        assert state['attempts']==1
        page.get_by_role('button',name='周 K',exact=True).click()
        expect(page.get_by_role('button',name='周 K',exact=True)).to_have_class('active')
        page.wait_for_timeout(250)
        assert state['attempts']==1,'失败后不应因周期切换立即重复自动请求'
        page.get_by_role('button',name='刷新行情',exact=True).click()
        expect(page.get_by_role('button',name='刷新行情',exact=True)).to_be_enabled(timeout=15000)
        assert state['attempts']==2,'显式刷新应能重试'
        result['adjustment_auto_refresh']={'expired_cache_queued':True,'failure_backoff':True,'manual_retry':True,'data':'browser-only interception'}
        assert not result['errors'],result['errors']
        browser.close()
    (OUT/'ui-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
