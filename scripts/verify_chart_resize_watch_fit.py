"""验证侧栏切换不裁掉图表末端，并检查自选列完整性；不修改业务记录。"""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8765'
OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/chart-resize-watch-fit'


def sidebar(page, collapsed):
    label = '收起侧边栏' if collapsed else '展开侧边栏'
    button = page.get_by_label(label, exact=True)
    if button.is_visible():
        button.click()
    page.wait_for_timeout(180)


def chart_edges(page):
    chart = page.locator('.index-panel .stock-chart')
    chart.scroll_into_view_if_needed()
    # lightweight-charts第一行中间单元格是主图绘图区，排除左右价格轴。
    bounds = chart.locator('table tr').first.locator('td').nth(1).bounding_box()
    values = []
    for x in [bounds['x'] + 1, bounds['x'] + bounds['width'] - 3]:
        page.mouse.move(x, bounds['y'] + 80)
        page.wait_for_timeout(80)
        values.append(page.locator('.index-panel .chart-date').first.inner_text())
    return values


def minutes(text):
    hour, minute = map(int, text.split(':'))
    return hour * 60 + minute


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result, errors = {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width':1600, 'height':1000}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        before = page.request.get(BASE + '/api/v1/watchlists').json()['data']
        page.goto(BASE, wait_until='networkidle')
        expect(page.locator('.index-panel .stock-chart canvas').first).to_be_visible()
        initial = chart_edges(page)
        assert initial == ['09:30', '15:00'], initial
        result['intraday_full'] = []
        for width in [1600, 1920, 1366]:
            page.set_viewport_size({'width':width, 'height':1000})
            for _ in range(2):
                for collapsed in [True, False]:
                    sidebar(page, collapsed)
                    edges = chart_edges(page)
                    assert edges[-1] == initial[-1] and abs(minutes(edges[0])-minutes(initial[0])) <= 1, (width, collapsed, edges)
                    result['intraday_full'].append({'width':width, 'collapsed':collapsed, 'edges':edges})
        page.set_viewport_size({'width':1600, 'height':1000})
        page.mouse.move(10, 10)
        expect(page.locator('.index-panel .chart-date').first).to_have_text('15:00')
        page.locator('.index-panel').screenshot(path=str(OUT / 'home-full-after-toggle.png'))

        # 用户主动放大并拖到历史后，改变侧栏不能重置成全览或强制跳到最新。
        bounds = page.locator('.index-panel .stock-chart table tr').first.locator('td').nth(1).bounding_box()
        x, y = bounds['x'] + bounds['width'] * .55, bounds['y'] + 100
        page.mouse.move(x, y)
        page.mouse.wheel(0, -550)
        page.wait_for_timeout(250)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 200, y, steps=12)
        page.mouse.up()
        page.wait_for_timeout(400)
        historical = chart_edges(page)
        assert historical != initial and historical[-1] != '15:00', historical
        result['intraday_history'] = {'before':historical, 'after':[]}
        for collapsed in [True, False, True, False]:
            sidebar(page, collapsed)
            edges = chart_edges(page)
            assert all(abs(minutes(a) - minutes(b)) <= 1 for a,b in zip(edges, historical)), (historical, edges)
            result['intraday_history']['after'].append(edges)
        page.locator('.index-panel').screenshot(path=str(OUT / 'home-history-after-toggle.png'))

        result['candles'] = {}
        for label in ['日 K', '周 K', '月 K']:
            page.locator('.index-panel .chart-toolbar').get_by_role('button', name=label, exact=True).click()
            expect(page.locator('.chart-ranges')).to_be_visible()
            page.wait_for_timeout(250)
            edges = chart_edges(page)
            sidebar(page, True)
            sidebar(page, False)
            after = chart_edges(page)
            assert edges == after, (label, edges, after)
            result['candles'][label] = after

        page.locator('.app-sidebar').get_by_role('button', name='自选', exact=True).click()
        expect(page.locator('.watchlist-table')).to_be_visible()
        expect(page.locator('.watch-detail canvas').first).to_be_visible(timeout=15000)
        result['watch_sizes'] = []
        for width in [2048, 1920, 1600, 1536, 1366, 1280, 1093]:
            page.set_viewport_size({'width':width, 'height':1000})
            for collapsed in [False, True]:
                sidebar(page, collapsed)
                metrics = page.locator('.watchlist-layout').evaluate('''el=>{
                    const scroll=el.querySelector('.watchlist-table-scroll');
                    const table=el.querySelector('table');
                    const left=el.querySelector('.watchlist-table-panel').getBoundingClientRect();
                    const right=el.querySelector('.watch-detail').getBoundingClientRect();
                    const last=table.querySelector('th[data-column=amplitude]').getBoundingClientRect();
                    return {client:scroll.clientWidth, scroll:scroll.scrollWidth,
                        columns:table.querySelectorAll('th[data-column]').length,
                        lastVisible:last.right<=scroll.getBoundingClientRect().right+1,
                        sideBySide:Math.abs(left.top-right.top)<1,
                        aligned:Math.abs(left.bottom-right.bottom)<2,
                        font:getComputedStyle(table.querySelector('.quote-price')).fontSize,
                        pageOverflow:document.documentElement.scrollWidth>innerWidth};
                }''')
                assert metrics['columns'] == 10 and metrics['font'] == '16px', metrics
                assert not metrics['pageOverflow'], metrics
                if width >= 1280 or collapsed:
                    assert metrics['scroll'] <= metrics['client'] + 1 and metrics['lastVisible'], (width, collapsed, metrics)
                if metrics['sideBySide']:
                    assert metrics['aligned'], metrics
                result['watch_sizes'].append({'width':width, 'collapsed':collapsed, **metrics})
                if width in [1600,1366]:
                    page.screenshot(path=str(OUT / f'watch-{width}-{"collapsed" if collapsed else "expanded"}.png'), full_page=True)

        page.set_viewport_size({'width':1600, 'height':1000})
        sidebar(page, False)
        # 压缩间距后数字也不得互相覆盖，忽略名称的合法省略号。
        overflow = page.locator('.watchlist-table tbody td:not(.watch-name):not(.watch-remove)').evaluate_all('''cells=>cells.flatMap(td=>{
            const r=document.createRange();r.selectNodeContents(td);
            const text=r.getBoundingClientRect(), box=td.getBoundingClientRect();
            return text.width && (text.left<box.left+2 || text.right>box.right-2)
                ? [{column:td.dataset.column, value:td.textContent, width:box.width, textWidth:text.width}] : [];
        })''')
        assert not overflow, overflow
        # 开关右侧详情时隐藏画布不应用0宽度，恢复后仍有完整图表。
        for _ in range(2):
            page.get_by_label('收起右侧详情', exact=True).click()
            expect(page.locator('.watch-detail')).to_be_hidden()
            page.get_by_label('展开右侧详情', exact=True).click()
            expect(page.locator('.watch-detail canvas').first).to_be_visible()
            page.wait_for_timeout(200)
            assert page.locator('.watch-detail .stock-chart').evaluate('el=>Math.abs(el.clientWidth-el.querySelector("table").getBoundingClientRect().width)<3')
        page.locator('th[data-column=change_pct] button').click()
        expect(page.locator('th[data-column=change_pct]')).to_have_attribute('aria-sort','descending')
        page.get_by_label('列设置', exact=True).click()
        page.get_by_role('checkbox', name='报价时间', exact=True).check()
        page.keyboard.press('Escape')
        expect(page.locator('th[data-column=time]')).to_have_count(1)
        page.get_by_label('列设置', exact=True).click()
        page.get_by_role('checkbox', name='报价时间', exact=True).uncheck()
        page.keyboard.press('Escape')
        # 额外全部指标仍能选择、滚动和使用固定名称代码，不能以裁切实现无滚动。
        page.get_by_label('列设置', exact=True).click()
        for checkbox in page.get_by_role('checkbox').all():
            if checkbox.is_enabled():
                checkbox.check()
        page.keyboard.press('Escape')
        expect(page.locator('th[data-column]')).to_have_count(19)
        page.locator('.watchlist-table-scroll').evaluate('el=>el.scrollLeft=el.scrollWidth')
        expect(page.locator('th[data-column=time]')).to_be_in_viewport()
        fixed = page.locator('.watchlist-table-scroll').evaluate('''el=>{
            const name=el.querySelector('tbody .watch-name').getBoundingClientRect();
            const code=el.querySelector('tbody .watch-code').getBoundingClientRect();
            return Math.abs(name.left-el.getBoundingClientRect().left)<2 && Math.abs(name.right-code.left)<2;
        }''')
        assert fixed
        result['extra_columns_and_sticky'] = True
        after = page.request.get(BASE + '/api/v1/watchlists').json()['data']
        identity = lambda items:[(w['id'],w['security_id'],w['monitor_enabled']) for w in items]
        assert identity(before) == identity(after)
        assert not errors, errors
        result['unchanged_watchlist'] = True
        result['page_errors'] = errors
        browser.close()
    (OUT / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
