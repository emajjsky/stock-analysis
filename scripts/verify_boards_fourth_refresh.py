"""第四轮刷新视野、ETF小屏和焦点范围验收。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/boards-fourth-20261107'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    page = browser.new_page(viewport={'width':1600,'height':1000})
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/#/market')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.main-chart-panel .board-mini-chart',timeout=60000)
    def get(path):
        return page.request.get('http://127.0.0.1:8765/api/v1'+path).json()['data']
    def settings_snapshot():
        values={k:get(k) for k in ['/data/refresh','/watchlists','/monitors']}
        # 刷新状态/行情会变化；仅对比用户配置和实际自选记录。
        values['/data/refresh']={k:values['/data/refresh'][k] for k in ['enabled','interval_seconds']}
        values['/watchlists']=[{k:v for k,v in row.items() if k!='security'} for row in values['/watchlists']]
        return values
    before=settings_snapshot()
    chart=page.locator('.main-chart-panel .board-mini-chart')
    box=chart.bounding_box()
    page.mouse.move(box['x']+box['width']*.4,box['y']+box['height']*.4)
    for _ in range(5):
        page.mouse.wheel(0,-600)
        page.wait_for_timeout(50)
    def span():
        return chart.evaluate('(e)=>({from:Number(e.dataset.rangeFrom),to:Number(e.dataset.rangeTo),count:Number(e.dataset.pointCount)})')
    zoom=span()
    page.get_by_role('button',name='刷新行情',exact=True).click()
    page.wait_for_timeout(3800)
    refreshed=span()
    assert abs((zoom['to']-zoom['from'])-(refreshed['to']-refreshed['from']))<1,(zoom,refreshed)
    page.set_viewport_size({'width':1366,'height':768})
    page.wait_for_timeout(300)
    resized=span()
    assert abs((zoom['to']-zoom['from'])-(resized['to']-resized['from']))<1,(zoom,resized)
    page.get_by_role('tab',name='板块增仓',exact=True).click()
    page.wait_for_selector('.layout-position .board-top-panel tbody tr',timeout=60000)
    page.get_by_role('button',name='刷新行情',exact=True).click()
    page.wait_for_timeout(1000)
    assert get('/market/boards/positions')['covered']>400
    page.get_by_role('tab',name='板块热点',exact=True).click()
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='展开ETF列表',exact=True).click()
    dialog=page.get_by_role('dialog',name='ETF行情浏览')
    dialog.wait_for()
    page.get_by_role('combobox',name='ETF浏览范围').select_option('all')
    assert not page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1')
    for key in ['Tab']*16 + ['Shift+Tab']*16:
        page.keyboard.press(key)
        assert dialog.evaluate('(d)=>d.contains(document.activeElement)'), key
    page.screenshot(path=str(OUT/'09-ETF窄屏.png'))
    page.keyboard.press('Escape')
    assert not dialog.is_visible()
    after=settings_snapshot()
    assert before==after, '自选/监测/更新设置发生变化'
    assert not errors,errors
    result=dict(zoom=zoom,after_refresh=refreshed,after_resize=resized,mobile_dialog_overflow=False,
                keyboard_focus_trapped=True,watchlists_monitors_refresh_settings_unchanged=True,errors=errors)
    (OUT/'refresh-and-accessibility.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    browser.close()
