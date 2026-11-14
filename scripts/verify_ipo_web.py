"""正式8765新股页面的只读交互与截图验收；不加入自选，不运行算法。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path('docs/evidence/ipo-web')
OUT.mkdir(parents=True, exist_ok=True)
results, errors = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    context = browser.new_context(viewport={'width':1600,'height':1000}, device_scale_factor=1)
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/#/ipo')
    page.wait_for_load_state('networkidle')
    page.locator('.ipo-primary-table tbody tr').first.wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    assert page.locator('.ipo-navigation').bounding_box()['height'] < 70, '栏目导航未横向排列'
    assert page.locator('.ipo-primary-table').bounding_box()['y'] < 230
    assert page.get_by_role('navigation',name='主要功能').get_by_role('button',name='新股',exact=True).count()==1
    page.screenshot(path=str(OUT/'ipo-home-1600.png'))
    for label in ['新股申购','新股预披露','新股上会','打新收益','转债申购','科创板新股']:
        page.get_by_role('navigation',name='新股栏目').get_by_role('button',name=label,exact=True).click()
        page.locator('.ipo-primary-table tbody tr').first.wait_for(timeout=20000)
        assert not page.locator('.ipo-error').count(), (label,page.locator('.ipo-error').all_text_contents())
        page.screenshot(path=str(OUT/f'ipo-{label}-1600.png'))
        results.append({'tab':label,'rows':page.locator('.ipo-primary-table tbody tr').count(),
            'headers':page.locator('.ipo-primary-table th').all_text_contents()})
    page.get_by_role('navigation',name='新股栏目').get_by_role('button',name='新股申购',exact=True).click()
    page.get_by_role('navigation',name='新股市场').get_by_role('button',name='北交所',exact=True).click()
    page.locator('.ipo-primary-table tbody tr').first.wait_for(timeout=20000)
    page.get_by_role('textbox',name='筛选本页新股').fill('华晟')
    assert page.locator('.ipo-primary-table tbody tr').count()==1
    page.get_by_role('textbox',name='筛选本页新股').fill('')
    page.get_by_role('navigation',name='新股栏目').get_by_role('button',name='新股首页',exact=True).click()
    page.locator('.ipo-primary-table tbody tr').first.wait_for(timeout=20000)
    page.locator('.ipo-pending-table tbody tr').first.wait_for(timeout=20000)
    page.locator('.ipo-pending-table tbody tr').first.click()
    chosen = page.locator('.ipo-stock-name').inner_text()
    page.wait_for_timeout(6000)
    assert page.locator('.ipo-stock-name').inner_text()==chosen, '待上市选择被轮询重置'
    page.get_by_role('navigation',name='新股市场').get_by_role('button',name='全部A股',exact=True).click()
    page.locator('.ipo-primary-table tbody tr').first.wait_for(timeout=20000)
    for width in [1366,1920]:
        page.set_viewport_size({'width':width,'height':900})
        for collapsed in [False,True]:
            toggle=page.get_by_role('button',name='展开侧边栏' if collapsed else '收起侧边栏',exact=True)
            if toggle.count(): toggle.click()
            page.wait_for_timeout(300)
            layout=page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
                main:document.querySelector('.ipo-primary-table').getBoundingClientRect().bottom,
                aside:document.querySelector('.ipo-aside').getBoundingClientRect().bottom})''')
            assert layout['scroll'] <= width, layout
            assert layout['aside'] < 900, '主体内容超出屏幕'
            table=page.locator('.ipo-tables').bounding_box(); aside=page.locator('.ipo-aside').bounding_box()
            assert abs(table['y']+table['height']-aside['y']-aside['height'])<2,layout
            page.screenshot(path=str(OUT/f'ipo-home-{width}-{collapsed}.png'))
            results.append({'width':width,'collapsed':collapsed,'layout':layout})
    page.get_by_role('navigation',name='主要功能').get_by_role('button',name='网页行情',exact=True).click()
    page.get_by_role('heading',name='同花顺网页行情').wait_for()
    page.screenshot(path=str(OUT/'web-browser-mode.png'))
    assert not errors,errors
    browser.close()
(OUT/'ui-checks.json').write_text(json.dumps({'checks':results,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(results),'errors':errors},ensure_ascii=False))
