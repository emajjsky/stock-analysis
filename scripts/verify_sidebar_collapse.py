"""验证王炸品牌、图标侧栏、中文提示、宽度与移动抽屉；不写业务数据。"""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE='http://127.0.0.1:8765'
OUT=Path(__file__).resolve().parents[1]/'docs/evidence/sidebar-collapse'
LABELS=['首页','发现','市场','自选','信号','验证','交易','算法与规则','数据与设置']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='msedge')
        page=browser.new_page(viewport={'width':1600,'height':1000},locale='zh-CN')
        page.on('pageerror',lambda error:errors.append(str(error)))
        watches=page.request.get(BASE+'/api/v1/watchlists').json()['data']
        before=[(w['id'],w['security_id'],w['monitor_enabled']) for w in watches]
        page.goto(BASE+'/#/watch',wait_until='networkidle')
        expect(page).to_have_title('王炸 · A股分析工作台')
        expect(page.locator('.brand-name')).to_have_text('王炸')
        expect(page.locator('.brand-symbol')).to_have_text('股')
        sidebar=page.locator('.app-sidebar')
        for text in ['股研','LAB','A 股智能分析工作台','你的研究工作区','指数与行情','行情与关注','LOCAL WORKSPACE','KEEP YOUR EDGE']:
            assert text not in sidebar.inner_text(),text
        assert sidebar.locator('small').count()==0
        expect(page.locator('.mobile-nav-close')).to_be_hidden()
        brand=page.locator('.brand').bounding_box()
        toggle=page.get_by_label('收起侧边栏',exact=True).bounding_box()
        assert toggle['x']>=brand['x']+brand['width']
        assert abs(toggle['y']+toggle['height']/2-brand['y']-brand['height']/2)<2
        expect(page.locator('.watch-detail canvas').first).to_be_visible(timeout=15000)
        page.screenshot(path=str(OUT/'expanded-1600.png'),full_page=True)
        gains={}
        for width,height in [(2048,1080),(1920,1080),(1600,1000),(1366,900),(1093,720),(761,620)]:
            page.set_viewport_size({'width':width,'height':height})
            expect(page.get_by_label('收起侧边栏',exact=True)).to_be_visible()
            old=page.locator('.app-body').bounding_box()['width']
            old_content=page.locator('main').bounding_box()['width']
            page.get_by_label('收起侧边栏',exact=True).click()
            assert sidebar.bounding_box()['width']==80
            new=page.locator('.app-body').bounding_box()['width']
            gains[width]=round(new-old)
            assert gains[width]>=110,(width,gains)
            assert page.locator('main').bounding_box()['width']-old_content>=110,width
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            expect(page.locator('.brand-name')).to_be_hidden()
            for label in LABELS:
                button=sidebar.get_by_role('button',name=label,exact=True)
                expect(button.locator('.nav-label')).to_be_hidden()
                button.hover()
                expect(page.get_by_role('tooltip')).to_have_text(label)
                bounds=page.get_by_role('tooltip').bounding_box()
                assert bounds['x']>=70 and bounds['x']+bounds['width']<=width,(label,bounds)
            sidebar.get_by_role('button',name='自选',exact=True).focus()
            expect(page.get_by_role('tooltip')).to_have_text('自选')
            page.keyboard.press('Escape')
            expect(page.get_by_role('tooltip')).to_have_count(0)
            if width>=1366:
                sidebar.get_by_role('button',name='自选',exact=True).hover()
                page.screenshot(path=str(OUT/f'collapsed-{width}.png'),full_page=True)
            page.get_by_label('展开侧边栏',exact=True).click()
            expect(page.locator('.brand-name')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        page.set_viewport_size({'width':1600,'height':1000})
        page.get_by_label('收起侧边栏',exact=True).click()
        sidebar.get_by_role('button',name='数据与设置',exact=True).click()
        expect(page.locator('.breadcrumb')).to_contain_text('数据与设置')
        assert sidebar.bounding_box()['width']==80
        sidebar.get_by_role('button',name='自选',exact=True).click()
        expect(page.locator('.watchlist-table')).to_be_visible()
        page.reload(wait_until='networkidle')
        expect(page.get_by_label('展开侧边栏',exact=True)).to_be_visible()
        assert sidebar.bounding_box()['width']==80
        sidebar.get_by_role('button',name='算法与规则',exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)

        # 记住桌面收起偏好时，手机依然显示完整中文抽屉。
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('.app-body').bounding_box()['x']==0
        page.get_by_label('展开导航',exact=True).click()
        page.wait_for_timeout(200)
        expect(page.locator('.brand-name')).to_be_visible()
        expect(page.locator('.sidebar-toggle')).to_be_hidden()
        expect(page.get_by_label('关闭导航',exact=True)).to_be_visible()
        assert sidebar.bounding_box()['x']>=-1
        for label in LABELS:
            expect(sidebar.get_by_role('button',name=label,exact=True).locator('.nav-label')).to_be_visible()
        page.screenshot(path=str(OUT/'mobile-open.png'),full_page=True)
        page.get_by_label('关闭导航',exact=True).click()
        page.wait_for_timeout(200)
        assert sidebar.bounding_box()['x']+sidebar.bounding_box()['width']<=1
        page.get_by_label('展开导航',exact=True).click()
        page.wait_for_timeout(200)
        sidebar.get_by_role('button',name='首页',exact=True).click()
        expect(page.get_by_label('展开导航',exact=True)).to_have_attribute('aria-expanded','false')
        page.get_by_label('展开导航',exact=True).click()
        page.wait_for_timeout(200)
        page.get_by_label('关闭导航遮罩',exact=True).click(position={'x':350,'y':400})
        expect(page.get_by_label('展开导航',exact=True)).to_have_attribute('aria-expanded','false')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.set_viewport_size({'width':1366,'height':900})
        expect(page.get_by_label('展开侧边栏',exact=True)).to_be_visible()
        assert sidebar.bounding_box()['width']==80
        page.get_by_label('展开侧边栏',exact=True).click()
        page.reload(wait_until='networkidle')
        expect(page.get_by_label('收起侧边栏',exact=True)).to_be_visible()
        after=page.request.get(BASE+'/api/v1/watchlists').json()['data']
        assert before==[(w['id'],w['security_id'],w['monitor_enabled']) for w in after]
        assert not errors,errors
        result=dict(brand='王炸',stock_logo_retained=True,secondary_labels_removed=True,
                    collapsed_width=80,content_width_gains=gains,tooltip_labels=LABELS,
                    keyboard_tooltips=True,collapse_persists_after_reload=True,expand_persists_after_reload=True,
                    settings_and_rules_work=True,mobile_full_labels=True,mobile_close_and_backdrop=True,
                    no_page_overflow=True,watchlist_records_unchanged=True,page_errors=errors)
        (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        browser.close()


if __name__=='__main__':
    main()
