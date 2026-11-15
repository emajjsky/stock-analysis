"""独立8777测试服务：重现用户的运行中离开、返回、刷新、历史查看路径。"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright,expect


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8777');args=parser.parse_args()
    output=Path('docs/evidence/lab-workspaces-20261115');output.mkdir(parents=True,exist_ok=True)
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[];submitted=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:submitted.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/lab/jobs') else None)
        page.goto(args.url+'/#/discover');page.wait_for_load_state('networkidle')
        page.get_by_role('button',name='趋势＋风险过滤',exact=True).click()
        page.get_by_role('button',name='开始选股',exact=True).click()
        page.get_by_label('算法计算进度',exact=True).wait_for()
        job=page.request.get(args.url+'/api/v1/lab/jobs').json()['data'][0];jid=job['id']
        page.get_by_role('button',name='数据与设置',exact=True).click()
        page.get_by_role('button',name='查看算法计算进度',exact=True).wait_for()
        page.screenshot(path=str(output/'running-away.png'))
        page.get_by_role('button',name='发现',exact=True).click()
        page.get_by_label('算法计算进度',exact=True).wait_for();assert '均线趋势 / ATR' in page.locator('.lab-config-summary').inner_text()
        page.get_by_role('tab',name='个股分析',exact=False).click()
        page.get_by_label('搜索研究股票').fill('600519')
        page.locator('.lab-search-results button').filter(has_text='贵州茅台').click()
        page.get_by_role('tab',name='持续监测',exact=False).click()
        page.get_by_label('任务名称',exact=True).fill('独立监测草稿')
        page.reload();page.wait_for_load_state('networkidle')
        expect(page.get_by_label('任务名称',exact=True)).to_have_value('独立监测草稿')
        page.get_by_label('算法计算进度',exact=True).wait_for()
        page.get_by_role('tab',name='选股工作台',exact=False).click()
        assert page.request.get(args.url+'/api/v1/lab/jobs').json()['data'][0]['id']==jid
        page.screenshot(path=str(output/'running-restored.png'),full_page=True)
        expect(page.locator('.lab-result-summary')).to_have_attribute('data-run-id',jid,timeout=60000)
        assert len(submitted)==1,'切页/刷新不应重复提交计算'
        summary=page.locator('.lab-result-summary').inner_text();assert '5223' in summary
        assert page.locator('.lab-result').count()>0,'完成后候选必须直接展示'
        page.screenshot(path=str(output/'completed-candidates.png'),full_page=True)
        checks.append({'运行中离开设置页返回及刷新':True,'同一任务':jid,'提交次数':len(submitted),'完成结果':summary})
        # 切换页面后结果与筛选状态仍在。
        page.get_by_role('button',name='符合条件',exact=False).click()
        page.locator('.lab-result').first.get_by_role('button',name='查看依据',exact=True).click()
        first_name=page.locator('.lab-result').first.locator('.stock-link').inner_text()
        page.get_by_role('button',name='数据与设置',exact=True).click();page.get_by_role('button',name='发现',exact=True).click()
        page.locator('.lab-evidence').first.wait_for();assert first_name in page.locator('.lab-result').first.inner_text()
        page.get_by_role('tab',name='个股分析',exact=False).click()
        assert '贵州茅台' in page.locator('.lab-chosen').inner_text()
        page.get_by_role('button',name='分析这只股票',exact=True).click()
        expect(page.locator('.lab-result-summary')).to_have_attribute('data-run-id',submitted[-1]['request_id'],timeout=30000)
        assert '计算 1 只' in page.locator('.lab-result-summary').inner_text()
        page.get_by_role('button',name='全部 1',exact=True).click()
        assert '贵州茅台' in page.locator('.lab-result').first.inner_text()
        page.get_by_role('tab',name='选股工作台',exact=False).click()
        assert '5223' in page.locator('.lab-result-summary').inner_text()
        checks.append({'三场景的配置与结果独立':True,'展开依据返回仍在':True})
        # 实际历史按钮：不空白、不混成单股结果，恢复配置并定位结果。
        page.get_by_role('tab',name='运行记录',exact=False).click()
        record=page.locator('.lab-history .lab-task').filter(has_text='选股工作台').first
        record.get_by_role('button',name='查看结果',exact=True).click()
        expect(page.get_by_role('tab',name='选股工作台',exact=False)).to_have_attribute('aria-selected','true')
        assert '5223' in page.locator('.lab-result-summary').inner_text()
        box=page.locator('.lab-result-area').bounding_box();assert box and -20<=box['y']<page.viewport_size['height']
        assert '均线趋势 / ATR' in page.locator('.lab-config-summary').inner_text()
        checks.append({'查看历史恢复原条件并定位实际结果':True,'结果区域y':round(box['y'])})
        # 全部算法AND的零命中：明确完成和解释，查看全部仍有依据。
        page.get_by_role('button',name='展开配置',exact=True).click()
        for checkbox in page.locator('.algorithm-check input').all():checkbox.check()
        page.get_by_role('button',name='开始选股',exact=True).click()
        page.get_by_label('算法计算进度',exact=True).wait_for()
        page.get_by_label('算法计算进度',exact=True).wait_for(state='detached',timeout=60000)
        page.locator('.lab-no-candidates').wait_for();assert '没有股票满足' in page.locator('.lab-no-candidates').inner_text()
        page.screenshot(path=str(output/'zero-candidates.png'),full_page=True)
        page.get_by_role('button',name='查看全部结果与依据',exact=True).click()
        expect(page.locator('.lab-result')).to_have_count(50)
        checks.append({'零命中解释与全部结果可查看':True})
        # 有旧结果时再次运行并取消，不用半份结果替换它。
        old_time=page.locator('.lab-result-summary').inner_text()
        page.get_by_role('button',name='开始选股',exact=True).click();page.get_by_label('算法计算进度',exact=True).wait_for()
        assert old_time==page.locator('.lab-result-summary').inner_text()
        page.get_by_role('button',name='取消计算',exact=True).click()
        page.get_by_label('算法计算进度',exact=True).wait_for(state='detached',timeout=30000)
        assert old_time==page.locator('.lab-result-summary').inner_text()
        assert '已取消' in page.locator('.lab-job-outcome').inner_text()
        checks.append({'取消保留上一份完整结果':True})
        # 由实际结果带入监测，保存/暂停/恢复/编辑/删除。
        page.locator('.lab-result').first.get_by_role('button',name='查看依据',exact=True).click()
        page.locator('.lab-result').first.get_by_role('button',name='加入算法监测',exact=True).click()
        assert '独立监测草稿' not in page.locator('.lab-task-options').inner_text()
        task_name='交互验收监测 '+str(int(time.time()));page.get_by_label('任务名称',exact=True).fill(task_name)
        page.get_by_role('button',name='启用监测',exact=True).click()
        task=page.locator('.lab-monitor-list .lab-task').filter(has_text=task_name).first;task.wait_for()
        task.get_by_role('button',name='暂停',exact=True).click();task.get_by_role('button',name='恢复',exact=True).wait_for()
        task.get_by_role('button',name='恢复',exact=True).click();task.get_by_role('button',name='暂停',exact=True).wait_for()
        task.get_by_role('button',name='调整',exact=True).click();page.get_by_role('button',name='保存调整并重建基线',exact=True).click()
        task.get_by_role('button',name='删除',exact=True).click();task.wait_for(state='detached')
        checks.append({'结果带入监测及任务完整操作':True})
        page.get_by_role('tab',name='选股工作台',exact=False).click();page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(output/'mobile.png'),full_page=True)
        checks.append({'390px无横向溢出':True,'page_errors':errors});assert not errors
        (output/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(checks,ensure_ascii=False));browser.close()


if __name__=='__main__':main()
