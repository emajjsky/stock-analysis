"""自动监测界面验收，固定使用独立5173测试库。"""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/automation-increment"
BASE = "http://127.0.0.1:5173"


def wait_for_scheduled_runs(page, count, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = page.request.get(BASE + '/api/v1/automation/runs').json()['data']
        complete = [item for item in runs if item['trigger'] == 'SCHEDULED' and item['status'] == 'SUCCEEDED']
        if len(complete) >= count:
            return complete
        page.wait_for_timeout(1000)
    raise AssertionError(f'未在{timeout}秒内观察到{count}次成功定时运行')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    errors, server_errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge")
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: server_errors.append(response.url) if response.status >= 500 else None)
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        assert page.request.get(BASE + "/api/v1/securities").json()["data"] == [], "必须使用本轮独立空库"
        assert page.request.get(BASE + "/api/v1/sim/accounts").json()["data"] == []
        page.get_by_role("button", name="载入合成演示", exact=True).click()
        page.locator("nav button").filter(has_text="自选").click()
        panel = page.get_by_role("region", name="自动监测")
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("自动监测已关闭")
        expect(panel).to_contain_text("不自动拉取实时行情，也不连接交易")
        assert page.request.get(BASE + "/api/v1/automation").json()["data"]["enabled"] is False
        # 加一条持久化监测规则，检查单次运行从同一套计算入口产出结果。
        page.evaluate("""async () => {
          const r = await fetch('/api/v1/watchlists', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({security_id:'DEMO.000001'})});
          const watch = (await r.json()).data;
          await fetch(`/api/v1/watchlists/${watch.id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({monitor_enabled:true})});
        }""")
        page.get_by_role("button", name="立即运行一次").click()
        expect(panel.locator(".automation-run")).to_have_count(1, timeout=15000)
        expect(panel.locator(".automation-run").first).to_contain_text("手动")
        expect(panel.locator(".automation-run").first).to_contain_text("生成")
        assert len(page.request.get(BASE + "/api/v1/signals").json()["data"]) >= 1
        panel.locator('input[type="checkbox"]').first.check()
        interval = panel.get_by_label("检查间隔（秒）")
        interval.fill("30")
        panel.get_by_role("button", name="保存设置").click()
        expect(panel).to_contain_text("自动监测已启用")
        saved = page.request.get(BASE + "/api/v1/automation").json()["data"]
        assert saved["enabled"] is True and saved["interval_seconds"] == 30 and saved["auto_review"] is False
        # 启用立即调度，再等待一个真实30秒周期；不靠修改后台时间伪造定时成功。
        wait_for_scheduled_runs(page, 1, 15)
        signal_ids = sorted(x["id"] for x in page.request.get(BASE + "/api/v1/signals").json()["data"])
        interval.fill("47")
        page.wait_for_timeout(6500)
        expect(interval).to_have_value("47")
        assert page.request.get(BASE + "/api/v1/automation").json()["data"]["interval_seconds"] == 30
        scheduled = wait_for_scheduled_runs(page, 2, 40)
        scheduled.sort(key=lambda item: item["started_at"])
        from datetime import datetime
        gaps = [(datetime.fromisoformat(b["started_at"].replace("Z", "+00:00")) - datetime.fromisoformat(a["started_at"].replace("Z", "+00:00"))).total_seconds() for a, b in zip(scheduled, scheduled[1:])]
        assert len(gaps) >= 1 and gaps[-1] >= 29, f"必须观察到真实30秒调度间隔，实际间隔={gaps}"
        assert time.monotonic() - started >= 29, "验收未实际等待一个调度周期"
        assert sorted(x["id"] for x in page.request.get(BASE + "/api/v1/signals").json()["data"]) == signal_ids
        interval.fill("30")
        panel.get_by_role("button", name="保存设置").click()
        expect(panel).not_to_contain_text("待保存")
        page.reload()
        page.wait_for_load_state("networkidle")
        panel = page.get_by_role("region", name="自动监测")
        expect(panel.locator('input[type="checkbox"]').first).to_be_checked()
        expect(panel.get_by_label("检查间隔（秒）")).to_have_value("30")
        panel.locator("summary").click()
        expect(panel.locator(".automation-run").first).to_be_visible()
        page.screenshot(path=str(OUT / "01-automation-panel.png"), full_page=True)
        panel.locator('input[type="checkbox"]').first.uncheck()
        panel.locator('input[type="checkbox"]').nth(1).check()
        panel.get_by_role("button", name="保存设置").click()
        expect(panel).to_contain_text("自动监测已关闭")
        page.get_by_role("button", name="立即运行一次").click()
        expect(panel.locator(".automation-run").first).to_contain_text("尚未配置LLM", timeout=15000)
        assert page.request.get(BASE + "/api/v1/automation/runs").json()["data"][0]["reviewed"] == 0
        panel.locator('input[type="checkbox"]').nth(1).uncheck()
        panel.get_by_role("button", name="保存设置").click()
        expect(panel).not_to_contain_text("待保存")
        page.reload()
        page.wait_for_load_state("networkidle")
        final_config = page.request.get(BASE + "/api/v1/automation").json()["data"]
        assert final_config["enabled"] is False and final_config["auto_review"] is False
        assert page.request.get(BASE + "/api/v1/sim/accounts").json()["data"] == []
        page.set_viewport_size({"width": 1280, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(OUT / "02-automation-disabled-1280.png"), full_page=True)
        assert not errors and not server_errors, (errors, server_errors)
        report = {"browser": browser.version, "checks": ["default disabled state", "clear cached-data and no-trading boundary", "manual one-shot run and persisted signal", "two scheduled runs separated by at least 29 seconds", "polling preserves unsaved form", "unchanged signals deduplicated", "enabled configuration persists after reload", "unconfigured agent never reviews", "disabled configuration persists and no account created", "1280 viewport without page overflow"], "scheduled_run_gaps_seconds": gaps, "elapsed_seconds": round(time.monotonic() - started, 1), "final_config": final_config, "runs": page.request.get(BASE + "/api/v1/automation/runs").json()["data"], "page_errors": errors, "server_errors": server_errors}
        (OUT / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
