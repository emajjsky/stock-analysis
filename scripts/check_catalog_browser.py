"""正式服务目录浏览回归；只读页面，不增删自选。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

OUT = Path('docs/evidence/catalog-cache-20261109')
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Users\Administrator\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe')
    page = browser.new_page(viewport={'width': 1600, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8765/#/market', wait_until='networkidle')
    expect(page.locator('.catalog-panel tbody tr')).to_have_count(100)
    expect(page.locator('.catalog-panel tbody')).to_contain_text('平安银行')
    page.screenshot(path=str(OUT / 'catalog-first.png'), full_page=True)
    page.get_by_role('button', name='下一页', exact=True).click()
    expect(page.locator('.catalog-panel .pagination')).to_contain_text('101')
    expect(page.locator('.catalog-panel tbody tr')).to_have_count(100)
    page.screenshot(path=str(OUT / 'catalog-page2.png'), full_page=True)
    page.reload(wait_until='networkidle')
    expect(page.locator('.catalog-panel tbody tr')).to_have_count(100)
    results = []
    for width, height in [(1366,768),(1600,900),(1920,1080)]:
        page.set_viewport_size({'width':width,'height':height})
        results.append({'viewport':[width,height], 'rows':page.locator('.catalog-panel tbody tr').count(),
            'first':page.locator('.catalog-panel tbody tr').first.inner_text(),
            'footer':page.locator('.catalog-panel .panel-foot').inner_text()})
    print(json.dumps({'errors':errors,'layouts':results}, ensure_ascii=False))
    (OUT / 'browser.json').write_text(json.dumps({'errors':errors,'layouts':results},ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors
    browser.close()
