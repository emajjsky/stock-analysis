import { describe, expect, it } from "vitest";
import { nextMarketRange } from "./marketChartRange";

describe("市场图表可见范围", () => {
  it("首次、日期切换、异常范围和单点数据全览", () => {
    expect(nextMarketRange(null, 0, 241)).toBeNull();
    expect(nextMarketRange({ from: 20, to: 80 }, 241, 241, true)).toBeNull();
    expect(nextMarketRange({ from: NaN, to: Infinity }, 241, 241)).toBeNull();
    expect(nextMarketRange({ from: 0, to: 1 }, 1, 1)).toBeNull();
  });
  it("全览更新仍然全览，不把数据挤进旧窗口", () => {
    expect(nextMarketRange({ from: -0.5, to: 240.5 }, 241, 242)).toBeNull();
    expect(nextMarketRange({ from: -1000, to: 1000 }, 241, 241)).toBeNull();
  });
  it("跟随最新时保持窗口宽度，历史浏览时保持原位置", () => {
    expect(nextMarketRange({ from: 200, to: 240 }, 241, 245)).toEqual({
      from: 204,
      to: 244,
    });
    expect(nextMarketRange({ from: 20, to: 80 }, 241, 245)).toEqual({
      from: 20,
      to: 80,
    });
  });
  it("缩放和拖拽的范围被约束到有效数据内", () => {
    expect(nextMarketRange({ from: -20, to: 40 }, 241, 241)).toEqual({
      from: 0,
      to: 60,
    });
    expect(nextMarketRange({ from: 400, to: 450 }, 241, 241)).toEqual({
      from: 190,
      to: 240,
    });
    expect(nextMarketRange({ from: 0, to: 500 }, 500, 100)).toBeNull();
  });
});
