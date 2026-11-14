"""正式8765两只故障股分时恢复、来源标识及真实重试请求验收。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/intraday-source-recovery'
BASE='http://127.0.0.1:8765'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    results={'errors':[],'stocks':[],'retry_requests':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page=browser.new_page(viewport={'width':1700,'height':1250},locale='zh-CN')
        page.on('pageerror',lambda e:results['errors'].append(str(e)))
        for key,name in [('LIVE.SH.688066','*ST航图'),('LIVE.SZ.301015','百洋医药')]:
            if not results['stocks']:
                page.goto(BASE+'/#/stock/'+key);page.wait_for_load_state('networkidle')
            else:
                page.locator('.global-search input').fill(key.split('.')[-1])
                page.get_by_role('option').filter(has_text=name).click()
            expect(page.locator('main h1')).to_contain_text(name)
            expect(page.locator('[aria-label="分时与成交量图"]')).to_be_visible(timeout=20000)
            expect(page.locator('.intraday-source')).to_have_text('东方财富公开分时（备用）')
            expect(page.locator('.intraday-source')).to_have_attribute('title','腾讯分时来源返回 HTTP 501')
            expect(page.locator('.error-box')).to_have_count(0)
            expect(page.locator('.chart-legend')).not_to_contain_text('—')
            page.screenshot(path=str(OUT/(key.replace('.','-')+'.png')),full_page=True)
            results['stocks'].append({'id':key,'name':name,'chart':True,'source':page.locator('.intraday-source').inner_text()})

        # 独立浏览器模拟双源暂不可用，无数据不可宣称保留分时缓存。
        real=page.request.get(BASE+'/api/v1/market/intraday?security_id=LIVE.SZ.301015').json()
        state={'failed':True}
        def intraday(route):
            if not state['failed']:return route.fulfill(json=real)
            route.fulfill(json={'data':{**real['data'],'points':[],'error':'腾讯分时来源返回 HTTP 501；东方财富分时来源暂不可用'},'meta':{}})
        def refresh(route):
            results['retry_requests'].append(route.request.url)
            state['failed']=False
            route.fulfill(json={'data':{'enabled':True,'running':False},'meta':{}})
        page.route('**/api/v1/market/intraday?*',intraday)
        page.route('**/api/v1/market/refresh?security_id=*',refresh)
        page.reload();page.wait_for_load_state('networkidle')
        expect(page.locator('.error-box')).to_contain_text('尚未取得可用分时数据')
        expect(page.locator('.error-box')).not_to_contain_text('已保留缓存')
        page.locator('.error-box').get_by_role('button',name='重试',exact=True).click()
        expect(page.locator('[aria-label="分时与成交量图"]')).to_be_visible(timeout=10000)
        expect(page.locator('.error-box')).to_have_count(0)
        assert len(results['retry_requests'])==1 and 'LIVE.SZ.301015' in results['retry_requests'][0]
        results['retry_recovers_empty_chart']=True
        assert not results['errors'],results['errors']
        browser.close()
    (OUT/'ui-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main()
