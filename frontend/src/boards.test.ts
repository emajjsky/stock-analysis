import { describe, it, expect } from "vitest";
import {
  boardTiles,
  boardBreadth,
  bondBreadth,
  wan,
  matchEtfs,
  etfEmptyMessage,
  membersForBoard,
  type Board,
  type BoardMembers,
  type Etfs,
  type EtfHoldings,
} from "./boards";

describe("板块图表数据口径", () => {
  it("债股分布互斥计数，平盘与缺报价单独保留", () => {
    const rows = [
      { change_pct: "2", stock_change_pct: "1" },
      { change_pct: "-2", stock_change_pct: "-1" },
      { change_pct: "2", stock_change_pct: "-1" },
      { change_pct: "-2", stock_change_pct: "1" },
      { change_pct: "0", stock_change_pct: "1" },
      { change_pct: "0", stock_change_pct: "0" },
      { change_pct: "2", stock_change_pct: null },
      { change_pct: "", stock_change_pct: "1" },
    ];
    const counts = bondBreadth(rows);
    expect(counts).toEqual({
      bothUp: 1,
      bothDown: 1,
      bondUp: 1,
      stockUp: 1,
      flat: 2,
      missing: 2,
    });
    expect(
      Object.values(counts).reduce((total, value) => total + value, 0),
    ).toBe(rows.length);
  });
  it("区分来源全量涨跌分布与已载入行情覆盖，不把缺报价证券当成下跌", () => {
    const rows = [
      { change_pct: "4.2" },
      { change_pct: "0" },
      { change_pct: "-1.1" },
      { change_pct: null },
      { change_pct: "" },
      { change_pct: "not-a-number" },
      { change_pct: "7.0" },
    ];
    expect(
      boardBreadth(rows, { advancing: 25, unchanged: 1, declining: 282 }, 308),
    ).toEqual({
      up: 25,
      flat: 1,
      down: 282,
      total: 308,
      loaded: 4,
      membersTotal: 308,
      bands: [
        { label: "≥7%", tone: "up", count: 1 },
        { label: "3%至7%", tone: "up", count: 1 },
        { label: "-3%至3%", tone: "flat", count: 2 },
        { label: "-7%至-3%", tone: "down", count: 0 },
        { label: "≤-7%", tone: "down", count: 0 },
      ],
    });
    expect(boardBreadth(rows)).toEqual({
      up: 2,
      flat: 1,
      down: 1,
      total: 4,
      loaded: 4,
      membersTotal: null,
      bands: [
        { label: "≥7%", tone: "up", count: 1 },
        { label: "3%至7%", tone: "up", count: 1 },
        { label: "-3%至3%", tone: "flat", count: 2 },
        { label: "-7%至-3%", tone: "down", count: 0 },
        { label: "≤-7%", tone: "down", count: 0 },
      ],
    });
  });
  it("热力图覆盖全部分类，等面积可查看缺失成交额的板块", () => {
    const rows = Array.from(
      { length: 496 },
      (_, i) => ({ code: String(i), amount: String(i + 1) }) as Board,
    );
    expect(boardTiles(rows)).toHaveLength(496);
    const equal = boardTiles(
      [...rows, { code: "missing", amount: null } as Board],
      900,
      500,
      "equal",
    );
    expect(equal).toHaveLength(497);
    expect(
      equal.every(
        (t) => Math.abs((t.width * t.height) / 10000 - 1 / 497) < 1e-10,
      ),
    ).toBe(true);
  });
  it("ETF披露重仓匹配至少3只且累计净值权重20%，避免偶然交集", () => {
    const rows = [
      {
        code: "1",
        name: "农业ETF",
        amount: "100",
        market: 0,
        price: "1",
        change_pct: "0",
      },
      {
        code: "2",
        name: "消费电子ETF",
        amount: "200",
        market: 0,
        price: "1",
        change_pct: "0",
      },
      {
        code: "3",
        name: "沪深300ETF",
        amount: "300",
        market: 0,
        price: "1",
        change_pct: "0",
      },
      {
        code: "4",
        name: "沪深300LOF",
        amount: "500",
        market: 0,
        price: "1",
        change_pct: "0",
      },
    ];
    expect(matchEtfs("种子", rows).map((e) => e.code)).toEqual(["1"]);
    expect(matchEtfs("MLCC概念", rows).map((e) => e.code)).toEqual(["2"]);
    expect(matchEtfs("2026三季报预增", rows)).toEqual([]);
    const portfolio = {
      code: "3",
      name: "沪深300ETF",
      report_date: "2026-09-30",
      holdings: [
        { code: "600519", name: "贵州茅台", weight: "12" },
        { code: "600036", name: "招商银行", weight: "8" },
        { code: "000001", name: "平安银行", weight: "5" },
      ],
    };
    const incidentalMembers = [
      "600519",
      "600036",
      ...Array.from({ length: 107 }, (_, i) => `X${i}`),
    ];
    expect(
      matchEtfs("2026三季报预增", rows, incidentalMembers, [portfolio]),
    ).toEqual([]);
    expect(
      matchEtfs("自定义行业", rows, ["600519", "600036"], [portfolio]),
    ).toEqual([]);
    const concentratedMembers = [
      "600519",
      "600036",
      "000001",
      ...Array.from({ length: 7 }, (_, i) => `Y${i}`),
    ];
    const matches = matchEtfs("自定义行业", rows, concentratedMembers, [
      portfolio,
    ]);
    expect(matches).toHaveLength(1);
    expect(matches[0]!.matchReason).toBe("披露重仓重合 · 3只 / 25.0%");
    expect(matches[0]!.matchDetail).toContain("2026-09-30");
    expect(matches[0]!.matchDetail).toContain("25.00%");
  });
  it("ETF无匹配时区分行情加载、持仓加载、源不可用和无可靠候选", () => {
    const quotes = {
      rows: [
        {
          code: "1",
          name: "农业ETF",
          market: 0,
          price: "1",
          change_pct: "0",
          amount: "100",
        },
      ],
    } as Etfs;
    const holdings = {
      status: "READY",
      refreshing: false,
      stale: false,
      error: null,
      fetched_at: null,
      enabled: true,
      rows: [],
    } as EtfHoldings;
    expect(etfEmptyMessage(undefined, undefined)).toBe("正在加载ETF行情…");
    expect(etfEmptyMessage(quotes, undefined)).toBe("正在读取ETF披露持仓…");
    expect(
      etfEmptyMessage(quotes, {
        ...holdings,
        refreshing: true,
        status: "LOADING",
      }),
    ).toBe("正在读取ETF披露持仓…");
    expect(etfEmptyMessage(quotes, { ...holdings, error: "upstream" })).toBe(
      "ETF披露持仓暂不可用",
    );
    expect(etfEmptyMessage(quotes, undefined, "network error")).toBe(
      "ETF披露持仓暂不可用",
    );
    expect(etfEmptyMessage(quotes, holdings)).toBe(
      "当前披露样本中暂无可靠匹配",
    );
  });
  it("板块成员只在缓存身份与所选板块完全一致时复用", () => {
    const cached = {
      code: "BK1001",
      rows: [{ code: "600000" }],
    } as unknown as BoardMembers;
    expect(membersForBoard("BK1001", cached)).toBe(cached);
    expect(membersForBoard("BK2002", cached)).toBeUndefined();
  });
  it("竖栏根据真实画布比例分割，不沿用横向矩形导致细条", () => {
    const rows = [9, 11].map(
      (amount, i) => ({ code: String(i), amount: String(amount) }) as Board,
    );
    const portrait = boardTiles(rows, 300, 480);
    const landscape = boardTiles(rows, 900, 330);
    expect(portrait[0]!.width).toBe(100);
    expect(landscape[0]!.height).toBe(100);
  });
  it("缺失金额不补零，元统一转万元，净额保留方向", () => {
    expect(wan(null)).toBe("—");
    expect(wan("100000")).toBe("10.0");
    expect(wan("-12500", true)).toBe("-1.3");
    expect(wan("12500", true)).toBe("+1.3");
  });
  it("热力图矩形面积保持成交额比例，并且不重叠、不越界", () => {
    const boards = [1, 2, 3, 4, 9, 11].map(
      (amount, i) => ({ code: String(i), amount: String(amount) }) as Board,
    );
    const tiles = boardTiles([...boards, { amount: null } as Board]);
    const total = boards.reduce((sum, b) => sum + Number(b.amount), 0);
    expect(tiles).toHaveLength(6);
    for (const t of tiles) {
      expect((t.width * t.height) / 10000).toBeCloseTo(
        Number(t.board.amount) / total,
      );
      expect(t.x + t.width).toBeLessThanOrEqual(100.00001);
      expect(t.y + t.height).toBeLessThanOrEqual(100.00001);
      for (const other of tiles.filter((o) => o !== t)) {
        const overlap =
          Math.min(t.x + t.width, other.x + other.width) -
          Math.max(t.x, other.x);
        const vertical =
          Math.min(t.y + t.height, other.y + other.height) -
          Math.max(t.y, other.y);
        expect(overlap <= 0.000001 || vertical <= 0.000001).toBe(true);
      }
    }
  });
});
