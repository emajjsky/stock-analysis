import type { Bar, Security } from "./types";
import type { Intraday } from "./terminal";

export interface Board {
  id: string;
  code: string;
  name: string;
  kind: string;
  price: string | null;
  change_pct: string | null;
  amount: string | null;
  turnover_rate: string | null;
  net_inflow: string | null;
  net_ratio: string | null;
  advancing: number | null;
  declining: number | null;
  unchanged: number | null;
  source_time: string | null;
  leader: {
    id: string;
    code: string;
    name: string;
    change_pct: string | null;
  } | null;
  speed?: string | null;
  super_net?: string | null;
  large_net?: string | null;
  medium_net?: string | null;
  small_net?: string | null;
  net_3d?: string | null;
  ratio_3d?: string | null;
  net_5d?: string | null;
  ratio_5d?: string | null;
  net_10d?: string | null;
  ratio_10d?: string | null;
}
export interface BoardCache {
  status: string;
  refreshing: boolean;
  stale: boolean;
  error: string | null;
  fetched_at: string | null;
  enabled: boolean;
  source?: string;
}
export interface BoardList extends BoardCache {
  rows?: Board[];
  total?: number;
}
export interface BoardPositions extends BoardCache {
  rows?: (Board & {
    position_today: string | null;
    position_2d: string | null;
    position_3d: string | null;
    rank_today?: number;
    rank_2d?: number;
    rank_3d?: number;
  })[];
  covered?: number;
  total?: number;
  failed?: number;
  progress?: { completed: number; total: number; failed: number };
  formula?: string;
}
export function boardBreadth(
  rows: { change_pct?: string | null }[],
  source?: Pick<Board, "advancing" | "unchanged" | "declining">,
  membersTotal?: number,
) {
  const quotedRows = rows.filter(
    (row) =>
      row.change_pct != null &&
      row.change_pct.trim() !== "" &&
      Number.isFinite(Number(row.change_pct)),
  );
  const sourceCounts = [
    source?.advancing,
    source?.unchanged,
    source?.declining,
  ];
  const hasCompleteSourceCounts = sourceCounts.every(
    (value) =>
      value != null && Number.isFinite(Number(value)) && Number(value) >= 0,
  );
  const up = hasCompleteSourceCounts
    ? Number(sourceCounts[0])
    : quotedRows.filter((row) => Number(row.change_pct) > 0).length;
  const flat = hasCompleteSourceCounts
    ? Number(sourceCounts[1])
    : quotedRows.filter((row) => Number(row.change_pct) === 0).length;
  const down = hasCompleteSourceCounts
    ? Number(sourceCounts[2])
    : quotedRows.filter((row) => Number(row.change_pct) < 0).length;
  const definitions = [
    { label: "≥7%", tone: "up", test: (value: number) => value >= 7 },
    {
      label: "3%至7%",
      tone: "up",
      test: (value: number) => value >= 3 && value < 7,
    },
    {
      label: "-3%至3%",
      tone: "flat",
      test: (value: number) => value > -3 && value < 3,
    },
    {
      label: "-7%至-3%",
      tone: "down",
      test: (value: number) => value > -7 && value <= -3,
    },
    { label: "≤-7%", tone: "down", test: (value: number) => value <= -7 },
  ] as const;
  return {
    up,
    flat,
    down,
    total: up + flat + down,
    loaded: quotedRows.length,
    membersTotal:
      membersTotal ?? (hasCompleteSourceCounts ? up + flat + down : null),
    bands: definitions.map((band) => ({
      label: band.label,
      tone: band.tone,
      count: quotedRows.filter((row) => band.test(Number(row.change_pct)))
        .length,
    })),
  };
}
export type FlowFields = Pick<
  Board,
  | "speed"
  | "super_net"
  | "large_net"
  | "medium_net"
  | "small_net"
  | "net_3d"
  | "ratio_3d"
  | "net_5d"
  | "ratio_5d"
  | "net_10d"
  | "ratio_10d"
