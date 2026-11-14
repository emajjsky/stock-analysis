"""对唯一8765正式服务执行板块页面验收；不添加自选，不触发算法或交易。"""
from pathlib import Path
import json

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/boards'
OUT.mkdir(parents=True, exist_ok=True)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
        executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    errors, refreshes = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda req: refreshes.append(req.url)
            if req.method == 'POST' and '/market/boards/refresh?' in req.url else None)
    page.goto('http://127.0.0.1:8765/#/market')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.board-ranking tbody tr', timeout=60000)
    counts = {'industry': page.locator('.board-ranking tbody tr').count()}
    page.locator('.board-search input').fill('种子')
    page.locator('.board-ranking tbody tr').first.click()
    page.wait_for_selector('.member-table tbody tr', timeout=60000)
    page.wait_for_function("[...document.querySelectorAll('.chart-panel')].every(e=>e.querySelector('canvas'))", timeout=60000)
    counts['seed_supported_members'] = page.locator('.member-table tbody tr').count()
    page.locator('.board-search input').fill('')
    page.get_by_role('button', name='刷新行情', exact=True).click()
    page.wait_for_function("!document.querySelector('[aria-label=刷新行情]').disabled")
    assert len(refreshes) == 1
    page.screenshot(path=str(OUT / 'hot-desktop.png'), full_page=True)

    page.get_by_role('button', name='收起侧边栏', exact=True).click()
    page.wait_for_timeout(500)
    assert page.locator('.chart-panel canvas').count() > 0
    page.get_by_role('button', name='展开侧边栏', exact=True).click()
    page.get_by_role('tab', name='板块分析', exact=True).click()
    page.wait_for_function("document.querySelectorAll('.board-heatmap button').length===40")
    page.screenshot(path=str(OUT / 'heat-desktop.png'), full_page=True)
    page.get_by_role('tab', name='板块资金', exact=True).click()
    page.wait_for_selector('.fund-day', timeout=60000)
    assert page.locator('.fund-day').count() == 20
    page.screenshot(path=str(OUT / 'funds-desktop.png'), full_page=True)
    page.get_by_role('tab', name='板块轮动', exact=True).click()
    page.wait_for_selector('.rotation-grid button', timeout=30000)
    page.screenshot(path=str(OUT / 'rotation-desktop.png'), full_page=True)

    page.get_by_role('button', name='概念', exact=True).click()
    page.get_by_role('tab', name='板块热点', exact=True).click()
    page.wait_for_selector('.board-ranking tbody tr', timeout=60000)
    counts['concept'] = page.locator('.board-ranking tbody tr').count()
    page.locator('.board-ranking th button').filter(has_text='成交额').click()
    for index in [3, 5, 2]:
        page.locator('.board-ranking tbody tr').nth(index).click()
    page.wait_for_selector('.member-table tbody tr', timeout=60000)
    selected = page.locator('.board-ranking tr.selected .board-name').inner_text()
    assert selected in page.locator('.board-right .chart-title').first.inner_text()
    page.locator('.chart-panel').first.get_by_role('button', name='日K', exact=True).click()
    page.locator('.chart-panel').first.locator('canvas').first.wait_for(timeout=60000)
    page.locator('.chart-panel').nth(1).get_by_role('button', name='日K', exact=True).click()
    page.locator('.chart-panel').nth(1).locator('canvas').first.wait_for(timeout=60000)
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / 'concept-daily.png'), full_page=True)
    layouts = []
    for width, height in [(1366, 900), (1920, 1080), (1100, 850), (390, 844)]:
        page.set_viewport_size({'width': width, 'height': height})
        page.wait_for_timeout(500)
        overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not overflow, width
        layouts.append({'width': width, 'height': height, 'page_horizontal_overflow': overflow})
        page.screenshot(path=str(OUT / f'layout-{width}.png'), full_page=True)
    page.set_viewport_size({'width': 1600, 'height': 1000})
    page.get_by_role('button', name='证券目录', exact=False).click()
    page.get_by_role('textbox', name='搜索证券', exact=True).fill('000001')
    page.wait_for_selector('.catalog-panel .stock-name-link', timeout=30000)
    assert '平安银行' in page.locator('.catalog-panel').inner_text()
    page.locator('.catalog-panel .stock-name-link').first.click()
    page.wait_for_url('**/#/stock/LIVE.SZ.000001')
    assert not errors, errors
    result = {'counts': counts, 'layouts': layouts, 'manual_refresh_posts': len(refreshes),
              'page_errors': errors, 'opened_stock_url': page.url,
              'checks': ['行业概念切换', '搜索与排序', '板块成分股联动', '分时及日K', '快速切换不串板块',
                         '热力图40板块', '20日资金', '已存交易日轮动', '手动刷新', '侧栏折叠展开', '目录搜索打开个股']}
    (OUT / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    browser.close()
