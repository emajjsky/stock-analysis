"""在既有 8765 服务上验证分时边界；测试数据只在独立浏览器内拦截。"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evidence/intraday-viewport"
OUTPUT.mkdir(parents=True, exist_ok=True)


def fixture(count, day="2026-11-03"):
    start = int(datetime.fromisoformat(f"{day}T01:30:00+00:00").timestamp())
    return {
        "data": {
            "symbol": "sh000001",
            "points": [
                {"time": str(start + i * 60),
                 "value": str(3600 + (i % 11) * 0.4 + i * 0.02),
                 "volume": 100000 + i * 1000}
                for i in range(count)
            ],
            "source": "浏览器回归测试夹具",
            "source_time": None,
            "error": None,
        },
        "meta": {},
    }


def measure(page, name, all_visible=False, count=26):
    page.wait_for_timeout(200)
    chart = page.locator('[aria-label="分时与成交量图"]')
    # 左涨跌幅轴也有独立canvas；选择面积最大的绘图区，不把坐标轴当曲线。
    canvases = chart.locator("canvas").all()
    canvas = max(canvases, key=lambda c: c.evaluate('(el) => el.clientWidth * el.clientHeight'))
    png = canvas.screenshot()
    image = Image.open(io.BytesIO(png)).convert("RGB")
    columns = [x for x in range(image.width)
               if any(r < 80 and 60 < g < 125 and 130 < b < 210 and b > g * 1.3
                      for r, g, b in (image.getpixel((x, y))
                                      for y in range(image.height)))]
    assert columns, f"{name}: 价格曲线未渲染"
    left, right = min(columns), image.width - 1 - max(columns)
    limit = image.width / max(2, count) + 8
    if all_visible:
        assert left <= limit, f"{name}: 左侧空白 {left}px > {limit:.1f}px"
    right_limit = max(image.width * 0.12, image.width / count / 2 + 8)
    assert right < right_limit, f"{name}: 右侧空白 {right}px"
    chart.screenshot(path=str(OUTPUT / f"{name}.png"))
    return {"name": name, "width": image.width, "left_blank": left,
            "right_blank": right, "all_visible": all_visible}


def wheel(page, direction, steps=10, ratio=0.2):
    chart = page.locator('[aria-label="分时与成交量图"]')
    chart.scroll_into_view_if_needed()
    box = chart.bounding_box()
    page.mouse.move(box["x"] + box["width"] * ratio,
                    box["y"] + box["height"] * 0.35)
    for _ in range(steps):
        page.mouse.wheel(0, direction * 120)
    page.wait_for_timeout(200)


def run():
    results, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe")
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        state = {"count": 26, "day": "2026-11-03", "requests": 0}

        def intraday(route):
            state["requests"] += 1
            route.fulfill(json=fixture(state["count"], state["day"]))

        page.route("**/api/v1/market/indices/*/intraday", intraday)
        page.goto("http://127.0.0.1:8765/")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector('[aria-label="分时与成交量图"] canvas')
        results.append(measure(page, "01-early-open", True))
        wheel(page, 1, 16)
        results.append(measure(page, "02-zoom-out-limit", True))
        wheel(page, -1, 6)
        results.append(measure(page, "03-zoom-in-right"))
        wheel(page, 1, 16, 0.8)
        results.append(measure(page, "04-zoom-out-other-position", True))

        # 确认真实轮询更新 Vue props 后，全览仍铺满。
        state["count"] = 40
        previous = state["requests"]
        for _ in range(60):
            if state["requests"] > previous:
                break
            page.wait_for_timeout(250)
        assert state["requests"] > previous, "未收到盘中轮询"
        results.append(measure(page, "05-refresh-full-range", True, 40))
        wheel(page, -1, 6)
        before = measure(page, "06-before-refresh-zoom")
        state["count"] = 45
        previous = state["requests"]
        for _ in range(60):
            if state["requests"] > previous:
                break
            page.wait_for_timeout(250)
        assert state["requests"] > previous, "未收到缩放后轮询"
        after = measure(page, "07-refresh-zoom-range")
        assert abs(before["right_blank"] - after["right_blank"]) < 4, \
            "轮询后缩放倍率发生变化"
        results.append(after)
        wheel(page, 1, 16)
        results.append(measure(page, "08-refresh-zoom-out-limit", True, 45))
        for width, height in [(1366, 768), (1920, 1080)]:
            page.set_viewport_size({"width": width, "height": height})
            results.append(measure(page, f"09-resize-{width}", True, 45))
        state.update(count=2, day="2026-11-04")
        previous = state["requests"]
        for _ in range(60):
            if state["requests"] > previous:
                break
            page.wait_for_timeout(250)
        assert state["requests"] > previous, "未收到换日轮询"
        results.append(measure(page, "10-next-day-two-points", True, 2))
        assert not errors, errors
        browser.close()
    report = {"time": datetime.now(timezone.utc).isoformat(),
              "test_data": "browser-only fixtures, no database writes",
              "results": results, "page_errors": errors}
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    run()