> & { net_inflow?: string | null; net_ratio?: string | null };
export interface BoardMembers extends BoardCache {
  code?: string;
  rows?: (Security & { quote: Security["quote"] & FlowFields })[];
  total?: number;
  loaded?: number;
}
export function membersForBoard(code: string, members?: BoardMembers) {
  return code && members?.code === code ? members : undefined;
}
export interface BoardChart extends BoardCache {
  code?: string;
  name?: string;
  period?: string;
  trade_date?: string;
  points?: Intraday["points"];
  bars?: Bar[];
  previous_close?: string | null;
  flows?: {
    time: string;
    net_inflow: string | null;
    net_ratio: string | null;
    close: string | null;
    change_pct: string | null;
  }[];
}
export interface Rotation extends Partial<BoardCache> {
  days: { date: string; rows: Board[]; fetched_at: string }[];
  covered?: number;
  total?: number;
  failed?: number;
  progress?: { completed: number; total: number; failed: number };
}
export interface BoardNews extends BoardCache {
  items?: {
    id: string;
    title: string;
    summary: string;
    published_at: string;
    media: string;
    url: string | null;
  }[];
}
export interface BoardFinancial extends BoardCache {
  covered?: number;
  sample_size?: number;
  metrics?: Record<string, { value: string | null; count: number }>;
  rows?: { code: string; name: string; period: string }[];
  balance_error?: string | null;
}
export interface NewConcepts extends BoardCache {
  rows?: {
    id: string;
    name: string;
    date: string;
    total: number;
    event: string;
    url: string;
    board_code: string | null;
  }[];
}
export interface Future {
  id: string;
  code: string;
  name: string;
  market: number;
  price: string | null;
  change_pct: string | null;
  change: string | null;
  volume: string | null;
  amount: string | null;
  bid: string | null;
  ask: string | null;
  open_interest: string | null;
  interest_change: string | null;
  source_time: string | null;
  theme: string | null;
  theme_keywords: string[];
}
export interface Futures extends BoardCache {
  rows?: Future[];
  loaded?: number;
}
export interface ConvertibleBond {
  id: string;
  code: string;
  name: string;
  price: string | null;
  change_pct: string | null;
  amount: string | null;
  source_time: string | null;
  stock_id: string;
  stock_code: string;
  stock_name: string;
  stock_price: string | null;
  stock_change_pct: string | null;
  stock_source_time: string | null;
  change_spread: string | null;
  listing_date: string | null;
  conversion_start: string | null;
  conversion_end: string | null;
  conversion_state: "BEFORE" | "ACTIVE" | "ENDED" | "UNKNOWN";
  initial_conversion_price: string | null;
  issue_scale: string | null;
}
export interface ConvertibleBonds extends BoardCache {
  rows?: ConvertibleBond[];
  total?: number;
  loaded?: number;
  linked?: number;
  unmatched?: number;
  relation_note?: string;
}
export function bondBreadth(
  rows: Pick<ConvertibleBond, "change_pct" | "stock_change_pct">[],
) {
  const counts = {
    bothUp: 0,
    bothDown: 0,
    bondUp: 0,
    stockUp: 0,
    flat: 0,
    missing: 0,
  };
  for (const row of rows) {
    const values = [row.change_pct, row.stock_change_pct];
    if (
      values.some(
        (value) =>
          value == null ||
          value.trim() === "" ||
          !Number.isFinite(Number(value)),
      )
    ) {
      counts.missing++;
      continue;
    }
    const bond = Number(row.change_pct),
      stock = Number(row.stock_change_pct);
    if (bond === 0 || stock === 0) counts.flat++;
    else if (bond > 0 && stock > 0) counts.bothUp++;
    else if (bond < 0 && stock < 0) counts.bothDown++;
    else if (bond > 0) counts.bondUp++;
    else counts.stockUp++;
  }
  return counts;
}
export interface Etfs extends BoardCache {
  rows?: {
    code: string;
    name: string;
    market: number;
    price: string | null;
    change_pct: string | null;
    amount: string | null;
  }[];
}

