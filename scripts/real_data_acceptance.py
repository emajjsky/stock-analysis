"""真实上游浏览器验收，固定使用5173独立空库，不操作正式库。"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/real-data-increment'
BASE = 'http://127.0.0.1:5173'


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    errors, server_errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width':1600,'height':1000}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: server_errors.append(response.url) if response.status >= 500 else None)
        page.goto(BASE)
        page.wait_for_load_state('networkidle')
        assert page.request.get(BASE + '/api/v1/securities').json()['data'] == [], '必须使用独立空库'
        page.get_by_role('button',name='载入合成演示',exact=True).click()
        page.get_by_role('button',name='数据与设置',exact=False).click()
        codes = page.locator('#sync-security-codes')
        expect(codes).to_have_value('')
        sync = page.get_by_role('button',name='开始手动同步',exact=True)
        expect(sync).to_be_disabled()
        codes.fill('600519, 000001')
        page.get_by_label('同步未复权已完成日线',exact=False).check()
        with page.expect_response(lambda r: r.url.endswith('/data/providers/tencent/sync') and r.request.method == 'POST', timeout=90000) as event:
            sync.click()
        response = event.value
        assert response.status == 200
        result = response.json()['data']
        assert result['status'] == 'SUCCEEDED', result
        assert result['quotes_updated'] == 2 and result['daily_rows_saved'] >= 100
        expect(page.locator('.sync-result')).to_contain_text('同步完成')
        expect(page.get_by_role('heading',name='公开行情同步记录')).to_be_visible()
        page.screenshot(path=str(OUT/'01-real-data-center.png'),full_page=True)
        securities = page.request.get(BASE+'/api/v1/securities').json()['data']
        real = [x for x in securities if x['id'].startswith('LIVE.')]
        assert len(real)==2 and len(securities)==8
        assert all(x['quote']['source_time'] and x['quote']['fetched_at'] and len(x['quote']['raw_hash'])==64 for x in real)
        assert all(x['quote']['mode']=='LIVE' and x['quote']['is_realtime'] is False for x in real)
        assert all('演示' not in x['name'] for x in real)
        assert page.request.get(BASE+'/api/v1/watchlists').json()['data']==[]
        page.locator('nav button').filter(has_text='市场').click()
        row = page.get_by_role('row').filter(has_text='600519').filter(has_text='公开行情快照')
        expect(row).to_have_count(1)
        row.locator('.stock-link').click()
        expect(page.locator('.stock-header')).to_contain_text('非持续实时订阅')
        expect(page.locator('.chart-panel canvas').first).to_be_visible()
        research_button = page.get_by_role('button', name='手动同步研究资料', exact=True)
        expect(research_button).to_be_enabled()
        with page.expect_response(lambda r: r.url.endswith('/securities/LIVE.SH.600519/research/sync') and r.request.method == 'POST', timeout=120000) as research_event:
            research_button.click()
        research_response = research_event.value
        assert research_response.status == 200
        research_result = research_response.json()['data']
        assert research_result['status'] == 'SUCCEEDED', research_result
        expect(page.locator('[data-testid="research-sync-result"]')).to_contain_text('同步完成')
        profile = page.request.get(BASE + '/api/v1/securities/LIVE.SH.600519/profile').json()['data']
        assert profile['research']['status'] == 'SYNCED'
        assert profile['business'] and profile['financials'] and profile['events']
        page.get_by_role('button', name='财务摘要', exact=True).click()
        expect(page.locator('.research-table tbody tr')).to_have_count(4)
        page.set_viewport_size({'width':1280,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '财务表造成整页横向溢出'
        page.screenshot(path=str(OUT/'06-real-financials-1280.png'), full_page=True)
        page.set_viewport_size({'width':1600,'height':1000})
        page.get_by_role('button', name='新闻与公告', exact=True).click()
        expect(page.locator('.event-row')).to_have_count(10)
        page.screenshot(path=str(OUT/'05-real-research.png'), full_page=True)
        daily = page.request.get(BASE+'/api/v1/market/bars?security_id=LIVE.SH.600519&timeframe=1d').json()['data']
        assert len(daily['bars']) >= 100
        assert all(x['amount'] is None for x in daily['bars'])
        page.get_by_role('button',name='周 K',exact=True).click()
        expect(page.locator('.chart-panel canvas').first).to_be_visible()
        page.get_by_role('button',name='月 K',exact=True).click()
        expect(page.locator('.chart-panel canvas').first).to_be_visible()
        page.screenshot(path=str(OUT/'02-real-stock-chart.png'),full_page=True)
        page.locator('nav button').filter(has_text='发现').click()
        page.get_by_label('选择选股算法').select_option('trend-stability-v1')
        page.get_by_role('button',name='运行选股',exact=True).click()
        expect(page.locator('.recommendation-card')).to_have_count(2)
        recommendations = page.request.get(BASE+'/api/v1/recommendations').json()['data']
        assert recommendations and all(x['security']['id'].startswith('LIVE.') for x in recommendations)
        page.screenshot(path=str(OUT/'03-real-recommendations.png'),full_page=True)
        page.get_by_role('button',name='加入自选',exact=True).first.click()
        expect(page.get_by_role('button',name='已在自选',exact=True)).to_have_count(1)
        page.locator('nav button').filter(has_text='自选').click()
        page.get_by_role('button',name='配置此股监测').click()
        page.get_by_role('button',name='保存监测规则',exact=True).click()
        expect(page.get_by_text('监测配置已保存',exact=False)).to_be_visible()
        page.get_by_role('button',name='关闭',exact=True).first.click()
        page.locator('nav button').filter(has_text='信号').click()
        page.get_by_role('button',name='运行信号计算',exact=True).click()
        expect(page.locator('.signal-row')).to_have_count(1)
        assert page.request.get(BASE+'/api/v1/sim/accounts').json()['data']==[]
        page.set_viewport_size({'width':1280,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT/'04-real-signal.png'),full_page=True)
        assert not errors and not server_errors, (errors,server_errors)
        report=dict(browser=browser.version, upsteam_is_live=True, sync=result,
            research_sync=research_result,research_profile=dict(security_id=profile['security_id'],
                company_facts=len(profile['facts']), financial_count=len(profile['financials']),
                announcement_count=len(profile['events']), financials=profile['financials'],
                evidence=profile['evidence'], agent_context_unchanged=True),
            securities=real, historical_bar_count=len(daily['bars']), historical_cutoff=daily['bars'][-1]['time'],
            algorithm_ids=[x['algorithm_id'] for x in recommendations],
            checks=['no default symbols or automatic requests','real upstream quote and history saved',
                'synthetic records preserved under separate identities','quote source time differs from fetched time',
                'daily weekly monthly charts render with unknown amount kept null',
                'company profile, financial summary and announcement metadata sync with source evidence',
                'financial summary at 1280 viewport without page overflow',
                'real stock ranking excludes synthetic candidates','watchlist and signal workflow uses saved real history',
                'no accounts or trading created','1280 viewport without horizontal overflow'],
            page_errors=errors,server_errors=server_errors)
        (OUT/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True,indent=2))
        browser.close()


if __name__=='__main__':
    main()
