"""对独立8776测试库执行页面验收；不连接正式8765用户库。"""
import json
import time
import sqlite3
from datetime import datetime,timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    out=Path('docs/evidence/algorithm-lab-20261115');out.mkdir(parents=True,exist_ok=True)
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8776/#/discover');page.wait_for_load_state('networkidle')
        start=time.monotonic();page.get_by_role('button',name='运行一次',exact=True).click()
        page.locator('.lab-result-summary').wait_for(timeout=60000)
        checks.append({'全目录计算':page.locator('.lab-result-summary').inner_text(),'seconds':round(time.monotonic()-start,2)})
        page.get_by_role('button',name='展开配置',exact=True).click()
        page.locator('.lab-config-row select').nth(1).select_option('custom')
        for code,name in [('600519','贵州茅台'),('000001','平安银行')]:
            page.get_by_label('搜索研究股票').fill(code)
            page.locator('.lab-search-results button').filter(has_text=name).first.click()
        page.get_by_role('button',name='运行一次',exact=True).click()
        page.wait_for_function("document.querySelector('.lab-result-summary')?.innerText.includes('计算 2 只')")
        assert page.locator('.lab-result').count()==2
        page.locator('.lab-result').first.get_by_role('button',name='查看依据',exact=True).click()
        page.get_by_role('button',name='Jev 决策分流',exact=True).click()
        page.locator('.lab-review').wait_for()
        assert 'JEV_API_KEY' in page.locator('.lab-review').inner_text()
        page.get_by_role('button',name='Agent 复核',exact=True).click()
        page.wait_for_function("document.querySelector('.lab-review')?.innerText.includes('尚未配置模型')")
        page.screenshot(path=str(out/'screening-results.png'),full_page=True)
        checks.append({'多算法个股依据与未配置模型':True})
        page.get_by_role('button',name='加入算法监测',exact=True).click()
        name='界面验收监测 '+str(int(time.time()))
        page.locator('.lab-task-options input:not([type])').first.fill(name)
        page.get_by_role('button',name='启用监测',exact=True).click()
        task=page.locator('.lab-task').filter(has_text=name).first;task.wait_for()
        task.get_by_role('button',name='暂停',exact=True).click()
        task.get_by_role('button',name='恢复',exact=True).wait_for()
        task.get_by_role('button',name='调整',exact=True).click()
        page.get_by_role('button',name='保存调整并重建基线',exact=True).click()
        task.get_by_role('button',name='暂停',exact=True).wait_for()
        page.screenshot(path=str(out/'monitor-tasks.png'),full_page=True)
        task.get_by_role('button',name='删除',exact=True).click();task.wait_for(state='detached')
        checks.append({'任务保存暂停恢复编辑删除':True})
        db=sqlite3.connect('.runtime/lab-browser-20261115.db')
        notice=dict(id='qa-notice',title='通知轮询验收',message='独立测试库通知',kind='ALGORITHM',security_id='LIVE.SH.600519',read=False,created_at=datetime.now(timezone.utc).isoformat())
        with db:db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)',('notification','qa-notice',json.dumps(notice)))
        page.locator('.unread-dot').wait_for(timeout=15000)
        page.get_by_role('button',name='打开通知中心',exact=True).click()
        page.get_by_text('通知轮询验收',exact=True).wait_for()
        page.get_by_role('button',name='关闭通知',exact=True).click()
        with db:db.execute("DELETE FROM documents WHERE kind='notification' AND id='qa-notice'")
        db.close();checks.append({'后台新通知自动进入通知中心':True})
        page.get_by_role('tab',name='运行记录',exact=True).click()
        page.locator('.lab-task').first.get_by_role('button',name='查看结果',exact=True).click()
        page.locator('.lab-result-summary').wait_for();assert page.locator('.lab-result').count()==2
        page.get_by_role('tab',name='个股分析',exact=True).click()
        page.get_by_label('搜索研究股票').fill('600519')
        page.locator('.lab-search-results button').filter(has_text='贵州茅台').first.click()
        page.get_by_role('button',name='运行一次',exact=True).click()
        page.wait_for_function("document.querySelector('.lab-result-summary')?.innerText.includes('计算 1 只')")
        page.locator('.stock-link').filter(has_text='贵州茅台').click()
        page.get_by_role('button',name='计算建议',exact=True).wait_for(timeout=30000)
        page.get_by_role('button',name='计算建议',exact=True).click()
        page.locator('.stock-algorithms .lab-result-summary').wait_for()
        assert page.locator('.stock-algorithms .lab-evidence-row').count()==2
        page.locator('.stock-algorithms').scroll_into_view_if_needed()
        page.screenshot(path=str(out/'stock-algorithms.png'),full_page=True)
        checks.append({'发现个股分析跳转及K线算法组件':True})
        page.goto('http://127.0.0.1:8776/#/discover');page.reload();page.wait_for_load_state('networkidle')
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('tab',name='选股工作台',exact=True).wait_for()
        page.wait_for_timeout(350)
        page.screenshot(path=str(out/'discover-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
        checks.append({'390px无横向溢出':True,'page_errors':errors});assert not errors,errors
        (out/'browser-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(checks,ensure_ascii=False));browser.close()


if __name__=='__main__':main()
