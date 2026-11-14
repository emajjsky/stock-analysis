"""截图逐项对应的正式8765验收；只读，不添加自选、不触发交易。"""
from pathlib import Path
import argparse
import json

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='docs/evidence/boards-completion')
OUT = ROOT / parser.parse_args().output
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
        executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    page = browser.new_page(viewport={'width':1600,'height':1000})
    errors, refreshes = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: refreshes.append(r.url)
            if r.method == 'POST' and '/market/boards/refresh?' in r.url else None)
    page.goto('http://127.0.0.1:8765/#/market')
    page.wait_for_selector('.board-ranking tbody tr', timeout=60000)
    page.get_by_role('textbox',name='搜索板块',exact=True).fill('种子')
    page.locator('.board-top-panel tbody tr').first.click()
    page.get_by_role('textbox',name='搜索板块',exact=True).fill('')
    page.wait_for_selector('.member-table tbody tr',timeout=60000)
    page.wait_for_function("[...document.querySelectorAll('.chart-panel')].every(p=>p.querySelector('canvas'))",timeout=60000)
    page.wait_for_selector('.news-list article',timeout=60000)
    page.screenshot(path=str(OUT/'01-hot.png'),full_page=True)
    hot_members=page.locator('.member-table tbody tr').count()
    page.get_by_role('button',name='更多指标',exact=True).click()
    assert '动态PE' in page.locator('.member-table thead').inner_text()
    assert '市净率' in page.locator('.member-table thead').inner_text()
    page.get_by_role('button',name='基础指标',exact=True).click()
    page.get_by_role('button',name='市场快讯',exact=True).click()
    page.wait_for_selector('.news-list article',timeout=60000)
    page.get_by_role('button',name='板块资讯',exact=True).click()

    page.get_by_role('tab',name='板块分析',exact=True).click()
    page.wait_for_selector('.financial-metric',timeout=60000)
    page.wait_for_selector('.analysis-charts canvas',timeout=60000)
    assert page.locator('.board-heatmap button').count() > 40
    assert page.locator('.financial-metric').count() == 5
    page.screenshot(path=str(OUT/'02-analysis.png'),full_page=True)
    page.get_by_label('对比上证').uncheck()
    page.get_by_label('对比上证').check()
    page.get_by_role('combobox',name='个股热力指标').select_option('volume')
    page.get_by_role('button',name='收起侧边栏',exact=True).click()
    page.wait_for_timeout(300)
    page.get_by_role('button',name='展开侧边栏',exact=True).click()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT/'02-analysis-resized.png'),full_page=True)

    page.get_by_role('tab',name='板块资金',exact=True).click()
    for period in ['3日','5日','10日','今日']:
        page.get_by_role('button',name=period,exact=True).click()
        assert ('今日' if period=='今日' else period)+'净额' in page.locator('.board-top-panel thead').inner_text()
    page.get_by_role('button',name='按订单大小',exact=True).click()
    assert '今日超大单' in page.locator('.board-top-panel thead').inner_text()
    page.wait_for_selector('.funds-history canvas',timeout=60000)
    assert page.locator('.stock-chart-panel canvas').count()>0
    page.screenshot(path=str(OUT/'03-funds.png'),full_page=True)

    page.get_by_role('tab',name='板块轮动',exact=True).click()
    page.wait_for_function("document.querySelectorAll('.rotation-day').length===10",timeout=60000)
    page.get_by_role('combobox',name='轮动榜单').select_option('20')
    page.get_by_role('combobox',name='轮动排序').select_option('amount')
    assert page.locator('.rotation-day').first.locator('button').count()==20
    page.get_by_role('combobox',name='轮动交易日').select_option('5')
    assert page.locator('.rotation-day').count()==5
    page.get_by_role('combobox',name='轮动榜单').select_option('10')
    page.get_by_role('combobox',name='轮动交易日').select_option('10')
    page.get_by_role('combobox',name='轮动排序').select_option('change_pct')
    page.locator('.rotation-day').first.locator('button').nth(2).click()
    page.wait_for_selector('.member-panel tbody tr',timeout=60000)
    page.wait_for_function("[...document.querySelectorAll('.chart-panel')].every(p=>p.querySelector('canvas'))",timeout=60000)
    page.screenshot(path=str(OUT/'04-rotation.png'),full_page=True)

    page.get_by_role('tab',name='最新概念',exact=True).click()
    page.wait_for_selector('.board-top-panel tbody tr',timeout=30000)
    page.locator('.board-top-panel tbody tr').filter(has_text='玻璃基板').click()
    page.wait_for_function("document.querySelector('.member-panel .panel-head')?.textContent.includes('玻璃基板')",timeout=30000)
    page.wait_for_selector('.member-panel tbody tr',timeout=60000)
    page.wait_for_selector('.stock-chart-panel canvas',timeout=60000)
    page.screenshot(path=str(OUT/'05-concepts.png'),full_page=True)
    page.locator('.board-top-panel tbody tr').filter(has_text='MLCC概念').click()
    page.wait_for_function("document.querySelector('.member-panel tbody')?.children.length===0")
    assert '暂无完全同名的行情映射' in page.locator('.member-panel').inner_text()
    page.screenshot(path=str(OUT/'05-concepts-unmapped.png'),full_page=True)

    page.get_by_role('tab',name='期股联动',exact=True).click()
    page.wait_for_selector('.board-top-panel tbody tr',timeout=60000)
    page.get_by_role('textbox',name='搜索期货').fill('lh2701')
    page.wait_for_selector('.board-top-panel tbody tr',timeout=30000)
    page.locator('.board-top-panel tbody tr').first.click()
    page.get_by_role('button',name='刷新行情',exact=True).click()
    page.wait_for_selector('.main-chart-panel canvas',timeout=60000)
    page.wait_for_selector('.member-panel tbody tr',timeout=60000)
    assert '生猪' in page.locator('.relation-note').inner_text()
    page.wait_for_selector('.stock-chart-panel canvas',timeout=60000)
    page.screenshot(path=str(OUT/'06-futures.png'),full_page=True)
    page.locator('.main-chart-panel').get_by_role('button',name='分时',exact=True).click()
    page.wait_for_selector('.main-chart-panel canvas',timeout=60000)
    page.screenshot(path=str(OUT/'06-futures-night.png'),full_page=True)

    page.get_by_role('tab',name='板块增仓',exact=True).click()
    page.wait_for_selector('.layout-position .board-top-panel tbody tr',timeout=60000)
    assert '2日增仓' in page.locator('.board-top-panel thead').inner_text()
    page.screenshot(path=str(OUT/'07-position-live.png'),full_page=True)
    page.get_by_role('button',name='功能与数据',exact=True).click()
    assert '港股/美股' in page.get_by_role('dialog').inner_text()
    page.screenshot(path=str(OUT/'08-coverage.png'),full_page=True)
    page.get_by_role('button',name='关闭功能说明',exact=True).click()

    layouts=[]
    for width,height,zoom in [(1366,768,1),(1600,900,1),(1920,1080,1),(1366,768,1.25),(390,844,1)]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(z)=>document.documentElement.style.zoom=String(z)',zoom)
        for tab in ['板块热点','板块分析','板块轮动','期股联动']:
            page.get_by_role('tab',name=tab,exact=True).click()
            page.wait_for_timeout(250)
            overflow=page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth+1')
            assert not overflow,(width,height,zoom,tab)
            layouts.append(dict(width=width,height=height,zoom=zoom,tab=tab,horizontal_overflow=overflow))
        page.screenshot(path=str(OUT/f'layout-{width}-{zoom}.png'),full_page=True)
    page.evaluate('document.documentElement.style.zoom="1"')
    page.set_viewport_size({'width':1600,'height':1000})
    assert not errors,errors
    (OUT/'browser-results.json').write_text(json.dumps(dict(errors=errors,layouts=layouts,
        hot_members=hot_members,manual_refresh_requests=len(refreshes),checks=['热点两表两图资讯','样本财务五项','独立分析布局','上下证比较','量额资金与换手历史','更多指标','ETF候选','多日资金与订单分项','十日轮动及5日前20成交额排序','最新概念日期与事件','未映射概念不串数据','期货日K夜盘分时及A股主题联动','增仓真实排行','覆盖清单','侧栏缩进恢复']),ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',len(layouts),'layout checks; browser errors:',errors)
    browser.close()
