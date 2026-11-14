"""既有8765服务的图表工作区验收；拦截仅发生在独立浏览器，不写假行情入库。"""
import hashlib
import json
import re
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/chart-workspace'
BASE = 'http://127.0.0.1:8765'
KEY = 'LIVE.SZ.300502'


def choose(page, label, option):
    if label in ['主图指标','副图指标选择','分时副图']:
        page.get_by_role('group',name=label,exact=True).get_by_role('button',name=option,exact=True).click()
        page.mouse.move(240,100)
        return
    page.get_by_role('button', name=label, exact=True).click()
    page.get_by_role('option').filter(has_text=option).click()
    page.mouse.move(240, 100)


def geometry(page):
    return page.locator('.chart-stack').evaluate('''e=>{
      const b=e.getBoundingClientRect(),v=e.querySelector('.volume-heading').getBoundingClientRect(),
        s=e.querySelector('.secondary-heading').getBoundingClientRect();
      return {height:b.height,volume:v.top-b.top,secondary:s.top-b.top,
        volumeHeader:v.height,secondaryHeader:s.height,
        paneCanvases:e.querySelectorAll('tr > td:nth-child(2) canvas').length};
    }''')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'errors': [], 'main': [], 'secondary': [], 'viewports': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        context = browser.new_context(viewport={'width':1600,'height':1100},locale='zh-CN')
        page = context.new_page()
        page.on('pageerror', lambda e: result['errors'].append(str(e)))
        page.goto(BASE + '/#/stock/' + KEY)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('group',name='分时副图',exact=True)).to_be_visible(timeout=20000)
        result['intraday_panes'] = geometry(page)
        assert result['intraday_panes']['volume'] > 250
        assert result['intraday_panes']['secondary'] > result['intraday_panes']['volume']+65
        for value in ['RSI','MACD']:
            choose(page,'分时副图',value)
            expect(page.locator('.secondary-heading .pane-values')).not_to_contain_text('—')
        expect(page.locator('.chart-legend')).to_contain_text('均价')
        expect(page.locator('.chart-panel')).not_to_contain_text('数据口径')
        page.screenshot(path=str(OUT/'01-stock-intraday.png'),full_page=True)

        # 分时也能找到复权；选择后进入对应K线。
        choose(page,'复权方式','前复权')
        expect(page.get_by_role('button',name='日 K',exact=True)).to_have_class('active')
        expect(page.get_by_role('group',name='主图指标',exact=True)).to_be_visible()
        result['kline_panes'] = geometry(page)
        assert result['kline_panes']['volume']>250
        for option in ['布林带 BOLL','指数均线 EXPMA','多空均线 BBI','抛物线 SAR','均线 MA']:
            choose(page,'主图指标',option)
            expect(page.locator('.chart-ma-values')).not_to_contain_text('—')
            result['main'].append(option)
        for option in ['MACD','KDJ','RSI','OBV','W&R','MTM','VR','ARBR','DMI','BIAS','DMA','ASI','TRIX','DPO']:
            choose(page,'副图指标选择',option)
            expect(page.locator('.secondary-heading .pane-values')).not_to_contain_text('—')
            result['secondary'].append(option)
        choose(page,'副图指标选择','MACD')

        # 默认前五条勾选，修改周期和显示状态即时生效，重载记住偏好。
        page.locator('.ma-picker summary').click()
        for i in range(1,9):
            control = page.get_by_role('checkbox',name=f'显示第{i}条均线',exact=True)
            assert control.is_checked() == (i<=5)
        page.get_by_role('spinbutton',name='第1条均线周期',exact=True).fill('7')
        page.get_by_role('checkbox',name='显示第2条均线',exact=True).uncheck()
        page.get_by_role('checkbox',name='显示第6条均线',exact=True).check()
        page.locator('.ma-picker summary').click()
        expect(page.locator('.chart-ma-values')).to_contain_text('MA7')
        expect(page.locator('.chart-ma-values')).not_to_contain_text('MA10 ')
        bars=page.request.get(BASE+'/api/v1/market/bars?security_id='+KEY+'&timeframe=1d&adjustment=qfq').json()['data']['bars']
        average=sum(float(b['close']) for b in bars[-7:])/7
        shown=page.locator('.chart-ma-values > span').first.inner_text()
        assert abs(float(shown.split()[-1].replace(',',''))-average)<0.001,(shown,average)
        result['ma7']={'expected':average,'display':shown,'selected':5}
        page.reload();page.wait_for_load_state('networkidle')
        page.get_by_role('button',name='日 K',exact=True).click()
        expect(page.locator('.chart-ma-values')).to_contain_text('MA7')
        page.locator('.ma-picker summary').click()
        expect(page.get_by_role('spinbutton',name='第1条均线周期',exact=True)).to_have_value('7')
        expect(page.get_by_role('checkbox',name='显示第2条均线',exact=True)).not_to_be_checked()
        page.get_by_role('button',name='恢复默认',exact=True).click()
        page.locator('.ma-picker summary').click()
        for label,unit in [('周 K','周'),('月 K','月'),('日 K','日')]:
            page.get_by_role('button',name=label,exact=True).click()
            expect(page.locator('.ma-picker')).to_be_visible()
            page.locator('.ma-picker summary').click()
            expect(page.locator('.ma-settings')).to_contain_text('周期单位为'+unit)
            page.locator('.ma-picker summary').click()

        # 三种真实复权返回值不同，菜单口径与实际图表口径一致。
        adjustments={}
        for option,value in [('前复权','qfq'),('后复权','hfq'),('除权 / 不复权','none')]:
            choose(page,'复权方式',option)
            expect(page.locator('.chart-adjustment-label')).to_have_text(option)
            body=page.request.get(BASE+'/api/v1/market/bars?security_id='+KEY+'&adjustment='+value).json()['data']
            assert body['adjustment']==value.upper()
            adjustments[value]={b['time']:b['close'] for b in body['bars']}
        common=set.intersection(*(set(x) for x in adjustments.values()))
        sample=next(d for d in sorted(common,reverse=True) if len({x[d] for x in adjustments.values()})==3)
        result['adjustments']={'date':sample,'close':{a:x[sample] for a,x in adjustments.items()}}
        choose(page,'复权方式','前复权')

        # “全部”时滚轮不应再次改变K线绘图。
        page.get_by_role('button',name='全部',exact=True).click()
        chart=page.locator('[aria-label="K线图，支持缩放、拖动、均线和技术指标"]')
        canvas=max(chart.locator('canvas').all(),key=lambda c:c.evaluate('(e)=>e.clientWidth*e.clientHeight'))
        chart.scroll_into_view_if_needed();box=chart.bounding_box()
        page.mouse.move(box['x']+box['width']*.5,box['y']+80);page.wait_for_timeout(150)
        before=hashlib.sha256(canvas.screenshot()).hexdigest()
        for _ in range(5):page.mouse.wheel(0,-120)
        page.wait_for_timeout(250)
        after=hashlib.sha256(canvas.screenshot()).hexdigest()
        assert before==after,'全部模式滚轮改变了绘图'
        result['all_disables_wheel']=True
        page.get_by_role('button',name='一年',exact=True).click();page.mouse.move(240,100)
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(OUT/'02-kline-workspace.png'),full_page=True)
        page.locator('.ma-picker summary').click()
        page.screenshot(path=str(OUT/'03-ma-settings.png'),full_page=True)
        page.locator('.ma-picker summary').click()
        search=page.locator('.global-search input');search.focus()
        style=search.evaluate('(e)=>({outline:getComputedStyle(e).outlineStyle,parent:getComputedStyle(e.parentElement).borderColor})')
        assert style['outline']=='none',style
        result['search_focus']=style
        page.mouse.click(250,100)

        # 可见面积与菜单可操作，不只检查DOM存在。
        for width,height in [(1920,1080),(1366,768),(1093,614),(390,844)]:
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
            dims=page.evaluate('''()=>{
              const b=document.querySelector('.order-book'),c=document.querySelector('.stock-chart-column');
              return {scroll:document.documentElement.scrollWidth,width:innerWidth,bookOverflow:b.scrollHeight-b.clientHeight,
                bottomGap:Math.abs(b.getBoundingClientRect().bottom-c.getBoundingClientRect().bottom)};
            }''')
            assert dims['scroll']<=width,dims
            if width>1080:
                assert dims['bottomGap']<2 and dims['bookOverflow']<3,dims
            choose(page,'副图指标选择','KDJ')
            result['viewports'].append(dims)
        page.screenshot(path=str(OUT/'04-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1600,'height':1100})

        # 真正清除会话cookie，运行中的API客户端自动恢复；不刷新页面。
        sessions=[]; unauthorized=[]
        page.on('response',lambda response: sessions.append(response.status) if response.url.endswith('/api/v1/session') else unauthorized.append(response.url) if response.status==401 else None)
        context.clear_cookies()
        started=time.monotonic()
        page.locator('.global-search input').fill('301210')
        page.get_by_role('option').filter(has_text='金杨').click()
        expect(page.locator('main h1')).to_contain_text('金杨',timeout=20000)
        expect(page.locator('.stock-chart-loading')).to_have_count(0,timeout=65000)
        result['new_stock']={'seconds_to_chart_or_explicit_error':round(time.monotonic()-started,2),
            'has_chart':page.locator('.chart-stack').count()>0,
            'state':page.locator('.stock-chart-column').inner_text()[:650]}
        # 站内搜索跳转不会刷新客户端；抓到401和单次session恢复。
        assert len(unauthorized)>=1 and len(sessions)==1,(unauthorized,sessions)
        result['session_recovery']={'unauthorized':len(unauthorized),'new_sessions':len(sessions),'no_error': '会话已失效' not in page.locator('main').inner_text()}
        assert result['session_recovery']['no_error']

        # 真实指数旧缓存读时清洗，页面不再绘制股票均价线。
        series=page.request.get(BASE+'/api/v1/market/indices/sh000001/intraday').json()['data']
        assert series['average_supported'] is False and all(x['average_price'] is None for x in series['points'])
        page.goto(BASE+'/');page.wait_for_load_state('networkidle')
        expect(page.locator('[aria-label="分时与成交量图"]')).to_be_visible(timeout=20000)
        expect(page.locator('.intraday-toolbar')).to_contain_text('指数点位')
        expect(page.locator('.chart-legend')).not_to_contain_text('均价')
        result['index_average_removed']={'points':len(series['points']),'first_price':series['points'][0]['value']}
        page.screenshot(path=str(OUT/'05-index-intraday.png'),full_page=True)
        assert not result['errors'],result['errors']
        browser.close()
    (OUT/'ui-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
