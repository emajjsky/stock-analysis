"""标签指标与真实量额切换；复用唯一8765，不写入测试行情。"""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import expect,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/indicator-tabs'
BASE='http://127.0.0.1:8765'


def choose(page,group,name):
    button=page.get_by_role('group',name=group,exact=True).get_by_role('button',name=name,exact=True)
    button.click();page.mouse.move(240,95)
    expect(button).to_have_attribute('aria-pressed','true')
    assert page.get_by_role('group',name=group,exact=True).locator('[aria-pressed=true]').count()==1


def plot(page,pane):
    chart=page.locator('.chart-stack .stock-chart')
    # lightweight-charts的pane中间单元格是绘图区，两层canvas的第一层为数据。
    canvas=chart.locator('tr').nth(pane).locator('td').nth(1).locator('canvas').first
    page.wait_for_timeout(100)
    return hashlib.sha256(canvas.screenshot()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    result={'errors':[],'main':[],'secondary':[],'viewports':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page=browser.new_page(viewport={'width':1700,'height':1200},locale='zh-CN')
        page.on('pageerror',lambda e:result['errors'].append(str(e)))
        page.goto(BASE+'/#/stock/LIVE.SZ.300502');page.wait_for_load_state('networkidle')
        expect(page.get_by_role('group',name='分时副图',exact=True)).to_be_visible(timeout=15000)
        for value in ['RSI','MACD']:choose(page,'分时副图',value)
        for group in ['分时副图','量图指标']:
            assert page.get_by_role('group',name=group,exact=True).locator('[aria-haspopup]').count()==0
        quantity=page.get_by_role('checkbox',name='显示量额均线',exact=True)
        expect(quantity).to_be_checked()
        vol=plot(page,2)
        choose(page,'量图指标','成交额')
        expect(page.locator('.volume-heading')).to_contain_text('成交额')
        expect(page.locator('.quantity-current')).to_contain_text('元')
        amount=plot(page,2)
        assert vol!=amount,'成交额未改变柱线图'
        row=page.request.get(BASE+'/api/v1/market/intraday?security_id=LIVE.SZ.300502').json()['data']['points']
        expected=float(row[-1]['cumulative_amount'])-float(row[-2]['cumulative_amount'])
        actual=page.locator('.quantity-current').inner_text()
        assert str(round(expected/10000,2)) in actual or str(round(expected/1e8,2)) in actual,(actual,expected)
        quantity.uncheck()
        expect(page.locator('.quantity-average-values')).to_have_count(0)
        assert plot(page,2)!=amount,'量均线开关未改变图形'
        quantity.check();choose(page,'量图指标','成交量')
        expect(page.locator('.quantity-current')).to_contain_text('股')
        result['intraday']={'amount':expected,'display':actual,'volume_amount_differ':True,'ma_toggle_changes_canvas':True}
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(OUT/'01-intraday-tabs.png'),full_page=True)

        page.get_by_role('button',name='日 K',exact=True).click()
        expect(page.get_by_role('group',name='主图指标',exact=True)).to_be_visible(timeout=15000)
        main_hashes=[]
        for value in ['均线 MA','布林带 BOLL','指数均线 EXPMA','多空均线 BBI','抛物线 SAR']:
            choose(page,'主图指标',value)
            expect(page.locator('.chart-ma-values')).not_to_contain_text('—')
            result['main'].append(value)
            main_hashes.append(plot(page,0))
        assert len(set(main_hashes))==5,'主图标签未全部改变曲线'
        for value in ['MACD','KDJ','RSI','OBV','W&R','MTM','VR','ARBR','DMI','BIAS','DMA','ASI','TRIX','DPO']:
            choose(page,'副图指标选择',value)
            expect(page.locator('.secondary-heading')).to_contain_text(value)
            expect(page.locator('.secondary-heading .pane-values')).not_to_contain_text('—')
            result['secondary'].append(value)
        choose(page,'主图指标','均线 MA');choose(page,'副图指标选择','MACD')
        choose(page,'量图指标','成交额')
        bars=page.request.get(BASE+'/api/v1/market/bars?security_id=LIVE.SZ.300502&adjustment=qfq').json()['data']['bars']
        if all(b['amount'] is None for b in bars):
            expect(page.locator('.quantity-unavailable')).to_contain_text('来源未提供')
            expect(page.locator('.quantity-current')).to_have_text('—')
            result['missing_history_amount']='explicit missing, no fabricated columns'
        choose(page,'量图指标','成交量')
        expect(page.locator('.quantity-average-values')).not_to_contain_text('—')
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(OUT/'02-kline-tabs.png'),full_page=True)

        for width,height in [(1920,1080),(1366,768),(1093,614),(390,844)]:
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
            choose(page,'副图指标选择','DPO');choose(page,'主图指标','多空均线 BBI')
            dims=page.evaluate('''()=>{
              const c=document.querySelector('.stock-chart-column'),b=document.querySelector('.order-book');
              const stack=document.querySelector('.chart-stack').getBoundingClientRect(),controls=document.querySelector('.chart-metric-controls').getBoundingClientRect();
              return {width:innerWidth,scroll:document.documentElement.scrollWidth,stackHeight:stack.height,
                controlsAfterCanvas:controls.top>=stack.bottom-1,bottomGap:Math.abs(c.getBoundingClientRect().bottom-b.getBoundingClientRect().bottom),
                labels:[...document.querySelectorAll('.indicator-tabs')].map(e=>e.scrollWidth-e.clientWidth)};
            }''')
            assert dims['scroll']<=width and dims['controlsAfterCanvas'] and max(dims['labels'])<2,dims
            assert dims['stackHeight']>350,dims
            if width>1080:assert dims['bottomGap']<2,dims
            result['viewports'].append(dims)
        page.screenshot(path=str(OUT/'03-mobile-tabs.png'),full_page=True)
        # 响应轮询后选中态保持，不把成交额重置为成交量。
        choose(page,'量图指标','成交额')
        page.wait_for_timeout(11000)
        expect(page.get_by_role('group',name='量图指标').get_by_role('button',name='成交额',exact=True)).to_have_attribute('aria-pressed','true')
        assert not result['errors'],result['errors']
        browser.close()
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