export interface EtfHoldings extends BoardCache {
  rows?: {
    code: string;
    name: string;
    report_date: string;
    holdings: { code: string; name: string; weight: string | null }[];
  }[];
  total?: number;
  failed?: number;
}

export function etfEmptyMessage(
  quotes: Etfs | undefined,
  portfolios: EtfHoldings | undefined,
  portfoliosError = "",
) {
  if (!quotes?.rows?.length) {
    if (quotes?.refreshing || !quotes) return "正在加载ETF行情…";
    return "ETF行情暂不可用";
  }
  if (portfoliosError) return "ETF披露持仓暂不可用";
  if (!portfolios || portfolios.refreshing || portfolios.status === "LOADING")
    return "正在读取ETF披露持仓…";
  if (portfolios.error && !portfolios.rows?.length)
    return "ETF披露持仓暂不可用";
  return "当前披露样本中暂无可靠匹配";
}

// 名称直接对应、人工上位主题和披露重仓重合分别保留理由，不能当作精确板块持仓比例。
const etfThemes: [RegExp, string[]][] = [
  [/种子|种植|农业|转基因/, ["农业"]],
  [/养殖|饲料/, ["养殖", "农业"]],
  [/半导体|芯片|MLCC|玻璃基板/i, ["半导体", "芯片", "电子"]],
  [/光伏|太阳能/, ["光伏"]],
  [/电池|锂电|能源金属|锂矿/, ["电池", "新能源"]],
  [/元件|电子|电路板|PCB|被动元件/i, ["电子", "半导体"]],
  [/工业金属|小金属|有色/, ["有色", "稀有金属"]],
  [/贵金属|黄金/, ["黄金"]],
  [/化学|化工/, ["化工"]],
  [/电力|电网|特高压/, ["电力", "电网"]],
  [/石油|油气/, ["石油", "油气"]],
  [/煤炭|焦煤/, ["煤炭"]],
  [/通信|光模块|CPO|算力/i, ["通信", "5G", "人工智能"]],
  [/软件|IT服务|信创/i, ["软件", "计算机"]],
  [/互联网|电商/, ["互联网"]],
  [/人工智能|机器人|AI应用/i, ["人工智能", "机器人"]],
  [/银行/, ["银行"]],
  [/证券|券商/, ["证券"]],
  [/保险|多元金融/, ["金融"]],
  [/医药|制药|生物|医疗|创新药/, ["医药", "医疗", "创新药"]],
  [/航天|航空|军工|国防|船舶/, ["军工", "国防"]],
  [/汽车|智驾|智能驾驶/, ["汽车", "智能汽车"]],
  [/机械|设备|制造|工业母机/, ["机械", "高端装备"]],
  [/传媒|影视|游戏|文化/, ["传媒", "游戏"]],
  [/家电|白色家电/, ["家电"]],
  [/食品|饮料|白酒|乳业|消费/, ["食品", "消费"]],
  [/房地产|地产/, ["房地产"]],
  [/建筑|建材|水泥|玻璃/, ["建材", "基建"]],
  [/钢铁/, ["钢铁"]],
  [/环保/, ["环保"]],
  [/旅游|酒店/, ["旅游"]],
  [/航空机场|航运|物流|运输/, ["交通运输"]],
];
export function matchEtfs(
  name: string,
  rows: NonNullable<Etfs["rows"]>,
  memberCodes: string[] = [],
  portfolios: NonNullable<EtfHoldings["rows"]> = [],
) {
  const direct = name.replace(/概念|行业|板块/g, "").trim();
  const themes = [
    ...new Set(
      etfThemes
        .filter(([pattern]) => pattern.test(name))
        .flatMap(([, words]) => words),
    ),
  ];
  const codes = new Set(memberCodes);
  return rows
    .filter((e) => /ETF/i.test(e.name))
    .flatMap((e) => {
      const p = portfolios.find((p) => p.code === e.code);
      const overlap = p?.holdings.filter((h) => codes.has(h.code)) ?? [];
      const overlapWeight = overlap.reduce((sum, h) => {
        const weight = Number(h.weight);
        return sum + (Number.isFinite(weight) && weight > 0 ? weight : 0);
      }, 0);
      const exact = direct.length >= 2 && e.name.includes(direct);
      const theme = themes.find((w) => e.name.includes(w));
      if (!exact && !theme && (overlap.length < 3 || overlapWeight < 20))
        return [];
      return [
        {
          ...e,
          matchReason: exact
            ? "名称对应"
            : theme
              ? `上位主题 · ${theme}`
              : `披露重仓重合 · ${overlap.length}只 / ${overlapWeight.toFixed(1)}%`,
          matchDetail: overlap.length
            ? `${p!.report_date}披露前十大持仓中${overlap.map((h) => h.name).join("、")}与当前板块成分重合，披露净值权重合计${overlapWeight.toFixed(2)}%；仅披露样本，不代表完整持仓或实时持仓比例`
            : "按名称和人工产业主题匹配，不代表实际持仓比例",
          score: exact ? 3 : theme ? 2 : 1,
          overlap: overlap.length,
          overlapWeight,
        },
      ];
    })
    .sort(
      (a, b) =>
        b.score - a.score ||
        b.overlap - a.overlap ||
        Number(b.amount ?? -Infinity) - Number(a.amount ?? -Infinity),
    );
}

