"""现有8765的真实资讯与双栏验收；异常/阅读位置使用独立浏览器夹具。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/market-news'
BASE = 'http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = dict(real=[], fixtures=[], errors=[])
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport=dict(width=1920, height=1080), locale='zh-CN')
        page.on('pageerror', lambda e: results['errors'].append(str(e)))
        page.goto(BASE)
        page.wait_for_load_state('networkidle')
        news = page.get_by_role('region', name='资讯列表', exact=True)
        expect(news.locator('.news-item').first).to_be_visible(timeout=35000)
        for width, height in [(1920,1080), (1600,900), (1366,768), (1093,614), (390,760)]:
            page.set_viewport_size(dict(width=width, height=height))
            page.locator('.market-lower-grid').scroll_into_view_if_needed()
            ranking = page.get_by_role('region', name='市场排行榜', exact=True)
            dims = page.locator('.market-lower-grid').evaluate('e=>{const a=e.children[0].getBoundingClientRect(),b=e.children[1].getBoundingClientRect();return {left:{x:a.x,y:a.y,w:a.width,h:a.height},right:{x:b.x,y:b.y,w:b.width,h:b.height},overflow:document.documentElement.scrollWidth>innerWidth}}')
            assert not dims['overflow'], dims
            if width >= 1280:
                assert dims['right']['x'] > dims['left']['x'] and abs(dims['left']['y']-dims['right']['y']) < 2, dims
                assert abs(dims['left']['h']-dims['right']['h']) < 2, dims
            else:
                assert dims['right']['y'] > dims['left']['y'], dims
            assert ranking.locator('td.numeric').first.evaluate('e=>getComputedStyle(e).fontSize') == '16px'
            assert news.locator('.news-title').first.evaluate('e=>getComputedStyle(e).fontSize') == '16px'
            if width == 1920:
                page.locator('.market-lower-grid').screenshot(path=str(OUT/'01-live-dual-1920.png'))
            if width == 1366:
                page.locator('.market-lower-grid').screenshot(path=str(OUT/'02-live-dual-1366.png'))
            results['real'].append(dict(width=width,height=height,**dims))
        page.set_viewport_size(dict(width=1600,height=1000))
        page.locator('.news-panel').scroll_into_view_if_needed()
        expect(news.locator('.news-item')).to_have_count(100, timeout=30000)
        news.locator('.news-title').first.click()
        expect(news.locator('.news-detail').first).to_be_visible()
        anchor=news.locator('.news-detail a').first
        if anchor.count():
            assert anchor.get_attribute('href').startswith('https://finance.sina.com.cn/')
        page.locator('.news-panel').get_by_role('button',name='公司公告',exact=True).click()
        expect(news.locator('.news-kind').first).to_be_visible(timeout=30000)
        expect(news.locator('.news-meta time').first).to_have_text(__import__('re').compile(r'^\d{2}/\d{2}$'))
        page.locator('.news-panel').get_by_role('button',name='自选相关',exact=True).click()
        watch_data=page.request.get(BASE+'/api/v1/market/news?tab=watch').json()['data']
        if watch_data['watch_count']:
            expect(news.locator('.news-item').first).to_be_visible(timeout=30000)
            watched={x['security_id'] for x in page.request.get(BASE+'/api/v1/watchlists').json()['data']}
            assert all(watched.intersection(s['id'] for s in x['securities']) for x in watch_data['items'])
        else:
            expect(news).to_contain_text('加入自选后', timeout=10000)
        # 选中榜单行只加载对应资讯，不进入个股，不更改自选。
        row=page.locator('.ranking-scroll tbody tr').first
        row.locator('td').nth(1).click()
        name=row.locator('.stock-link').inner_text()
        expect(news.locator('.news-context')).to_contain_text(name)
        expect(page.locator('.news-tabs button').last).to_have_attribute('aria-pressed','true')
        expect(news.locator('.news-item').first).to_be_visible(timeout=35000)
        for stock in news.locator('.news-securities button').all():
            assert name in stock.inner_text(), (name,stock.inner_text())
        page.locator('.news-panel').screenshot(path=str(OUT/'03-live-linked-announcements.png'))
        page.get_by_role('button',name='返回全部资讯',exact=True).click()
        expect(news.locator('.news-context')).to_have_count(0)
        expect(page.locator('.news-tabs button').first).to_have_attribute('aria-pressed','true')
        for region in (ranking,news):
            region.scroll_into_view_if_needed()
            region.evaluate('e=>e.scrollTop=e.scrollHeight')
            rect=region.bounding_box()
            page.mouse.move(rect['x']+rect['width']/2, max(140,rect['y']+150))
            before=page.evaluate('window.scrollY')
            other=news if region==ranking else ranking
            other_before=other.evaluate('e=>e.scrollTop')
            page.mouse.wheel(0,1000)
            page.wait_for_timeout(300)
            assert page.evaluate('window.scrollY') == before
            assert other.evaluate('e=>e.scrollTop') == other_before
        response=page.request.get(BASE+'/api/v1/market/news').json()
        assert response['data']['items'] and response['data']['updated_at']
        (OUT/'live-api.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
        results['real'].append(dict(case='真实快讯/公告/空自选/榜单联动/清除/滚动隔离',items=len(response['data']['items'])))

        # 新消息夹具：只拦截此独立页，源数据和正式数据库不写入。
        fixture=deepcopy(response)
        phase=[0]
        initial=deepcopy(fixture['data']['items'])
        new_item=deepcopy(initial[0])
        new_item.update(id='test:new',title='测试夹具：新的市场消息')
        def route_news(route):
            value=deepcopy(fixture)
            if phase[0]==1:
                value['data']['items']=[new_item]+initial
            elif phase[0]==2:
                value['data'].update(error='测试来源故障',status='ERROR')
            elif phase[0]==3:
                value['data'].update(items=[],error=None,status='READY')
            route.fulfill(json=value)
        test=browser.new_page(viewport=dict(width=1600,height=900),locale='zh-CN')
        test.on('pageerror',lambda e:results['errors'].append(str(e)))
        test.route('**/api/v1/market/news?*',route_news)
        test.goto(BASE)
        test.wait_for_load_state('networkidle')
        scroll=test.get_by_role('region',name='资讯列表',exact=True)
        scroll.scroll_into_view_if_needed()
        scroll.evaluate('e=>e.scrollTop=450')
        anchor_title=scroll.locator('.news-title').nth(8)
        before_y=anchor_title.bounding_box()['y']
        phase[0]=1
        expect(test.locator('.news-pending')).to_be_visible(timeout=16000)
        assert scroll.evaluate('e=>e.scrollTop') == 450
        after_y=anchor_title.bounding_box()['y']
        assert abs(after_y-before_y) < 2, (before_y,after_y)
        expect(scroll.locator('.news-title').first).not_to_contain_text('测试夹具')
        test.locator('.news-pending').click()
        expect(scroll.locator('.news-title').first).to_contain_text('测试夹具')
        assert scroll.evaluate('e=>e.scrollTop')==0
        phase[0]=2
        expect(scroll).to_contain_text('测试来源故障',timeout=16000)
        assert scroll.locator('.news-item').count()>0
        phase[0]=3
        test.locator('.news-tabs').get_by_role('button',name='公司公告',exact=True).click()
        expect(scroll).to_contain_text('暂无公司公告')
        results['fixtures'].append('页面自身轮询：阅读位置保留、新消息提示、点击后置顶更新、失败保留、空公告')
        browser.close()

    before=json.loads((ROOT/'.runtime/news-before.json').read_text(encoding='utf-8'))
    with sqlite3.connect(str(ROOT/'.local/workstation.db')) as db:
        kinds=before['kinds']
        rows=db.execute('select kind,id,payload from documents where kind in ('+','.join('?' for _ in kinds)+') order by kind,id',kinds).fetchall()
        bars=db.execute('select * from bars order by security_id,time').fetchall()
        assert hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()==before['documents_hash']
        assert hashlib.sha256(json.dumps(bars,ensure_ascii=False).encode()).hexdigest()==before['bars_hash']
    results['protected_data_unchanged']=True
    assert not results['errors'],results['errors']
    (OUT/'browser-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
