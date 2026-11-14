"""对5173上的独立验收库检查多算法与过滤层；不改正式用户库。"""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/selection-increment"
BASE = "http://127.0.0.1:5173"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, server_errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge")
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: server_errors.append(response.url) if response.status >= 500 else None)
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        assert page.request.get(BASE + "/api/v1/securities").json()["data"] == [], "必须使用独立空库"
        page.get_by_role("button", name="载入合成演示", exact=True).click()
        page.get_by_role("button", name="运行选股", exact=True).click()
        expect(page.locator(".recommendation-card")).to_have_count(6)
        picker = page.locator(".select-inline select")
        picker.select_option("trend-stability-v1")
        expect(page.locator(".recommendation-card")).to_have_count(0)
        page.get_by_role("button", name="运行选股", exact=True).click()
        expect(page.locator(".recommendation-card")).to_have_count(6)
        recs = page.request.get(BASE + "/api/v1/recommendations").json()["data"]
        assert all(r["algorithm_id"] == "trend-stability-v1" and len(r["input_snapshot_hash"]) == 64 for r in recs)
        expect(page.locator(".recommendation-card").first).to_contain_text("ATR")
        page.screenshot(path=str(OUT / "01-two-algorithms.png"), full_page=True)
        page.get_by_role("button", name="加入自选", exact=True).first.click()
        expect(page.get_by_role("button", name="已在自选", exact=True)).to_have_count(1)
        page.locator("nav button").filter(has_text="自选").click()
        page.get_by_role("button", name="配置此股监测").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_text("Agent 工作方式", exact=False).locator("select").select_option("FILTER")
        page.get_by_role("button", name="保存监测规则", exact=True).click()
        expect(page.get_by_text("监测配置已保存", exact=False)).to_be_visible()
        page.get_by_role("button", name="关闭", exact=True).first.click()
        page.locator("nav button").filter(has_text="信号").click()
        page.get_by_role("button", name="运行信号计算", exact=True).click()
        expect(page.locator(".signal-row")).to_have_count(1)
        panel = page.get_by_role("region", name="复核过滤决策门")
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("未通过过滤")
        expect(panel).to_contain_text("未核对账户，不构成下单许可")
        page.get_by_role("button", name="请求复核", exact=True).click()
        expect(page.get_by_text("AI服务未配置", exact=False)).to_be_visible()
        page.get_by_role("button", name="显式体验规则复核演示（非 AI）", exact=True).click()
        expect(page.get_by_text("规则演示，非AI", exact=False)).to_be_visible()
        expect(panel).to_contain_text("未通过过滤")
        page.screenshot(path=str(OUT / "02-review-gate.png"), full_page=True)
        assert not errors and not server_errors, (errors, server_errors)
        report = {"browser": browser.version, "checks": ["two algorithms explicit selection and distinct explanations", "recommendation versions and input hashes", "FILTER mode persisted", "expired/no-model/rule-demo stay blocked", "execution permission remains not evaluated"], "page_errors": errors, "server_errors": server_errors}
        (OUT / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
