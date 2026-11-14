import { describe, it, expect } from "vitest";
import { chartTimestamp, normalizedPoints, compact, percent } from "./terminal";
describe("行情图时间与缺失值", () => {
  it("ISO 与 Unix 秒统一，拒绝无效时间", () => {
    expect(chartTimestamp("2026-10-29T01:30:00Z")).toBe(1793237400);
    expect(chartTimestamp("1793237400")).toBe(1793237400);
    expect(chartTimestamp("bad")).toBeNull();
    expect(chartTimestamp("0")).toBeNull();
  });
  it("仅保留最新上海交易日，按时序排序去重，不将缺失量补零", () => {
    const points = normalizedPoints([
      { time: "2026-10-28T07:00:00Z", value: "10", volume: 1 },
      { time: "2026-10-29T01:32:00Z", value: "12", volume: null },
      { time: "2026-10-29T01:30:00Z", value: "11", volume: 4 },
      { time: "2026-10-29T01:30:00Z", value: "11.2", volume: 5 },
      { time: "invalid", value: "1", volume: 1 },
    ]);
    expect(points.map((p) => p.value)).toEqual([11.2, 12]);
    expect(points[1].volume).toBeNull();
  });
  it("跨 UTC 零点仍按上海交易日分组", () => {
    expect(
      normalizedPoints([
        { time: "2026-10-28T23:00:00Z", value: "1", volume: null },
        { time: "2026-10-29T01:00:00Z", value: "2", volume: null },
      ]),
    ).toHaveLength(2);
  });
  it("未知价格和比例显示缺失，真实零值保留", () => {
    expect(compact(null)).toBe("—");
    expect(percent(undefined)).toBe("—");
    expect(compact(0)).toBe("0");
    expect(percent(0)).toBe("0.00%");
    expect(percent("1.2")).toBe("+1.20%");
  });
});
