"""只读浏览器检查：短窗口、缩放等效视口和移动菜单中的设置入口。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/settings-navigation'
BASE = 'http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        for width, height in [(1536, 695), (1280, 720), (1093, 614),
                              (1440, 400), (1920, 1080), (390, 640), (667, 375)]:
            page = browser.new_page(viewport={'width': width, 'height': height}, locale='zh-CN')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.wait_for_load_state('networkidle')
            if width <= 760:
                page.get_by_role('button', name='展开导航', exact=True).click()
                page.wait_for_function("getComputedStyle(document.querySelector('.app-sidebar')).transform === 'none'")
            settings = page.locator('.sidebar-footer').get_by_role('button', name='数据与设置', exact=True)

            def check_button():
                bounds = settings.bounding_box()
                assert bounds and bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height, bounds
                assert settings.evaluate('''el => {
                    const r = el.getBoundingClientRect();
                    return el.contains(document.elementFromPoint(r.x+r.width/2, r.y+r.height/2));
                }'''), f'{width}x{height} 设置按钮被覆盖'

            check_button()
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            check_button()
            if width == 1536:
                page.screenshot(path=str(OUT / '01-short-window-navigation.png'))
            settings.click()
            expect(page.get_by_role('heading', name='数据与工作台设置', exact=True)).to_be_visible()
            expect(page).to_have_url(BASE + '/#/settings')
            if width <= 760:
                expect(page.get_by_role('button', name='展开导航', exact=True)).to_have_attribute('aria-expanded', 'false')
            page.get_by_label('沪深 A 股代码（以逗号、空格或换行分隔）').scroll_into_view_if_needed()
            expect(page.get_by_label('沪深 A 股代码（以逗号、空格或换行分隔）')).to_be_visible()
            code_input = page.locator('#sync-security-codes')
            sync_button = page.get_by_role('button', name='开始手动同步', exact=True)
            expect(sync_button).to_be_disabled()
            expect(page.locator('#sync-block-reason')).to_contain_text('请先输入')
            watch_option = page.locator('.sync-options input[value="watchlist"]')
            empty_watch = '（0）' in watch_option.locator('..').inner_text()
            watch_option.check()
            if empty_watch:
                expect(page.get_by_text('还没有真实来源自选股', exact=True)).to_be_visible()
                expect(sync_button).to_be_disabled()
                expect(page.locator('#sync-block-reason')).to_contain_text('0 只')
                page.get_by_role('button', name='改为输入股票代码', exact=True).click()
                expect(code_input).to_be_focused()
            else:
                page.locator('.sync-options input[value="codes"]').check()
            code_input.fill('600519, 000001')
            expect(sync_button).to_be_enabled()
            page.get_by_label('同步未复权已完成日线', exact=True).check()
            expect(sync_button).to_be_enabled()
            code_input.fill('600519,000001,600000,000002,300750,601318')
            expect(sync_button).to_be_disabled()
            expect(page.locator('#sync-block-reason')).to_contain_text('最多同步 5 只')
            code_input.fill('bad')
            expect(sync_button).to_be_disabled()
            expect(page.locator('#sync-block-reason')).to_contain_text('股票代码有误')
            code_input.fill('600519, 000001')
            expect(sync_button).to_be_enabled()
            sync_button.scroll_into_view_if_needed()
            if width == 1536:
                page.screenshot(path=str(OUT / '02-settings-sync-entry.png'))
            page.reload()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('heading', name='数据与工作台设置', exact=True)).to_be_visible()
            cases.append({'width': width, 'height': height, 'settings_visible': True,
                          'settings_click_and_reload': True, 'sync_input_accessible': True,
                          'empty_watch_recovery': empty_watch, 'sync_form_gates_checked': True})
            page.close()
        browser.close()
    assert not errors, errors
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'service': BASE,
              'cases': cases, 'page_errors': errors,
              'data_sync_triggered': False, 'business_data_modified': False}
    (OUT / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
