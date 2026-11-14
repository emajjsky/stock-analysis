"""第四轮实际8765验收：真实数据、所有标签图表边界、ETF完整浏览。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/boards-fourth-20261107'
OUT.mkdir(parents=True, exist_ok=True)


def viewport(chart):
    return chart.evaluate('''e => ({count:Number(e.dataset.pointCount), from:Number(e.dataset.rangeFrom), to:Number(e.dataset.rangeTo), width:e.clientWidth, height:e.clientHeight})''')


def bounded(value, full=False):
    assert value['count'] > 1 and value['width'] > 100 and value['height'] > 60, value
    assert value['from'] >= -0.6 and value['to'] <= value['count'] - 0.4, value
    if full:
        assert value['from'] <= 0.6 and value['to'] >= value['count'] - 1.6, value


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    errors, requests, checks = [], [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(dict(method=r.method, url=r.url)) if r.method == 'POST' else None)
    page.goto('http://127.0.0.1:8765/#/market')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.board-top-panel tbody tr', timeout=60000)
    assert page.locator('.data-ribbon,.market-source,.app-footer,.concept-count,.etf-toolbar,.etf-foot').count() == 0

    # 真实接口覆盖及值，不能用空态或截取截图报价冒充接入。
    positions = {}
    for kind in ('industry','concept'):
        response = page.request.get('http://127.0.0.1:8765/api/v1/market/boards/positions?kind='+kind)
        assert response.ok
        d = response.json()['data']
        assert d['total'] > 400 and d['covered'] == d['total'], {k:d.get(k) for k in ['covered','total','progress','error']}
        assert all(row['position_2d'] is not None for row in d['rows'])
        positions[kind] = d
    (OUT/'live-positions.json').write_text(json.dumps(positions,ensure_ascii=False,indent=2),encoding='utf-8')

    def exercise(chart, label):
        chart.wait_for(timeout=60000)
        chart.scroll_into_view_if_needed()
        page.wait_for_timeout(100)
        box = chart.bounding_box()
        x, y = box['x'] + box['width'] * .55, box['y'] + box['height'] * .4
        page.mouse.move(x, y)
        for _ in range(12):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(15)
        page.wait_for_timeout(120)
        full = viewport(chart)
        bounded(full, full=True)
        for _ in range(4):
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(25)
        page.wait_for_timeout(120)
        zoom = viewport(chart)
        bounded(zoom)
        assert zoom['to'] - zoom['from'] < full['to'] - full['from'] - 1, (label, full, zoom)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + box['width'] * .7, y, steps=10)
        page.mouse.up()
        page.wait_for_timeout(150)
        dragged = viewport(chart)
        bounded(dragged)
        # 每个图独立验证缩进展开后保留范围，不只检查整页是否横向溢出。
        before = dragged['to'] - dragged['from']
        page.get_by_role('button', name='收起侧边栏', exact=True).click()
        page.wait_for_timeout(220)
        bounded(viewport(chart))
        page.get_by_role('button', name='展开侧边栏', exact=True).click()
        page.wait_for_timeout(220)
        restored = viewport(chart)
        bounded(restored)
        assert abs(restored['to'] - restored['from'] - before) < 1, (label, dragged, restored)
        chart.scroll_into_view_if_needed()
        box = chart.bounding_box()
        page.mouse.move(box['x'] + box['width']*.5, box['y'] + box['height']*.4)
        for _ in range(12):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(15)
        page.wait_for_timeout(150)
        bounded(viewport(chart), full=True)
        checks.append(dict(label=label, full=full, zoom=zoom, dragged=dragged, restored=restored))

    tabs = ['板块热点','板块轮动','板块分析','板块资金','板块增仓','最新概念','期股联动']
    for index, tab in enumerate(tabs, 1):
        page.get_by_role('tab', name=tab, exact=True).click()
        if tab == '最新概念':
            page.wait_for_selector('.board-top-panel tbody tr',timeout=60000)
            page.locator('.board-top-panel tbody tr').filter(has_text='2026三季报预增').click()
        if tab == '期股联动':
            page.wait_for_selector('.board-top-panel tbody tr',timeout=60000)
            page.get_by_role('textbox',name='搜索期货',exact=True).fill('生猪')
            page.locator('.board-top-panel tbody tr').first.click()
        if tab == '板块增仓':
            page.wait_for_selector('.board-top-panel tbody tr',timeout=60000)
            for name in ['2日','3日','今日']:
                page.locator('.position-options').get_by_role('button',name=name,exact=True).click()
                assert name+'增仓' in page.locator('.board-top-panel thead').inner_text()
                first=page.locator('.board-top-panel tbody tr').first
                first.click()
            page.get_by_role('button',name='概念',exact=True).click()
            page.wait_for_function("document.querySelector('.board-top-panel tbody tr')?.textContent.includes('%')")
            page.get_by_role('button',name='行业',exact=True).click()
        for panel_name in ['main-chart-panel', 'stock-chart-panel']:
            panel = page.locator('.'+panel_name)
            if not panel.count():
                continue
            for mode in ['分时','日K']:
                panel.get_by_role('button',name=mode,exact=True).click()
                exercise(panel.locator('.board-mini-chart'), tab+'/'+panel_name+'/'+mode)
        for i in range(page.locator('.metric-canvas').count()):
            exercise(page.locator('.metric-canvas').nth(i), tab+'/指标图'+str(i+1))
        page.locator('.market-page').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/f'{index:02}-{tab}.png'),full_page=True)
        print('PASS',tab,flush=True)

    # ETF紧凑区域与完整可操作目录，搜索会重置分页，Esc关闭后焦点返回。
    page.get_by_role('tab',name='板块热点',exact=True).click()
    page.get_by_role('button',name='行业',exact=True).click()
    page.get_by_role('textbox',name='搜索板块',exact=True).fill('种子')
    page.locator('.board-top-panel tbody tr').first.click()
    page.get_by_role('textbox',name='搜索板块',exact=True).fill('')
    page.wait_for_selector('.etf-row',timeout=60000)
    visible = page.locator('.etf-rows').evaluate('''e=>{const b=e.getBoundingClientRect();return [...e.querySelectorAll('.etf-row')].filter(r=>{const x=r.getBoundingClientRect();return x.top>=b.top&&x.bottom<=b.bottom}).length}''')
    assert visible >= 5,visible
    page.get_by_role('button',name='展开ETF列表',exact=True).click()
    dialog=page.get_by_role('dialog',name='ETF行情浏览',exact=True)
    dialog.wait_for()
    assert dialog.locator('tbody tr').count() >= 5
    page.get_by_role('combobox',name='ETF浏览范围',exact=True).select_option('all')
    assert dialog.locator('tbody tr').count() == 50
    page.get_by_role('combobox',name='ETF每页数量',exact=True).select_option('100')
    assert dialog.locator('tbody tr').count() == 100
    first=dialog.locator('tbody tr').first.inner_text()
    dialog.get_by_role('button',name='下一页',exact=True).click()
    assert dialog.locator('tbody tr').first.inner_text()!=first
    page.get_by_role('textbox',name='搜索ETF',exact=True).fill('510300')
    assert dialog.locator('tbody tr').count()==1 and '510300' in dialog.locator('tbody').inner_text()
    page.get_by_role('textbox',name='搜索ETF',exact=True).fill('')
    dialog.get_by_role('button',name='涨跌幅',exact=False).click()
    page.screenshot(path=str(OUT/'08-ETF完整浏览.png'))
    total_text=page.get_by_role('combobox',name='ETF浏览范围').inner_text()
    page.keyboard.press('Escape')
    assert not dialog.is_visible()
    assert page.get_by_role('button',name='展开ETF列表',exact=True).evaluate('(e)=>document.activeElement===e')

    layouts=[]
    for width,height,zoom in [(1366,768,1),(1920,1080,1),(1366,768,1.25),(390,844,1)]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(z)=>document.documentElement.style.zoom=String(z)',zoom)
        for tab in tabs:
            page.get_by_role('tab',name=tab,exact=True).click()
            page.wait_for_timeout(200)
            assert not page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'),(width,height,zoom,tab)
            layouts.append(dict(width=width,height=height,zoom=zoom,tab=tab,overflow=False))
        page.screenshot(path=str(OUT/f'layout-{width}-{zoom}.png'),full_page=True)
    page.evaluate('document.documentElement.style.zoom="1"')
    page.set_viewport_size({'width':1600,'height':1000})
    page.get_by_role('tab',name='板块增仓',exact=True).click()
    page.get_by_role('button',name='功能与数据',exact=True).click()
    assert 'TradingView' in page.get_by_role('dialog',name='功能与数据覆盖').inner_text()
    page.get_by_role('button',name='关闭功能说明',exact=True).click()
    assert not errors,errors
    assert not any('/activate' in r['url'] for r in requests if '/ETF' in r['url'])
    forbidden=[r for r in requests if any(x in r['url'] for x in ['/sim/','/orders','/monitors','/reviews'])]
    assert not forbidden,forbidden
    report=dict(errors=errors,charts=checks,layouts=layouts,visible_etfs=visible,etf_scope=total_text,
                position_coverage={k:dict(covered=d['covered'],total=d['total']) for k,d in positions.items()})
    (OUT/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',len(checks),'chart cases;',len(layouts),'layouts; errors',errors)
    browser.close()
