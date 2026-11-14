"""对单独空库测试服务运行；不清空数据，不连接外部供应商。

启动示例：WORKSTATION_DB指向全新的.runtime/browser-*.db后，运行本机服务。
依赖：pip install playwright；使用本机已安装的无头Edge。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
BASE = "http://127.0.0.1:8765"


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors, failed_responses, checks = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge")
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: failed_responses.append({"url": response.url, "status": response.status}) if response.status >= 500 else None)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        assert page.request.get(BASE + "/api/v1/securities").json()["data"] == [], "请使用单独的新建空库，禁止在用户库运行验收"
        expect(page.get_by_text("你的研究，从一份数据开始")).to_be_visible()
        page.screenshot(path=str(EVIDENCE / "01-empty.png"), full_page=True)
        checks.append("空库不含证券或账户，不强迫建模拟账户")
        page.get_by_role("button", name="载入合成演示", exact=True).click()
        expect(page.get_by_role("button", name="运行选股", exact=True)).to_be_enabled()
        page.get_by_role("button", name="运行选股", exact=True).click()
        expect(page.locator(".recommendation-card")).to_have_count(6)
        page.get_by_role("button", name="加入自选", exact=True).first.click()
        expect(page.get_by_role("button", name="已在自选", exact=True)).to_have_count(1)
        checks.append("显式演示→运行选股→加入自选")
        page.screenshot(path=str(EVIDENCE / "02-discovery.png"), full_page=True)

        def nav(text):
            page.locator("nav button").filter(has_text=text).click()

        nav("自选")
        expect(page.locator("tbody tr")).to_have_count(1)
        page.get_by_role("button", name="配置此股监测").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.get_by_role("button", name="保存监测规则", exact=True).click()
        expect(page.get_by_text("监测配置已保存", exact=False)).to_be_visible()
        page.get_by_role("button", name="关闭", exact=True).first.click()
        nav("信号")
        page.get_by_role("button", name="运行信号计算", exact=True).click()
        expect(page.locator(".signal-row")).to_have_count(1)
        page.get_by_role("button", name="请求复核", exact=True).click()
        expect(page.get_by_text("AI服务未配置", exact=False)).to_be_visible()
        page.get_by_role("button", name="显式体验规则复核演示（非 AI）", exact=True).click()
        expect(page.get_by_text("规则演示，非AI", exact=False)).to_be_visible()
        checks.append("自选→监测规则→信号→未配置WAIT→显式非AI规则演示")
        page.screenshot(path=str(EVIDENCE / "03-signal-review.png"), full_page=True)
        page.get_by_role("button", name="查看个股图表").click()
        expect(page.locator(".stock-chart canvas").first).to_be_visible()
        page.get_by_role("button", name="周 K", exact=True).click()
        expect(page.locator(".stock-chart canvas").first).to_be_visible()
        page.get_by_role("button", name="月 K", exact=True).click()
        expect(page.locator(".stock-chart canvas").first).to_be_visible()
        page.get_by_role("button", name="日 K", exact=True).click()
        page.screenshot(path=str(EVIDENCE / "04-stock-chart.png"), full_page=True)
        checks.append("成熟图表实际渲染、日周月切换")

        page.get_by_role("button", name="数据与设置", exact=True).click()
        page.locator('input[type="file"]').set_input_files(str(ROOT / "examples/history.csv"))
        page.get_by_role("button", name="校验并预览", exact=True).click()
        expect(page.get_by_text("有效 3 行", exact=True)).to_be_visible()
        page.get_by_role("button", name="确认导入并保存", exact=True).click()
        expect(page.get_by_role("button", name="已提交保存", exact=True)).to_be_disabled()
        assert len(page.request.get(BASE + "/api/v1/securities").json()["data"]) == 7
        checks.append("CSV选择→预览→事务提交，演示和导入并存")
        page.screenshot(path=str(EVIDENCE / "05-data-import.png"), full_page=True)

        nav("交易")
        expect(page.get_by_placeholder("由你设定，不预填资金")).to_have_value("")
        page.get_by_placeholder("例如：波段基线实验").fill("浏览器验收账户")
        page.get_by_placeholder("由你设定，不预填资金").fill("54321.09")
        page.get_by_role("button", name="创建模拟账户", exact=True).click()
        expect(page.locator(".environment-strip")).to_be_visible()
        page.locator(".order-form select").nth(0).select_option("DEMO.000001")
        page.locator(".order-form input").fill("200")
        page.get_by_role("button", name="提交模拟委托", exact=True).click()
        expect(page.locator(".trading-main tbody tr").first).to_contain_text("200 / 0")
        page.locator(".order-form select").nth(1).select_option("SELL")
        page.locator(".order-form input").fill("100")
        page.get_by_role("button", name="提交模拟委托", exact=True).click()
        expect(page.get_by_text("可卖库存不足", exact=False)).to_be_visible()
        page.get_by_role("button", name="推进演示交易日", exact=True).click()
        page.locator(".order-form select").nth(2).select_option("T")
        page.get_by_role("button", name="提交模拟委托", exact=True).click()
        expect(page.locator(".trading-main tbody tr").filter(has_text="已成交")).to_have_count(2)
        expect(page.get_by_role("button", name="提交模拟委托", exact=True)).to_be_enabled()
        page.locator(".order-form select").nth(1).select_option("BUY")
        expect(page.locator(".order-form select").nth(1)).to_have_value("BUY")
        page.get_by_role("button", name="提交模拟委托", exact=True).click()
        expect(page.get_by_text("今日实际盈亏", exact=True)).to_be_visible()
        expect(page.locator(".trading-main tbody tr").filter(has_text="已成交")).to_have_count(3)
        account = page.request.get(BASE + "/api/v1/sim/accounts").json()["data"][0]
        assert account["initial_cash"] == "54321.09"
        comparison = page.request.get(BASE + f"/api/v1/sim/accounts/{account['id']}").json()["data"]["comparison"]
        assert comparison["open_t_quantity"] == 0
        page.screenshot(path=str(EVIDENCE / "06-simulation.png"), full_page=True)
        checks.append("自定54321.09资金→底仓→T+1拒卖→推进→T卖出回补→今日及累计对照")
        page.get_by_role("button", name=re.compile("真实交易")).click()
        expect(page.get_by_role("button", name="连接实盘账户（未开放）", exact=True)).to_be_disabled()
        checks.append("实盘入口禁用")

        nav("验证")
        page.get_by_role("button", name="运行后验验证", exact=True).click()
        expect(page.get_by_text("五日后验信号事件研究", exact=True)).to_be_visible()
        page.get_by_role("button", name="打开通知中心").click()
        expect(page.get_by_role("heading", name=re.compile("通知中心"))).to_be_visible()
        page.get_by_role("button", name="标为已读", exact=True).first.click()
        page.get_by_role("button", name="关闭通知", exact=True).click()
        checks.append("后验待验证结果及通知已读保存")

        nav("发现")
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".recommendation-card")).to_have_count(6)
        checks.append("刷新恢复持久化推荐及自选")
        for width in (1366, 1600, 1920):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"页面在{width}宽度溢出"
            page.screenshot(path=str(EVIDENCE / f"layout-{width}.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 800})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "125%等效逻辑视口溢出"
        page.screenshot(path=str(EVIDENCE / "layout-125pct-equivalent.png"), full_page=True)
        checks.append("1366/1600/1920与1600屏125%等效1280逻辑视口无整页横向溢出")
        result = {"browser": browser.version, "checks": checks, "page_errors": errors, "server_errors": failed_responses}
        (EVIDENCE / "browser-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        assert not errors, errors
        assert not failed_responses, failed_responses
        context.close()
        browser.close()
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
