"""2026-11-07 七项截图反馈的正式服务验收；不改自选、算法或交易。"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/boards-fourth-20261107/revision-regression'
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8765/#/market')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.board-top-panel tbody tr', timeout=60000)
    assert page.locator('.data-ribbon').count() == 0
    assert page.locator('.concept-strip').count() == 0
    page.get_by_role('textbox', name='搜索板块', exact=True).fill('种子')
    page.locator('.board-top-panel tbody tr').first.click()
    page.get_by_role('textbox', name='搜索板块', exact=True).fill('')
    page.wait_for_selector('.etf-row', timeout=60000)
    assert '农业' in page.locator('.etf-panel').inner_text()
    page.screenshot(path=str(OUT / '01-hot.png'), full_page=True)

    page.get_by_role('tab', name='最新概念', exact=True).click()
    page.wait_for_selector('.board-top-panel tbody tr', timeout=30000)
    assert page.locator('.concept-strip, .concept-event').count() == 0
    page.locator('.board-top-panel tbody tr').filter(has_text='2026三季报预增').click()
    page.wait_for_selector('.member-panel tbody tr', timeout=60000)
    page.wait_for_selector('.etf-row', timeout=60000)
    page.wait_for_function("[...document.querySelectorAll('.etf-row')].some(e=>e.title.includes('披露重仓重合'))", timeout=60000)
    visible_rows = page.locator('.board-top-panel').evaluate('''panel => {
      const box=panel.querySelector('.market-grid-scroll').getBoundingClientRect();
      return [...panel.querySelectorAll('tbody tr')].filter(r=>{const b=r.getBoundingClientRect();return b.top>=box.top && b.bottom<=box.bottom}).length;
    }''')
    assert visible_rows >= 6, visible_rows
    concepts_etfs = page.locator('.etf-rows').inner_text()
    page.screenshot(path=str(OUT / '02-concepts.png'), full_page=True)
    page.locator('.board-top-panel tbody tr').filter(has_text='MLCC概念').click()
    page.wait_for_function("document.querySelector('.member-panel')?.textContent.includes('暂无完全同名的行情映射')")
    assert page.locator('.member-panel tbody tr').count() == 0
    page.wait_for_function("[...document.querySelectorAll('.etf-row')].some(e=>e.title.includes('上位主题'))")
    page.screenshot(path=str(OUT / '03-concepts-unmapped.png'), full_page=True)

    page.get_by_role('tab', name='板块分析', exact=True).click()
    page.wait_for_selector('.board-heatmap button', timeout=60000)
    count = page.locator('.board-heatmap button').count()
    assert count > 400, count
    bounds = page.locator('.board-heatmap').bounding_box()
    market_bounds = page.locator('.market-page').bounding_box()
    assert bounds['height'] >= 440 and bounds['width'] > market_bounds['width'] * 0.9
    page.get_by_role('combobox', name='热力图面积').select_option('equal')
    assert page.locator('.board-heatmap button').count() >= count
    page.get_by_role('combobox', name='热力图颜色').select_option('net_ratio')
    page.get_by_role('combobox', name='热力图颜色').select_option('change_pct')
    page.get_by_role('combobox', name='热力图面积').select_option('amount')
    page.get_by_role('textbox', name='搜索热力图').fill('半导体')
    page.locator('.board-heatmap button').first.click()
    page.wait_for_function("document.querySelector('.member-panel .panel-head')?.textContent.includes('半导体')")
    page.wait_for_selector('.member-panel tbody tr', timeout=60000)
    page.get_by_role('textbox', name='搜索热力图').fill('')
    page.get_by_role('button', name='热力图全屏', exact=True).click()
    page.wait_for_function('!!document.fullscreenElement')
    page.screenshot(path=str(OUT / '04-heatmap-fullscreen.png'))
    page.get_by_role('button', name='退出热力图全屏', exact=True).click()
    page.wait_for_function('!document.fullscreenElement')
    page.screenshot(path=str(OUT / '05-analysis.png'), full_page=True)
    page.get_by_role('button', name='收起侧边栏', exact=True).click()
    page.wait_for_timeout(300)
    page.get_by_role('button', name='展开侧边栏', exact=True).click()
    page.wait_for_timeout(300)
    assert page.locator('.board-heatmap').bounding_box()['width'] > 900

    layouts = []
    for width, height, zoom in [(1366,768,1),(1920,1080,1),(1366,768,1.25),(390,844,1)]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(zoom)=>document.documentElement.style.zoom=String(zoom)', zoom)
        for tab in ['板块热点','最新概念','板块分析']:
            page.get_by_role('tab', name=tab, exact=True).click()
            page.wait_for_timeout(250)
            assert not page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'), (width,height,zoom,tab)
            layouts.append(dict(width=width,height=height,zoom=zoom,tab=tab,overflow=False))
        page.screenshot(path=str(OUT / f'layout-{width}-{zoom}.png'), full_page=True)
    page.evaluate('document.documentElement.style.zoom="1"')
    page.set_viewport_size({'width':1600,'height':1000})
    page.get_by_role('tab', name='板块增仓', exact=True).click()
    page.wait_for_selector('.layout-position .board-top-panel tbody tr',timeout=60000)
    assert '2日增仓' in page.locator('.board-top-panel thead').inner_text()
    page.screenshot(path=str(OUT / '06-position-live.png'), full_page=True)
    assert not errors, errors
    result = dict(errors=errors, visible_concept_rows=visible_rows, heatmap_boards=count, heatmap_bounds=bounds,
        concept_etfs=concepts_etfs, layouts=layouts, position_source_available=True)
    (OUT / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
