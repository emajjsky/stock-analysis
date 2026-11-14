"""Verify market navigation, unique breadth details, and desktop/mobile layouts."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/market-interface-audit-20261107"
EXPECTED_TABS = [
    "板块热点",
    "板块轮动",
    "板块分析",
    "板块资金",
    "板块增仓",
    "债股联动",
    "期股联动",
    "证券目录",
]


def assert_no_page_overflow(page):
    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 2, f"horizontal page overflow: {overflow}px"
    return overflow


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8765/#/market")
    page.wait_for_selector(".market-tabs [role=tab]", timeout=60000)
    labels = [
        value.strip()
        for value in page.locator(".market-tabs [role=tab]").all_text_contents()
    ]
    assert labels == EXPECTED_TABS, labels
    page.wait_for_selector(".board-top-panel tbody tr", timeout=60000)
    OUT.mkdir(parents=True, exist_ok=True)
    results = {"tabs": labels, "desktop_overflow": {}, "screenshots": []}

    page.get_by_role("tab", name="板块热点", exact=True).click()
    page.get_by_role("button", name="概念", exact=True).click()
    concept_row = page.locator(".board-top-panel tbody tr").filter(has_text="AI应用").first
    concept_row.click()
    page.wait_for_function(
        "document.querySelector('.breadth-coverage b')?.innerText.trim() === '296 / 308'",
        timeout=60000,
    )
    page.wait_for_selector(".stock-chart-panel .chart-area canvas", timeout=60000)
    assert page.locator(".breadth-main, .movers").count() == 0
    assert page.locator(".breadth-labels .flat").inner_text().strip() == "平 0.3%"
    page.screenshot(path=str(OUT / "01-hot-concept.png"))
    results["screenshots"].append("01-hot-concept.png")
    results["breadth"] = {
        "coverage": page.locator(".breadth-coverage b").inner_text().strip(),
        "distribution": page.locator(".breadth-labels").inner_text().replace("\n", " ").strip(),
        "member_return_bands": [
            text.replace("\n", " ").strip()
            for text in page.locator(".breadth-bands > div").all_text_contents()
        ],
    }
    assert sum(int(value) for value in page.locator(".breadth-bands strong").all_text_contents()) == 296
    results["desktop_overflow"]["板块热点"] = assert_no_page_overflow(page)

    for index, label in enumerate(EXPECTED_TABS[1:], start=2):
        page.get_by_role("tab", name=label, exact=True).click()
        page.wait_for_function(
            "label => [...document.querySelectorAll('.market-tabs [role=tab]')].some(el => el.getAttribute('aria-selected') === 'true' && el.innerText.trim() === label)",
            arg=label,
        )
        page.wait_for_timeout(700)
        if label in {"板块轮动", "板块分析", "板块资金", "板块增仓"}:
            page.wait_for_selector(".market-center .main-chart-panel canvas", timeout=60000)
            if label != "板块分析":
                page.wait_for_selector(".market-center .stock-chart-panel canvas", timeout=60000)
        if label == "期股联动":
            page.wait_for_selector(".market-center .main-chart-panel canvas", timeout=60000)
            page.wait_for_selector(".market-center .stock-chart-panel canvas", timeout=60000)
        if label == "债股联动":
            page.wait_for_selector(".bond-distribution dd", timeout=30000)
            counts = [int(value) for value in page.locator(".bond-distribution dd").all_text_contents()]
            totals = page.locator(".bond-method-panel footer").inner_text().split("/")
            assert sum(counts) == int(totals[0].strip())
            results["bond_distribution"] = counts
        if label == "证券目录":
            assert page.locator(".catalog-panel").is_visible()
            assert page.locator(".toolbar-actions .icon-button").count() == 0
            assert page.locator(".toolbar-actions time").count() == 0
            assert page.locator(".market-notice").count() == 0
            search = page.get_by_role("textbox", name="搜索证券")
            search.fill("平安银行")
            page.wait_for_function(
                "document.querySelector('.catalog-panel tbody td.code-cell span')?.innerText.trim() === '000001'",
                timeout=30000,
            )
            search.fill("")
            page.wait_for_function(
                "document.querySelectorAll('.catalog-panel tbody tr').length === 100",
                timeout=30000,
            )
        overflow = assert_no_page_overflow(page)
        results["desktop_overflow"][label] = overflow
        path = f"{index:02d}-{label}.png"
        page.screenshot(path=str(OUT / path))
        results["screenshots"].append(path)

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.on("pageerror", lambda error: errors.append(str(error)))
    mobile.goto("http://127.0.0.1:8765/#/market")
    mobile.wait_for_selector(".market-tabs [role=tab]", timeout=60000)
    mobile.get_by_role("tab", name="证券目录", exact=True).click()
    mobile.wait_for_selector(".catalog-panel tbody tr", timeout=30000)
    results["mobile_overflow"] = assert_no_page_overflow(mobile)
    mobile.screenshot(path=str(OUT / "09-catalog-mobile.png"), full_page=True)
    results["screenshots"].append("09-catalog-mobile.png")

    # A failed source must stay in its own workspace and clear after recovery.
    failure_page = browser.new_page(viewport={"width": 1366, "height": 900})
    failure_page.on("pageerror", lambda error: errors.append(str(error)))
    pattern = "**/api/v1/market/etfs/holdings"
    failure_page.route(pattern, lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"error": {"code": "AUDIT_TEST", "message_zh": "ETF接口故障回归样例"}}),
    ))
    failure_page.goto("http://127.0.0.1:8765/#/market")
    failure_page.wait_for_function(
        "document.querySelector('.market-notice')?.innerText.includes('ETF接口故障回归样例')",
        timeout=30000,
    )
    failure_page.get_by_role("tab", name="债股联动", exact=True).click()
    failure_page.wait_for_timeout(300)
    assert "ETF接口故障回归样例" not in failure_page.locator(".market-page").inner_text()
    failure_page.get_by_role("tab", name="证券目录", exact=True).click()
    failure_page.wait_for_selector(".catalog-panel tbody tr", timeout=30000)
    assert failure_page.locator(".market-notice").count() == 0
    failure_page.unroute(pattern)
    failure_page.get_by_role("tab", name="板块热点", exact=True).click()
    failure_page.wait_for_function(
        "!document.querySelector('.market-notice')?.innerText.includes('ETF接口故障回归样例')",
        timeout=30000,
    )
    results["source_error_isolation_and_recovery"] = "passed"
    results["narrow_desktop_overflow"] = assert_no_page_overflow(failure_page)
    results["page_errors"] = errors
    assert not errors, errors
    (OUT / "browser-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
