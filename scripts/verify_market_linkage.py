"""Verify market concept selection, ETF identity isolation and convertible linkage."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/market-linkage-20261107"
OUT.mkdir(parents=True, exist_ok=True)


def read_api(page, path):
    return page.evaluate(
        "path => fetch('/api/v1' + path).then(r => r.json()).then(j => j.data)", path
    )


def ready_rows(page, path, timeout=90):
    for _ in range(timeout * 2):
        data = read_api(page, path)
        if data and data.get("rows"):
            return data
        page.wait_for_timeout(500)
    raise AssertionError(f"No rows from {path}")


def etf_matches(name, member_codes, quotes, portfolios):
    direct = name.replace("概念", "").replace("行业", "").replace("板块", "").strip()
    themes = ["人工智能", "机器人"] if "AI应用" in name else []
    members = set(member_codes)
    matched = set()
    for etf in quotes:
        if "ETF" not in etf["name"].upper():
            continue
        holdings = next((p["holdings"] for p in portfolios if p["code"] == etf["code"]), [])
        overlap_rows = [h for h in holdings if h["code"] in members]
        overlap_weight = sum(float(h.get("weight") or 0) for h in overlap_rows)
        exact = len(direct) >= 2 and direct in etf["name"]
        theme = any(word in etf["name"] for word in themes)
        if exact or theme or (len(overlap_rows) >= 3 and overlap_weight >= 20):
            matched.add(etf["code"])
    return matched


def select_concept(page, name, listing, quotes, holdings):
    row = next(r for r in listing["rows"] if r["name"] == name)
    locator = page.locator(".board-top-panel tbody tr").filter(has_text=name).first
    locator.click()
    page.wait_for_function(
        "name => document.querySelector('.member-panel .panel-head strong')?.innerText.trim() === name",
        arg=name,
    )
    members = ready_rows(page, f"/market/boards/{row['code']}/members")
    ordered = sorted(
        members["rows"],
        key=lambda m: float(m.get("quote", {}).get("change_pct") or -1e20),
        reverse=True,
    )
    page.wait_for_function(
        "code => document.querySelector('.member-panel tbody tr td:nth-child(3)')?.innerText.trim() === code",
        arg=ordered[0]["code"],
    )
    actual_codes = set(page.locator(".etf-panel .etf-row small").all_text_contents())
    expected_codes = etf_matches(
        name, [m["code"] for m in members["rows"]], quotes["rows"], holdings["rows"]
    )
    assert actual_codes == expected_codes, (name, actual_codes, expected_codes)
    if expected_codes:
        page.wait_for_function(
            "() => document.querySelectorAll('.etf-panel .etf-row').length > 0",
            timeout=30000,
        )
    else:
        page.wait_for_function(
            "() => document.querySelector('.etf-panel .etf-empty')?.innerText.includes('当前披露样本中暂无可靠匹配')",
            timeout=30000,
        )
    return {
        "name": name,
        "code": row["code"],
        "member_count": members.get("loaded"),
        "visible_first_member": ordered[0]["code"],
        "etf_codes": sorted(actual_codes),
    }


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8765/#/market")
    page.wait_for_selector(".market-tabs [role=tab]", timeout=60000)
    page.wait_for_selector(".board-top-panel tbody tr", timeout=60000)

    listing = ready_rows(page, "/market/boards?kind=concept")
    latest = ready_rows(page, "/market/boards/concepts/latest")
    mapped = [r for r in latest["rows"] if r.get("board_code")]
    exact = [r for r in latest["rows"] if any(b["name"] == r["name"] for b in listing["rows"])]
    assert len(listing["rows"]) == 531
    assert len(latest["rows"]) == 10 and len(mapped) == 7 and len(exact) == 7

    quotes = ready_rows(page, "/market/etfs")
    holdings = ready_rows(page, "/market/etfs/holdings")
    bonds = ready_rows(page, "/market/bonds/convertible")
    assert bonds["loaded"] > 300 and bonds["total"] >= bonds["loaded"]
    assert all(row["stock_code"] and row["change_spread"] is not None for row in bonds["rows"])

    assert page.get_by_role("tab", name="最新概念", exact=True).count() == 0
    page.get_by_role("tab", name="板块热点", exact=True).click()
    page.get_by_role("button", name="概念", exact=True).click()
    page.wait_for_timeout(800)
    first = select_concept(page, "AI应用", listing, quotes, holdings)
    assert first["etf_codes"]
    page.screenshot(path=str(OUT / "desktop-hot-concept.png"), full_page=True)
    second = select_concept(page, "2026三季报预增", listing, quotes, holdings)
    assert not second["etf_codes"]
    page.screenshot(path=str(OUT / "desktop-event-without-etf-match.png"), full_page=True)

    page.get_by_role("tab", name="债股联动", exact=True).click()
    page.wait_for_selector(".bond-pair-grid", timeout=60000)
    selected = page.locator(".bond-link-panel .panel-head strong").inner_text().strip()
    assert selected and page.locator(".bond-source-label").inner_text() == "东方财富延时行情"
    assert page.locator(".bond-terms").count() == 1
    page.screenshot(path=str(OUT / "desktop-bond-linkage.png"), full_page=True)

    page.get_by_role("tab", name="板块热点", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('.member-panel .panel-head strong')?.innerText.trim() === '2026三季报预增'"
    )
    returned = select_concept(page, "2026三季报预增", listing, quotes, holdings)
    assert returned == second
    select_concept(page, "AI应用", listing, quotes, holdings)
    assert not errors, errors

    mobile = browser.new_page(viewport={"width": 390, "height": 844})
    mobile.goto("http://127.0.0.1:8765/#/market")
    mobile.wait_for_selector(".market-tabs [role=tab]", timeout=60000)
    mobile.get_by_role("tab", name="债股联动", exact=True).click()
    mobile.wait_for_selector(".bond-pair-grid", timeout=60000)
    overflow = mobile.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 2, overflow
    mobile.screenshot(path=str(OUT / "mobile-bond-linkage.png"), full_page=True)
    assert not errors, errors

    result = {
        "concept_counts": {
            "eastmoney_concept_boards": len(listing["rows"]),
            "latest_concept_events": len(latest["rows"]),
            "exact_name_mappings": len(exact),
        },
        "etf_switch_checks": [first, second, returned],
        "convertible_bonds": {
            "market_quotes": bonds["total"],
            "linked": bonds["loaded"],
            "unmatched": bonds.get("unmatched"),
            "source": bonds["source"],
        },
        "selected_bond": selected,
        "mobile_horizontal_overflow": overflow,
        "page_errors": errors,
    }
    (OUT / "browser-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    browser.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