export function wan(value: unknown, signed = false) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return (
    (signed && n > 0 ? "+" : "") +
    (n / 10000).toLocaleString("zh-CN", {
      maximumFractionDigits: 1,
      minimumFractionDigits: 1,
    })
  );
}

// 二分矩形布局：面积严格与成交额权重一致，零/缺失金额不进入图。
export function boardTiles(
  boards: Board[],
  canvasWidth = 900,
  canvasHeight = 330,
  weight: "amount" | "equal" = "amount",
) {
  const value = (b: Board) => (weight === "equal" ? 1 : Number(b.amount));
  const input = boards
    .filter(
      (b) =>
        weight === "equal" ||
        (b.amount != null &&
          Number.isFinite(Number(b.amount)) &&
          Number(b.amount) > 0),
    )
    .sort((a, b) => value(b) - value(a));
  const result: {
    board: Board;
    x: number;
    y: number;
    width: number;
    height: number;
  }[] = [];
  function split(
    rows: Board[],
    x: number,
    y: number,
    width: number,
    height: number,
  ) {
    if (!rows.length) return;
    if (rows.length === 1) {
      result.push({ board: rows[0]!, x, y, width, height });
      return;
    }
    const total = rows.reduce((sum, row) => sum + value(row), 0);
    let running = 0,
      index = 0;
    while (index < rows.length - 1 && running < total / 2)
      running += value(rows[index++]!);
    const ratio = running / total;
    // 按实际宽扁容器的比例分割，避免百分比坐标被误当作正方形。
    if (width / height > 1) {
      split(rows.slice(0, index), x, y, width * ratio, height);
      split(
        rows.slice(index),
        x + width * ratio,
        y,
        width * (1 - ratio),
        height,
      );
    } else {
      split(rows.slice(0, index), x, y, width, height * ratio);
      split(
        rows.slice(index),
        x,
        y + height * ratio,
        width,
        height * (1 - ratio),
      );
    }
  }
  split(input, 0, 0, canvasWidth, canvasHeight);
  return result.map((tile) => ({
    ...tile,
    x: (tile.x / canvasWidth) * 100,
    y: (tile.y / canvasHeight) * 100,
    width: (tile.width / canvasWidth) * 100,
    height: (tile.height / canvasHeight) * 100,
  }));
}
