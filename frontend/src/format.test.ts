import { describe, it, expect } from "vitest";
import { money, safeUrl, date, label } from "./format";
describe("行情展示边界", () => {
  it("未知金额不补零，前端只做显示格式化", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money("")).toBe("—");
    expect(money("0")).toBe("0.00");
    expect(money("1234.5")).toBe("1,234.50");
  });
  it("事件原文只允许 HTTP URL，阻止脚本协议", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("file:///c:/secret")).toBeNull();
    expect(safeUrl("https://example.com/notice")).toBe(
      "https://example.com/notice",
    );
  });
  it("UTC来源时间显示北京时间且Agent立场不伪装概率", () => {
    expect(date("2026-10-27T01:30:00Z")).toContain("09:30");
    expect(label("WAIT")).toBe("等待");
    expect(label("CONFIRMED")).toBe("已确认");
  });
});
