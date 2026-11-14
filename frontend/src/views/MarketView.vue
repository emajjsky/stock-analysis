<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { Search, RefreshCw, ArrowLeftRight } from "lucide-vue-next";
import { api } from "../api";
import { addWatch, state } from "../state";
import { date, direction, money } from "../format";
import { percent, type Intraday } from "../terminal";
import type { Bars, Security, Meta } from "../types";
import {
  wan,
  type BoardList,
  type BoardPositions,
  type BoardMembers,
  type BoardChart,
  type BoardCache,
  type Rotation,
  type BoardNews,
  type BoardFinancial,
  type Futures,
  type ConvertibleBonds,
  type Etfs,
  type EtfHoldings,
  boardBreadth,
  bondBreadth,
  membersForBoard,
} from "../boards";
import BoardMiniChart from "../components/BoardMiniChart.vue";
import BoardDataTable, {
  type MarketColumn,
} from "../components/BoardDataTable.vue";
import { catalogColumnWidths as getCatalogColumnWidths, catalogColumnsFor, readCatalogColumnKeys } from "../catalogColumns";
import BoardMetricChart from "../components/BoardMetricChart.vue";
import BoardHeatmap from "../components/BoardHeatmap.vue";
import EtfCandidates from "../components/EtfCandidates.vue";
defineEmits<{ open: [id: string] }>();
type View =
  | "hot"
  | "rotation"
  | "heat"
  | "funds"
  | "position"
  | "bond"
  | "futures"
  | "catalog";
const tabs = [
  { id: "catalog", label: "证券目录" },
  { id: "hot", label: "板块热点" },
  { id: "rotation", label: "板块轮动" },
  { id: "heat", label: "板块分析" },
  { id: "funds", label: "板块资金" },
  { id: "position", label: "板块增仓" },
  { id: "bond", label: "债股联动" },
  { id: "futures", label: "期股联动" },
] as const;
const view = ref<View>("catalog"),
  kind = ref<"industry" | "concept">("industry"),
  query = ref("");
const listing = ref<BoardList>(),
  positions = ref<BoardPositions>(),
  members = ref<BoardMembers>(),
  boardChart = ref<BoardChart>(),
  fundsChart = ref<BoardChart>(),
  dailyChart = ref<BoardChart>(),
  benchmark = ref<BoardChart>();
const news = ref<BoardNews>(),
  financial = ref<BoardFinancial>(),
  futures = ref<Futures>(),
  convertibles = ref<ConvertibleBonds>(),
  futureChart = ref<BoardChart>(),
  etfs = ref<Etfs>(),
  etfHoldings = ref<EtfHoldings>();
const rotation = ref<Rotation>(),
  boardCode = ref(""),
  stockId = ref(""),
  futureId = ref(""),
  bondId = ref("");
const boardMode = ref<"intraday" | "daily">("intraday"),
  stockMode = ref<"intraday" | "daily">("intraday"),
  futureMode = ref<"intraday" | "daily">("daily");
const stockChart = ref<{
  points?: Intraday["points"];
  bars?: Bars["bars"];
  trade_date?: string;
  source?: string;
  source_time?: string | null;
}>();
const listError = ref(""),
  memberError = ref(""),
  stockError = ref(""),
  featureErrors = ref<Record<string, string>>({});
const featureErrorForView = computed(() => {
  const lanes: Record<View, string[]> = {
    hot: ["etfs", "etfHoldings", "news", "marketNews"],
    rotation: ["rotation"],
    heat: [
      "news",
      "marketNews",
      "financial",
      "dailyChart",
      "fundsChart",
      "benchmark",
    ],
    funds: ["fundsChart"],
    position: ["positions", "fundsChart"],
    bond: ["convertibles"],
    futures: ["futures", "futureChart"],
    catalog: ["catalog"],
  };
  return (
    lanes[view.value]
      .filter((lane) => lane !== "marketNews" || newsTab.value === "market")
      .filter((lane) => lane !== "news" || newsTab.value === "board")
      .map((lane) => featureErrors.value[lane])
      .find(Boolean) ?? ""
  );
});
const marketNotice = computed(() => {
  if (featureErrorForView.value) return featureErrorForView.value;
  if (view.value === "catalog") {
    if (catalogStatus.value?.error) return catalogStatus.value.error;
    if (catalogStatus.value?.enabled === false) return "行情自动更新已关闭，可在设置 → 行情中开启。";
  }
  if (view.value !== "bond" && view.value !== "catalog" && listError.value)
    return listError.value;
  const cache =
    view.value === "bond"
      ? convertibles.value
      : view.value === "futures"
        ? futures.value
        : view.value === "position"
          ? positions.value
          : view.value === "catalog"
            ? undefined
            : listing.value;
  if (cache?.error) return cache.error;
  if (cache?.enabled === false)
    return "行情自动更新已关闭，可在设置 → 行情中开启。";
  return "";
});
const stockReady = ref(false),
  stockBusy = ref(false),
  refreshBusy = ref(false),
  coverageOpen = ref(false);
const rotationDays = ref(10),
  rotationTop = ref(10),
  rotationSort = ref<"change_pct" | "amount">("change_pct");
const fundPeriod = ref<"today" | "3d" | "5d" | "10d">("today"),
  fundDetails = ref(false),
  memberDetails = ref(false),
  newsTab = ref<"board" | "market">("board");
const positionPeriod = ref<"today" | "2d" | "3d">("today");
const marketNews = ref<{
  items?: {
    id: string;
    title: string;
    url?: string | null;
    published_at?: string | null;
    summary?: string;
  }[];
}>();
const futureQuery = ref(""),
  futureActiveOnly = ref(true),
  compareIndex = ref(true),
  stockHeatMetric = ref<"amount" | "volume">("amount");
const catalogQuery = ref(""),
  catalogRows = ref<Security[]>([]),
  catalogOffset = ref(0);
const catalogColumnKeys = readCatalogColumnKeys();
const catalogStatus = ref<Meta['catalog_quotes']>();
const catalogQuoteTime = computed(() => {
  const times = catalogRows.value.map(row => row.quote?.as_of).filter((t): t is string => Boolean(t));
  return times.length ? [...times].sort()[0] : null;
});
const catalogColumns = computed(() => catalogColumnsFor(catalogColumnKeys));
const catalogWidths = computed(() => getCatalogColumnWidths(catalogColumns.value));
const catalogTableRows = computed(() => catalogRows.value.map((security) => {
  const quote = security.quote ?? state.watchlists.find(item => item.security_id === security.id)?.security.quote ?? null;
  return {
    id: security.id,
    code: security.code,
    name: security.name,
    ...quote,
    quote,
    security: { ...security, quote },
    watched: state.watchlists.some(item => item.security_id === security.id),
  };
}));
const controllers = new Map<string, AbortController>();
let stopped = false,
  polling = false,
  timer: ReturnType<typeof setTimeout> | undefined,
  searchTimer: ReturnType<typeof setTimeout> | undefined;
const etfHoldingsError = ref("");
const selected = computed(() =>
  listing.value?.rows?.find((b) => b.code === boardCode.value),
);
const future = computed(() =>
  futures.value?.rows?.find((f) => f.id === futureId.value),
);
const selectedBond = computed(() =>
  convertibles.value?.rows?.find((b) => b.id === bondId.value),
);
const bondDistribution = computed(() =>
  bondBreadth(convertibles.value?.rows ?? []),
);
const currentMembers = computed(() =>
  membersForBoard(boardCode.value, members.value),
);
const stockRows = computed(() =>
  (currentMembers.value?.rows ?? []).map((s) => ({
    ...s,
    ...s.quote,
    watched: state.watchlists.some((w) => w.security_id === s.id),
  })),
);
const stock = computed(() =>
  currentMembers.value?.rows?.find((s) => s.id === stockId.value),
);
const sourceTime = computed(() =>
  view.value === "catalog"
    ? ""
    : view.value === "bond"
      ? (convertibles.value?.rows ?? []).reduce(
          (t, b) => (b.source_time && b.source_time > t ? b.source_time : t),
          "",
        )
      : listing.value?.rows?.reduce(
          (t, b) => (b.source_time && b.source_time > t ? b.source_time : t),
          "",
        ),
);
const boards = computed(() =>
  (view.value === "position"
    ? (positions.value?.rows ?? [])
    : (listing.value?.rows ?? [])
  )
    .filter(
      (b) =>
        !query.value ||
        (b.name + b.code).toLowerCase().includes(query.value.toLowerCase()),
    )
    .map((b) => ({ ...b, id: b.code, leader_name: b.leader?.name })),
);
const futureRows = computed(() =>
  (futures.value?.rows ?? []).filter(
    (f) =>
      (!futureQuery.value ||
        (f.name + f.code + (f.theme ?? ""))
          .toLowerCase()
          .includes(futureQuery.value.toLowerCase())) &&
      (!futureActiveOnly.value || Number(f.volume) > 10000),
  ),
);
const rankedDays = computed(() =>
  (rotation.value?.days ?? [])
    .slice(0, rotationDays.value)
    .map((d) => ({
      ...d,
      rows: [...d.rows]
        .sort(
          (a, b) =>
            Number(b[rotationSort.value] ?? -Infinity) -
            Number(a[rotationSort.value] ?? -Infinity),
        )
        .slice(0, rotationTop.value),
    }))
    .reverse(),
);
const appearances = computed(() => {
  const counts = new Map<
    string,
    { code: string; name: string; count: number }
  >();
  rankedDays.value.forEach((day) =>
    day.rows.forEach((b) => {
      const row = counts.get(b.code) ?? {
        code: b.code,
        name: b.name,
        count: 0,
      };
      row.count++;
      counts.set(b.code, row);
    }),
  );
  return [...counts.values()]
    .sort((a, b) => b.count - a.count)
    .slice(0, rotationTop.value);
});
const netKey = computed(() =>
  fundPeriod.value === "today" ? "net_inflow" : `net_${fundPeriod.value}`,
);
const ratioKey = computed(() =>
  fundPeriod.value === "today" ? "net_ratio" : `ratio_${fundPeriod.value}`,
);
const baseColumns: MarketColumn[] = [
  { key: "name", label: "板块名称" },
  { key: "change_pct", label: "涨跌幅", format: "percent", color: true },
  { key: "speed", label: "1分钟涨速", format: "percent", color: true },
  {
    key: "net_inflow",
    label: "主力净额",
    unit: "万元",
    format: "signedWan",
    color: true,
  },
  { key: "amount", label: "成交额", unit: "万元", format: "wan" },
  { key: "advancing", label: "涨家数", format: "number" },
  { key: "declining", label: "跌家数", format: "number" },
];
const boardColumns = computed<MarketColumn[]>(() =>
  view.value === "position"
    ? [
        baseColumns[0]!,
        baseColumns[1]!,
        ...(["today", "2d", "3d"] as const).flatMap((p) => [
          {
            key: "position_" + p,
            label: (p === "today" ? "今日" : p.replace("d", "日")) + "增仓",
            format: "percent" as const,
            color: true,
          },
          {
            key: "rank_" + p,
            label: (p === "today" ? "今日" : p.replace("d", "日")) + "排名",
            format: "number" as const,
          },
        ]),
      ]
    : view.value === "funds"
      ? [
          baseColumns[0]!,
          baseColumns[1]!,
          {
            key: netKey.value,
            label: `${fundPeriod.value === "today" ? "今日" : fundPeriod.value.replace("d", "日")}净额`,
            unit: "万元",
            format: "signedWan",
            color: true,
          },
          {
            key: ratioKey.value,
            label: "净额占比",
            format: "percent",
            color: true,
          },
          ...(fundDetails.value
            ? ["super_net", "large_net", "medium_net", "small_net"].map(
                (key, i) => ({
                  key,
                  label: ["今日超大单", "今日大单", "今日中单", "今日小单"][i]!,
                  format: "signedWan" as const,
                  unit: "万元",
                  color: true,
                }),
              )
            : ["net_3d", "net_5d", "net_10d"]
                .filter((k) => k !== netKey.value)
                .map((key) => ({
                  key,
                  label: key.replace("net_", "").replace("d", "日") + "净额",
                  format: "signedWan" as const,
                  unit: "万元",
                  color: true,
                }))),
        ]
      : baseColumns,
);
const memberColumns = computed<MarketColumn[]>(() => [
  { key: "name", label: "股票名称" },
  { key: "code", label: "代码" },
  { key: "change_pct", label: "涨跌幅", format: "percent", color: true },
  { key: "price", label: "现价", format: "price" },
  ...(view.value === "funds"
    ? [
        {
          key: netKey.value,
          label: "主力净额",
          unit: "万元",
          format: "signedWan" as const,
          color: true,
        },
        {
          key: ratioKey.value,
          label: "净额占比",
          format: "percent" as const,
          color: true,
        },
      ]
    : [
        {
          key: "amount",
          label: "成交额",
          unit: "万元",
          format: "wan" as const,
        },
        { key: "turnover_rate", label: "换手率", format: "percent" as const },
      ]),
  ...(memberDetails.value
    ? [
        {
          key: "speed",
          label: "1分钟涨速",
          format: "percent" as const,
          color: true,
        },
        {
          key: "volume",
          label: "成交量",
          unit: "股",
          format: "number" as const,
        },
        { key: "volume_ratio", label: "量比", format: "price" as const },
        { key: "amplitude", label: "振幅", format: "percent" as const },
        {
          key: "net_inflow",
          label: "今日主力净额",
          unit: "万元",
          format: "signedWan" as const,
          color: true,
        },
        { key: "pe_dynamic", label: "动态PE", format: "price" as const },
        { key: "pb", label: "市净率", format: "price" as const },
      ]
    : []),
]);
const futureColumns: MarketColumn[] = [
  { key: "code", label: "代码" },
  { key: "name", label: "合约名称" },
  { key: "change_pct", label: "涨跌幅", format: "percent", color: true },
  { key: "price", label: "现价", format: "price" },
  { key: "change", label: "涨跌", format: "price", color: true },
  { key: "volume", label: "成交量", unit: "张", format: "number" },
  { key: "theme", label: "A股关联主题" },
  { key: "bid", label: "买价", format: "price" },
  { key: "ask", label: "卖价", format: "price" },
  { key: "open_interest", label: "持仓量", unit: "张", format: "number" },
  {
    key: "interest_change",
    label: "增仓",
    unit: "张",
    format: "number",
    color: true,
  },
];
const bondRows = computed(() =>
  (convertibles.value?.rows ?? []).filter(
    (b) =>
      !query.value ||
      (b.name + b.code + b.stock_name + b.stock_code)
        .toLowerCase()
        .includes(query.value.toLowerCase()),
  ),
);
const bondColumns: MarketColumn[] = [
  { key: "name", label: "可转债" },
  { key: "code", label: "债券代码" },
  { key: "price", label: "现价", format: "price" },
  { key: "change_pct", label: "债券涨幅", format: "percent", color: true },
  { key: "stock_name", label: "正股" },
  { key: "stock_code", label: "正股代码" },
  {
    key: "stock_change_pct",
    label: "正股涨幅",
    format: "percent",
    color: true,
  },
  {
    key: "change_spread",
    label: "涨跌差",
    unit: "百分点",
    format: "point",
    color: true,
  },
  { key: "amount", label: "成交额", unit: "万元", format: "wan" },
];
const memberBreadth = computed(() => {
  return boardBreadth(
    stockRows.value,
    selected.value,
    currentMembers.value?.total,
  );
});
function breadthShare(value: number, total: number) {
  return total > 0 ? `${((value / total) * 100).toFixed(1)}%` : "—";
}
const historyBars = computed(() => (dailyChart.value?.bars ?? []).slice(-30));
const metricSeries = computed(() => [
  {
    name: "成交额 / 万元",
    color: "#467ba5",
    type: "bar" as const,
    values: historyBars.value
      .filter((b) => b.amount != null)
      .map((b) => ({ time: b.time, value: Number(b.amount) / 10000 })),
  },
  {
    name: "主力净额 / 万元",
    color: "#bd6768",
    type: "bar" as const,
    values: (fundsChart.value?.flows ?? [])
      .filter((f) => f.net_inflow != null)
      .map((f) => ({ time: f.time, value: Number(f.net_inflow) / 10000 })),
  },
  {
    name: "换手率 % · 左轴",
    color: "#bd922e",
    type: "line" as const,
    scale: "left",
    values: historyBars.value
      .filter((b) => (b as any).turnover_rate != null)
      .map((b) => ({ time: b.time, value: Number((b as any).turnover_rate) })),
  },
]);
const heatSeries = computed(() => {
  const bars = historyBars.value;
  return [
    {
      name: "成交额历史分位 %",
      color: "#487fa3",
      type: "line" as const,
      values: bars
        .filter((b) => b.amount != null)
        .map((b) => ({
          time: b.time,
          value:
            (bars.filter(
              (r) => r.amount != null && Number(r.amount) <= Number(b.amount),
            ).length /
              bars.filter((r) => r.amount != null).length) *
            100,
        })),
    },
  ];
});
const fundSeries = computed(() => [
  {
    name: "主力净额 / 万元",
    color: "#bd6768",
    type: "bar" as const,
    values: (fundsChart.value?.flows ?? [])
      .filter((f) => f.net_inflow != null)
      .map((f) => ({ time: f.time, value: Number(f.net_inflow) / 10000 })),
  },
]);
const heatStocks = computed(() =>
  [...stockRows.value]
    .filter(
      (s) =>
        s[stockHeatMetric.value] != null &&
        Number(s[stockHeatMetric.value]) > 0,
    )
    .sort(
      (a, b) =>
        Number(b[stockHeatMetric.value]) - Number(a[stockHeatMetric.value]),
    )
    .slice(0, 12),
);
const financialLabels = [
  { key: "roe", name: "盈利能力 · ROE" },
  { key: "margin", name: "销售毛利率" },
  { key: "debt_ratio", name: "资产负债率" },
  { key: "revenue_yoy", name: "营收同比" },
  { key: "profit_yoy", name: "净利润同比" },
];
function message(cache?: Partial<BoardCache>) {
  if (!cache) return "正在读取数据…";
  if (cache.error) return cache.error;
  if (cache.enabled === false) return "行情自动更新已关闭，请到设置开启";
  if (cache.status === "LOADING" || cache.refreshing)
    return "正在连接真实数据源…";
  return "暂无可用数据";
}
function ctrl(lane: string) {
  controllers.get(lane)?.abort();
  const c = new AbortController();
  controllers.set(lane, c);
  return c;
}
function stable<T>(target: { value: T | undefined }, value: T) {
  if (JSON.stringify(target.value) !== JSON.stringify(value))
    target.value = value;
}
async function feature<T>(
  lane: string,
  path: string,
  target: { value: T | undefined },
) {
  const c = ctrl(lane);
  if (lane === "etfHoldings") etfHoldingsError.value = "";
  try {
    const r = await api<T>(path, { signal: c.signal });
    if (!stopped && !c.signal.aborted) {
      const nextErrors = { ...featureErrors.value };
      delete nextErrors[lane];
      featureErrors.value = nextErrors;
      if (lane === "etfHoldings") etfHoldingsError.value = "";
      stable(target, r.data);
    }
  } catch (e) {
    if (!c.signal.aborted) {
      const message = e instanceof Error ? e.message : "补充数据读取失败";
      featureErrors.value = { ...featureErrors.value, [lane]: message };
      if (lane === "etfHoldings") etfHoldingsError.value = message;
    }
  }
}
async function loadList() {
  const k = kind.value,
    c = ctrl("list");
  try {
    const r = await api<BoardList>(`/market/boards?kind=${k}`, {
      signal: c.signal,
    });
    if (stopped || c.signal.aborted || k !== kind.value) return;
    listing.value = r.data;
    listError.value = "";
    if (view.value === "futures") linkFuture();
    else if (!boardCode.value && boards.value.length)
      boardCode.value = [...boards.value].sort(
        (a, b) =>
          Number(
            Number(b.advancing) + Number(b.declining) >= 5
              ? b.change_pct
              : -Infinity,
          ) -
          Number(
            Number(a.advancing) + Number(a.declining) >= 5
              ? a.change_pct
              : -Infinity,
          ),
      )[0]!.code;
  } catch (e) {
    if (!c.signal.aborted) listError.value = String(e);
  }
}
async function loadMembers() {
  if (!boardCode.value) return;
  const code = boardCode.value,
    c = ctrl("members");
  try {
    const r = await api<BoardMembers>(`/market/boards/${code}/members`, {
      signal: c.signal,
    });
    if (stopped || c.signal.aborted || code !== boardCode.value) return;
    members.value = r.data;
    memberError.value = "";
    if (!stockId.value && stockRows.value.length)
      stockId.value = [...stockRows.value].sort(
        (a, b) => Number(b.change_pct) - Number(a.change_pct),
      )[0]!.id;
  } catch (e) {
    if (!c.signal.aborted) memberError.value = String(e);
  }
}
async function loadBoardChart() {
  if (boardCode.value)
    await feature(
      "boardChart",
      `/market/boards/${boardCode.value}/chart?period=${boardMode.value}`,
      boardChart,
    );
}
async function activateStock() {
  const id = stockId.value;
  stockReady.value = false;
  stockChart.value = undefined;
  stockError.value = "";
  controllers.get("stockChart")?.abort();
  if (!id) return;
  const c = ctrl("activate");
  stockBusy.value = true;
  try {
    await api(`/securities/${encodeURIComponent(id)}/activate`, {
      method: "POST",
      body: "{}",
      signal: c.signal,
    });
    if (stopped || c.signal.aborted || id !== stockId.value) return;
    stockReady.value = true;
    await loadStockChart();
  } catch (e) {
    if (!c.signal.aborted) stockError.value = String(e);
  } finally {
    if (!c.signal.aborted) stockBusy.value = false;
  }
}
async function loadStockChart() {
  const id = stockId.value;
  if (!id || !stockReady.value) return;
  const c = ctrl("stockChart"),
    mode = stockMode.value;
  try {
    if (mode === "intraday") {
      const { data } = await api<Intraday>(
        `/market/intraday?security_id=${encodeURIComponent(id)}`,
        { signal: c.signal },
      );
      if (!c.signal.aborted && id === stockId.value) {
        stable(stockChart, {
          points: data.points,
          source: data.source ?? undefined,
          trade_date: data.trade_date,
          source_time: data.source_time,
        });
        stockError.value = data.error ?? "";
      }
    } else {
      const { data } = await api<Bars>(
        `/market/bars?security_id=${encodeURIComponent(id)}&timeframe=1d&adjustment=none`,
        { signal: c.signal },
      );
      if (!c.signal.aborted && id === stockId.value)
        stable(stockChart, {
          bars: data.bars,
          source: data.history_source ?? undefined,
        });
    }
  } catch (e) {
    if (!c.signal.aborted) stockError.value = String(e);
  }
}
async function supplements() {
  const jobs: Promise<unknown>[] = [];
  if (view.value === "position")
    jobs.push(
      feature(
        "positions",
        `/market/boards/positions?kind=${kind.value}`,
        positions,
      ),
    );
  if (view.value === "hot")
    jobs.push(
      feature("etfs", "/market/etfs", etfs),
      feature("etfHoldings", "/market/etfs/holdings", etfHoldings),
    );
  if (view.value === "bond")
    jobs.push(
      feature("convertibles", "/market/bonds/convertible", convertibles),
    );
  if (["hot", "heat"].includes(view.value) && boardCode.value) {
    jobs.push(feature("news", `/market/boards/${boardCode.value}/news`, news));
    if (newsTab.value === "market")
      jobs.push(feature("marketNews", "/market/news?tab=market", marketNews));
  }
  if (view.value === "heat" && boardCode.value)
    jobs.push(
      feature(
        "financial",
        `/market/boards/${boardCode.value}/financial`,
        financial,
      ),
      feature(
        "dailyChart",
        `/market/boards/${boardCode.value}/chart?period=daily`,
        dailyChart,
      ),
      feature(
        "fundsChart",
        `/market/boards/${boardCode.value}/chart?period=funds`,
        fundsChart,
      ),
      feature("benchmark", "/market/boards/benchmark", benchmark),
    );
  if (["funds", "position"].includes(view.value) && boardCode.value)
    jobs.push(
      feature(
        "fundsChart",
        `/market/boards/${boardCode.value}/chart?period=funds`,
        fundsChart,
      ),
    );
  if (view.value === "rotation")
    jobs.push(
      feature(
        "rotation",
        `/market/boards/rotation/history?kind=${kind.value}`,
        rotation,
      ),
    );
  if (view.value === "futures") {
    jobs.push(feature("futures", "/market/futures", futures));
    if (futureId.value)
      jobs.push(
        feature(
          "futureChart",
          `/market/futures/${encodeURIComponent(futureId.value)}/chart?period=${futureMode.value}`,
          futureChart,
        ),
      );
  }
  await Promise.allSettled(jobs);
}
async function poll() {
  if (stopped || polling) return;
  polling = true;
  try {
    if (view.value === "catalog") await loadCatalog();
    else if (view.value === "bond") await supplements();
    else
      await Promise.allSettled([
        loadList(),
        loadMembers(),
        loadBoardChart(),
        loadStockChart(),
        supplements(),
      ]);
  } finally {
    polling = false;
    if (!stopped) timer = setTimeout(poll, view.value === "catalog" ? 5000 : 3000);
  }
}
async function refreshVisible() {
  if (refreshBusy.value) return;
  refreshBusy.value = true;
  try {
    await api(
      `/market/boards/refresh?kind=${kind.value}&period=${boardMode.value}${view.value !== "bond" && boardCode.value ? "&code=" + boardCode.value : ""}${view.value !== "catalog" ? "&section=" + view.value : ""}${view.value === "futures" && futureId.value ? "&future_id=" + encodeURIComponent(futureId.value) + "&future_period=" + futureMode.value : ""}`,
      { method: "POST", body: "{}" },
    );
    if (view.value !== "bond" && stockId.value)
      await api(
        `/market/refresh?security_id=${encodeURIComponent(stockId.value)}`,
        { method: "POST", body: "{}" },
      );
    if (view.value === "bond") await supplements();
    else
      await Promise.allSettled([
        loadList(),
        loadMembers(),
        loadBoardChart(),
        loadStockChart(),
        supplements(),
      ]);
  } catch (e) {
    listError.value = String(e);
  } finally {
    refreshBusy.value = false;
  }
}
function chooseBoard(code: string) {
  if (listing.value?.rows?.some((b) => b.code === code)) boardCode.value = code;
}
function linkFuture() {
  const f = future.value;
  if (!f) return;
  const match = f.theme_keywords
    .map((w) => listing.value?.rows?.find((b) => b.name.includes(w)))
    .find(Boolean);
  boardCode.value = match?.code ?? "";
}
function tileColor(b: { change_pct?: string | null }) {
  const n = Number(b.change_pct);
  return b.change_pct == null || !n
    ? "#8b8b7c"
    : n > 0
      ? `hsl(355 48% ${Math.max(36, 61 - Math.abs(n) * 3)}%)`
      : `hsl(155 35% ${Math.max(28, 48 - Math.abs(n) * 2)}%)`;
}
function points(value: string | null | undefined) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? `${n > 0 ? "+" : ""}${n.toFixed(2)} 个百分点`
    : "—";
}
async function loadCatalog() {
  const q = catalogQuery.value.trim();
  const c = ctrl("catalog");
  try {
    const r = await api<Security[]>(q ? `/securities?q=${encodeURIComponent(q)}`
      : `/securities?catalog=true&limit=100&offset=${catalogOffset.value}`, { signal: c.signal });
    if (stopped || c.signal.aborted) return;
    stable(catalogRows, r.data);
    catalogStatus.value = r.meta.catalog_quotes;
    const errors = { ...featureErrors.value };
    delete errors.catalog;
    featureErrors.value = errors;
  } catch (e) {
    if (!c.signal.aborted) featureErrors.value = { ...featureErrors.value,
      catalog: e instanceof Error ? e.message : "行情缓存读取失败" };
  }
}
watch(kind, () => {
  controllers.forEach((c) => c.abort());
  listing.value = undefined;
  rotation.value = undefined;
  positions.value = undefined;
  boardCode.value = "";
  query.value = "";
  void loadList();
  void supplements();
});
watch(boardCode, () => {
  [
    "members",
    "boardChart",
    "news",
    "financial",
    "dailyChart",
    "fundsChart",
  ].forEach((k) => controllers.get(k)?.abort());
  members.value = undefined;
  boardChart.value = undefined;
  news.value = undefined;
  financial.value = undefined;
  dailyChart.value = undefined;
  fundsChart.value = undefined;
  stockId.value = "";
  memberError.value = "";
  void loadMembers();
  void loadBoardChart();
  void supplements();
});
watch(stockId, activateStock);
watch(boardMode, () => {
  boardChart.value = undefined;
  void loadBoardChart();
});
watch(stockMode, () => {
  stockChart.value = undefined;
  void loadStockChart();
});
watch([futureId, futureMode], () => {
  controllers.get("futureChart")?.abort();
  futureChart.value = undefined;
  linkFuture();
  void supplements();
});
watch(futures, () => {
  if (!futureId.value && futureRows.value.length)
    futureId.value = [...futureRows.value].sort(
      (a, b) => Number(b.volume) - Number(a.volume),
    )[0]!.id;
});
watch([bondRows, view], () => {
  if (
    view.value === "bond" &&
    !bondRows.value.some((b) => b.id === bondId.value)
  )
    bondId.value =
      [...bondRows.value].sort(
        (a, b) => Number(b.amount ?? -Infinity) - Number(a.amount ?? -Infinity),
      )[0]?.id ?? "";
});
watch(newsTab, supplements);
watch(view, (v) => {
  query.value = "";
  if (v === "futures") {
    kind.value = "industry";
    stockMode.value = "daily";
  }
  if (v === "catalog") void loadCatalog();
  else void supplements();
});
watch(catalogQuery, () => {
  clearTimeout(searchTimer);
  catalogOffset.value = 0;
  searchTimer = setTimeout(loadCatalog, 200);
});
watch(catalogOffset, loadCatalog);
onMounted(poll);
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  clearTimeout(searchTimer);
  controllers.forEach((c) => c.abort());
});
</script>

<template>
  <section class="market-page">
    <header class="market-toolbar">
      <div class="market-heading">
        <h1>市场</h1>
        <div
          v-if="!['bond', 'futures', 'catalog'].includes(view)"
          class="switch-group"
          aria-label="板块分类"
        >
          <button
            :class="{ active: kind === 'industry' }"
            @click="kind = 'industry'"
          >
            行业</button
          ><button
            :class="{ active: kind === 'concept' }"
            @click="kind = 'concept'"
          >
            概念
          </button>
        </div>
      </div>
      <div class="toolbar-actions">
        <time v-if="sourceTime">{{
          date(view === "futures" ? (future?.source_time ?? null) : sourceTime)
        }}</time
        ><button
          v-if="view !== 'catalog'"
          class="icon-button"
          aria-label="刷新行情"
          title="刷新当前板块及个股"
          :disabled="refreshBusy"
          @click="refreshVisible"
        >
          <RefreshCw :size="16" :class="{ spinning: refreshBusy }" /></button
        ><button class="subtle-button" @click="coverageOpen = true">
          功能与数据
        </button>
      </div>
    </header>
    <div class="market-tabbar">
      <div class="market-tabs" role="tablist" aria-label="市场视图">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          role="tab"
          :aria-selected="view === tab.id"
          :class="{ active: view === tab.id }"
          @click="view = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>
    <div v-if="marketNotice" class="market-notice" role="status">
      {{ marketNotice }}
    </div>
    <BoardHeatmap
      v-if="view === 'heat'"
      :boards="listing?.rows ?? []"
      :selected="boardCode"
      :kind="kind"
      :cache="listing"
      @select="chooseBoard"
    />

    <div
      v-if="view !== 'catalog'"
      class="market-workspace"
      :class="[
        `layout-${view}`,
        {
          'without-news': [
            'rotation',
            'funds',
            'futures',
            'position',
            'bond',
          ].includes(view),
        },
      ]"
    >
      <div class="market-left">
        <section v-if="view !== 'heat'" class="market-panel board-top-panel">
          <header class="panel-head">
            <strong>{{
              view === "rotation"
                ? "交易日排行榜"
                : view === "funds"
                  ? "板块资金排行"
                  : view === "position"
                    ? "板块增仓排行"
                    : view === "bond"
                      ? "可转债与正股"
                      : view === "futures"
                        ? "国内期货合约"
                        : "板块排行榜"
            }}</strong
            ><label
              v-if="!['rotation', 'futures'].includes(view)"
              class="market-search"
              ><Search :size="13" /><input
                v-model="query"
                :aria-label="view === 'bond' ? '搜索可转债与正股' : '搜索板块'"
                :placeholder="
                  view === 'bond' ? '债券 / 正股名称或代码' : '搜索板块 / 代码'
                " /></label
            ><label v-if="view === 'futures'" class="market-search"
              ><Search :size="13" /><input
                v-model="futureQuery"
                aria-label="搜索期货"
                placeholder="合约 / 主题"
            /></label>
          </header>

          <template v-if="view === 'rotation'">
            <div class="rotation-controls">
              <label
                >交易日
                <select v-model="rotationDays" aria-label="轮动交易日">
                  <option :value="5">5日</option>
                  <option :value="10">10日</option>
                </select></label
              ><label
                >榜单
                <select v-model="rotationTop" aria-label="轮动榜单">
                  <option :value="10">前10名</option>
                  <option :value="20">前20名</option>
                </select></label
              ><label
                >排序
                <select v-model="rotationSort" aria-label="轮动排序">
                  <option value="change_pct">涨跌幅</option>
                  <option value="amount">成交额</option>
                </select></label
              ><span v-if="rotation?.refreshing" class="progress-text"
                >真实日K回填 {{ rotation?.progress?.completed ?? 0 }}/{{
                  rotation?.progress?.total ?? listing?.total ?? "—"
                }}</span
              >
            </div>
            <div class="rotation-body">
              <div class="rotation-frequency">
                <strong>上榜次数</strong
                ><button
                  v-for="b in appearances"
                  :key="b.code"
                  :class="{ selected: b.code === boardCode }"
                  :title="b.name"
                  @click="chooseBoard(b.code)"
                >
                  <span>{{ b.name }}</span
                  ><b>{{ b.count }}</b>
                </button>
              </div>
              <div class="rotation-scroll">
                <div
                  v-if="rankedDays.length"
                  class="rotation-grid"
                  :style="{
                    gridTemplateColumns: `repeat(${rankedDays.length},minmax(66px,1fr))`,
                  }"
                >
                  <div
                    v-for="day in rankedDays"
                    :key="day.date"
                    class="rotation-day"
                  >
                    <div class="rotation-date">{{ day.date.slice(5) }}</div>
                    <button
                      v-for="(b, i) in day.rows"
                      :key="b.code"
                      :class="{ selected: boardCode === b.code }"
                      :title="`${day.date} 第${i + 1} ${b.name} ${percent(b.change_pct)} 成交额${wan(b.amount)}万元`"
                      @click="chooseBoard(b.code)"
                    >
                      <small>{{ i + 1 }}</small
                      ><strong>{{ b.name }}</strong
                      ><span :class="direction(b.change_pct)">{{
                        rotationSort === "amount"
                          ? wan(b.amount)
                          : percent(b.change_pct)
                      }}</span>
                    </button>
                  </div>
                </div>
                <div v-else class="market-empty">{{ message(rotation) }}</div>
              </div>
            </div>
          </template>

          <template v-else-if="view === 'futures'"
            ><div class="table-options">
              <label
                ><input v-model="futureActiveOnly" type="checkbox" />
                活跃合约（成交量＞1万张）</label
              ><span
                >{{ futureRows.length }} /
                {{ futures?.loaded ?? "—" }} 个合约</span
              >
            </div>
            <BoardDataTable
              :rows="futureRows"
              :columns="futureColumns"
              :selected="futureId"
              initial-sort="change_pct"
              :empty="message(futures)"
              @select="futureId = $event"
            />
          </template>

          <template v-else-if="view === 'bond'"
            ><BoardDataTable
              :rows="bondRows"
              :columns="bondColumns"
              :selected="bondId"
              initial-sort="amount"
              :empty="message(convertibles)"
              @select="bondId = $event"
            />
          </template>

          <template v-else
            ><div
              v-if="view === 'position'"
              class="table-options position-options"
              :title="positions?.formula"
            >
              <div class="switch-group">
                <button
                  v-for="p in [
                    { id: 'today', label: '今日' },
                    { id: '2d', label: '2日' },
                    { id: '3d', label: '3日' },
                  ]"
                  :key="p.id"
                  :class="{ active: positionPeriod === p.id }"
                  @click="positionPeriod = p.id as typeof positionPeriod"
                >
                  {{ p.label }}
                </button>
              </div>
              <span v-if="positions?.refreshing" class="progress-text"
                >历史回填
                {{ positions.progress?.completed ?? positions.covered ?? 0 }}/{{
                  positions.total ?? "—"
                }}</span
              >
              <span v-else-if="positions?.error" class="progress-text">{{
                positions.error
              }}</span>
              <span
                v-else-if="positions && positions.covered !== positions.total"
                class="progress-text"
                title="缺少连续交易日历史的板块不补零；2日排名仅在有值板块中计算，可用刷新重试"
                >2日覆盖 {{ positions.covered }}/{{ positions.total }}</span
              >
            </div>
            <div v-if="view === 'funds'" class="table-options">
              <div class="switch-group">
                <button
                  v-for="p in [
                    { id: 'today', label: '今日' },
                    { id: '3d', label: '3日' },
                    { id: '5d', label: '5日' },
                    { id: '10d', label: '10日' },
                  ]"
                  :key="p.id"
                  :class="{ active: fundPeriod === p.id }"
                  @click="fundPeriod = p.id as typeof fundPeriod"
                >
                  {{ p.label }}
                </button>
              </div>
              <button class="text-button" @click="fundDetails = !fundDetails">
                {{ fundDetails ? "多日趋势" : "按订单大小" }}
              </button>
            </div>
            <BoardDataTable
              :key="'board-' + view + fundPeriod + fundDetails + positionPeriod"
              :rows="boards"
              :columns="boardColumns"
              :selected="boardCode"
              :initial-sort="
                view === 'position'
                  ? 'position_' + positionPeriod
                  : view === 'funds'
                    ? netKey
                    : 'change_pct'
              "
              :empty="
                listing?.rows?.length ? '没有匹配的板块' : message(listing)
              "
              @select="chooseBoard"
            />
          </template>
        </section>

        <section v-if="view !== 'bond'" class="market-panel member-panel">
          <header class="panel-head">
            <strong
              >{{
                selected?.name ?? (view === "futures" ? "关联A股" : "板块")
              }} </strong
            ><button
              class="text-button"
              :class="{ active: memberDetails }"
              @click="memberDetails = !memberDetails"
            >
              {{ memberDetails ? "基础指标" : "更多指标" }}
            </button>
          </header>
          <div v-if="view === 'futures'" class="relation-note">
            {{
              future?.theme
                ? "产业关联：" +
                  future.theme +
                  " → " +
                  (selected?.name ?? "暂无匹配行业")
                : "该合约暂无人工产业关联"
            }}<small>人工主题对应，不代表价格相关性</small>
          </div>
          <BoardDataTable
            :key="'member-' + view + fundPeriod + memberDetails"
            :rows="stockRows"
            :columns="
              view === 'heat' && !memberDetails
                ? [memberColumns[0]!, memberColumns[1]!, memberColumns[2]!]
                : memberColumns
            "
            :selected="stockId"
            :stock="true"
            :empty="
              memberError ||
              (!boardCode
                ? '请选择已接行情的板块或关联主题'
                : message(currentMembers))
            "
            @select="stockId = $event"
            @open="$emit('open', $event)"
            @add="addWatch"
          />
        </section>
      </div>

      <div v-if="view === 'bond'" class="market-center bond-center">
        <section class="market-panel bond-link-panel">
          <header class="panel-head">
            <div class="chart-title">
              <strong>{{ selectedBond?.name ?? "可转债与正股" }}</strong>
              <small>{{ selectedBond?.code ?? "" }}</small>
            </div>
            <span class="bond-source-label">东方财富延时行情</span>
          </header>
          <template v-if="selectedBond">
            <div class="bond-pair-grid">
              <article class="bond-quote bond-quote-bond">
                <span>可转债</span>
                <strong>{{ money(selectedBond.price, 3) }}</strong>
                <b :class="direction(selectedBond.change_pct)">{{
                  percent(selectedBond.change_pct)
                }}</b>
                <small>行情 {{ date(selectedBond.source_time) }}</small>
              </article>
              <div class="bond-link-arrow" aria-hidden="true">
                <ArrowLeftRight :size="18" />
              </div>
              <article class="bond-quote bond-quote-stock">
                <span>对应正股</span>
                <button
                  class="text-button"
                  @click="$emit('open', selectedBond.stock_id)"
                >
                  {{ selectedBond.stock_name }} {{ selectedBond.stock_code }}
                </button>
                <strong>{{ money(selectedBond.stock_price, 3) }}</strong>
                <b :class="direction(selectedBond.stock_change_pct)">{{
                  percent(selectedBond.stock_change_pct)
                }}</b>
                <small>行情 {{ date(selectedBond.stock_source_time) }}</small>
              </article>
            </div>
            <div class="bond-spread">
              <span>当日涨跌差（债券 − 正股）</span>
              <strong :class="direction(selectedBond.change_spread)">{{
                points(selectedBond.change_spread)
              }}</strong>
              <small>不代表统计相关性</small>
            </div>
            <dl class="bond-terms">
              <div>
                <dt>转股状态</dt>
                <dd>
                  {{
                    selectedBond.conversion_state === "BEFORE"
                      ? "未进入转股期"
                      : selectedBond.conversion_state === "ACTIVE"
                        ? "处于转股期"
                        : selectedBond.conversion_state === "ENDED"
                          ? "已过转股期"
                          : "日期未知"
                  }}
                </dd>
              </div>
              <div>
                <dt>转股起始日</dt>
                <dd>{{ date(selectedBond.conversion_start) }}</dd>
              </div>
              <div>
                <dt>发行初始转股价</dt>
                <dd>{{ money(selectedBond.initial_conversion_price, 3) }}</dd>
              </div>
              <div>
                <dt>发行规模</dt>
                <dd>
                  {{
                    selectedBond.issue_scale == null
                      ? "—"
                      : `${money(selectedBond.issue_scale, 2)} 亿元`
                  }}
                </dd>
              </div>
            </dl>
            <p class="bond-source-note">
              转股价可能因公告调整；当前公开条款接口未提供可核验的现行转股价，因此不计算转股价值和溢价率。
            </p>
          </template>
          <div v-else class="market-empty">{{ message(convertibles) }}</div>
        </section>
        <section class="market-panel bond-method-panel">
          <header class="panel-head">
            <strong>债股强弱分布</strong
            ><span class="muted">全部已关联样本 · 只</span>
          </header>
          <dl class="bond-distribution">
            <div>
              <dt>债股同涨</dt>
              <dd class="up">
                {{ convertibles?.rows ? bondDistribution.bothUp : "—" }}
              </dd>
            </div>
            <div>
              <dt>债股同跌</dt>
              <dd class="down">
                {{ convertibles?.rows ? bondDistribution.bothDown : "—" }}
              </dd>
            </div>
            <div>
              <dt>债涨股跌</dt>
              <dd>{{ convertibles?.rows ? bondDistribution.bondUp : "—" }}</dd>
            </div>
            <div>
              <dt>债跌股涨</dt>
              <dd>{{ convertibles?.rows ? bondDistribution.stockUp : "—" }}</dd>
            </div>
            <div>
              <dt>任一平盘</dt>
              <dd>{{ convertibles?.rows ? bondDistribution.flat : "—" }}</dd>
            </div>
            <div>
              <dt>报价不全</dt>
              <dd>{{ convertibles?.rows ? bondDistribution.missing : "—" }}</dd>
            </div>
          </dl>
          <footer>
            {{ convertibles?.loaded ?? "—" }} /
            {{ convertibles?.total ?? "—" }} 只可转债已关联
          </footer>
        </section>
      </div>

      <div v-else class="market-center">
        <section class="market-panel chart-panel main-chart-panel">
          <header class="panel-head">
            <div class="chart-title">
              <strong>{{
                view === "futures"
                  ? (future?.name ?? "期货走势")
                  : (selected?.name ?? "板块走势")
              }}</strong
              ><span
                :class="
                  direction(
                    view === 'futures'
                      ? future?.change_pct
                      : selected?.change_pct,
                  )
                "
                >{{
                  percent(
                    view === "futures"
                      ? future?.change_pct
                      : selected?.change_pct,
                  )
                }}</span
              >
            </div>
            <div class="switch-group">
              <button
                :class="{
                  active:
                    (view === 'futures' ? futureMode : boardMode) ===
                    'intraday',
                }"
                @click="
                  view === 'futures'
                    ? (futureMode = 'intraday')
                    : (boardMode = 'intraday')
                "
              >
                分时</button
              ><button
                :class="{
                  active:
                    (view === 'futures' ? futureMode : boardMode) === 'daily',
                }"
                @click="
                  view === 'futures'
                    ? (futureMode = 'daily')
                    : (boardMode = 'daily')
                "
              >
                日K
              </button>
            </div>
          </header>
          <div
            class="chart-facts"
            :title="
              view === 'futures'
                ? futureChart?.trade_date
                : boardChart?.trade_date
            "
          >
            <span
              >{{ view === "futures" ? "现价" : "指数" }}
              <b>{{
                money(view === "futures" ? future?.price : selected?.price)
              }}</b></span
            ><span
              >成交额
              <b
                >{{
                  wan(view === "futures" ? future?.amount : selected?.amount)
                }}万</b
              ></span
            ><span v-if="view === 'heat' && boardMode === 'intraday'"
              ><label
                ><input v-model="compareIndex" type="checkbox" />
                对比上证</label
              ></span
            >
          </div>
          <template v-if="view === 'futures'"
            ><div
              v-if="futureChart?.points?.length || futureChart?.bars?.length"
              class="chart-area"
            >
              <BoardMiniChart
                :key="futureId + futureMode"
                :mode="futureMode"
                :points="futureChart.points"
                :bars="futureChart.bars"
                volume-unit="成交量 / 合约张"
              />
            </div>
            <div v-else class="chart-area market-empty">
              {{ message(futureChart) }}
            </div>
          </template>
          <template v-else
            ><div
              v-if="boardChart?.points?.length || boardChart?.bars?.length"
              class="chart-area"
            >
              <BoardMiniChart
                :key="
                  boardCode +
                  boardMode +
                  (view === 'heat' && compareIndex ? 'compare' : 'price')
                "
                :mode="boardMode"
                :points="boardChart.points"
                :bars="boardChart.bars"
                :previous-close="boardChart.previous_close"
                :benchmark="
                  view === 'heat' && compareIndex && boardMode === 'intraday'
                    ? benchmark?.points
                    : undefined
                "
                :benchmark-close="benchmark?.previous_close"
              />
            </div>
            <div v-else class="chart-area market-empty">
              {{ boardCode ? message(boardChart) : "选择板块查看行情" }}
            </div>
          </template>
        </section>

        <template v-if="view === 'heat'"
          ><div class="analysis-charts">
            <section class="market-panel">
              <header class="panel-head">
                <strong>交易活跃度</strong
                ><span
                  class="muted"
                  title="当日成交额在本板块近30个交易日的分位，非同花顺热度评分"
                  >近30日分位</span
                >
              </header>
              <div v-if="historyBars.length" class="metric-area">
                <BoardMetricChart
                  :key="boardCode + 'heat'"
                  :series="heatSeries"
                />
              </div>
              <div v-else class="market-empty">{{ message(dailyChart) }}</div>
            </section>
            <section class="market-panel">
              <header class="panel-head"><strong>资金成交概况</strong></header>
              <div v-if="historyBars.length" class="metric-area">
                <BoardMetricChart
                  :key="boardCode + 'metrics'"
                  :series="metricSeries"
                />
              </div>
              <div v-else class="market-empty">{{ message(dailyChart) }}</div>
            </section>
          </div>
          <section class="market-panel stock-heat-panel">
            <header class="panel-head">
              <strong>个股热力条</strong
              ><select v-model="stockHeatMetric" aria-label="个股热力指标">
                <option value="amount">成交额</option>
                <option value="volume">成交量</option>
              </select>
            </header>
            <div class="stock-heat-strip">
              <button
                v-for="s in heatStocks"
                :key="s.id"
                :style="{
                  flexGrow: Number(s[stockHeatMetric]),
                  background: tileColor(s),
                }"
                :title="`${s.name} ${percent(s.change_pct)} ${stockHeatMetric === 'amount' ? wan(s.amount) + '万元' : Number(s.volume).toLocaleString() + '股'}`"
                @click="
                  stockId = s.id;
                  $emit('open', s.id);
                "
              >
                {{ s.name }}</button
              ><span v-if="!heatStocks.length" class="muted"
                >等待成分股数据</span
              >
            </div>
          </section></template
        >

        <section
          v-else-if="view === 'funds' || view === 'position'"
          class="market-panel funds-history"
        >
          <header class="panel-head">
            <strong title="东方财富主力资金估算，单位万元"
              >近20日主力净额</strong
            >
          </header>
          <div v-if="fundsChart?.flows?.length" class="metric-area">
            <BoardMetricChart :key="boardCode + 'funds'" :series="fundSeries" />
          </div>
          <div v-else class="market-empty">{{ message(fundsChart) }}</div>
        </section>

        <section
          v-if="view !== 'heat'"
          class="market-panel chart-panel stock-chart-panel"
        >
          <header class="panel-head">
            <div class="chart-title">
              <button
                class="text-button stock-title"
                :disabled="!stock"
                @click="stock && $emit('open', stock.id)"
              >
                {{ stock?.name ?? "个股走势" }}</button
              ><span :class="direction(stock?.quote?.change_pct)">{{
                percent(stock?.quote?.change_pct)
              }}</span>
            </div>
            <div class="switch-group">
              <button
                :class="{ active: stockMode === 'intraday' }"
                @click="stockMode = 'intraday'"
              >
                分时</button
              ><button
                :class="{ active: stockMode === 'daily' }"
                @click="stockMode = 'daily'"
              >
                日K
              </button>
            </div>
          </header>
          <div class="chart-facts" :title="stockChart?.trade_date">
            <span>{{ stock?.code ?? "—" }}</span
            ><span
              >最新 <b>{{ money(stock?.quote?.price) }}</b></span
            ><span
              >换手 <b>{{ percent(stock?.quote?.turnover_rate) }}</b></span
            >
          </div>
          <div
            v-if="stockChart?.points?.length || stockChart?.bars?.length"
            class="chart-area"
          >
            <BoardMiniChart
              :key="stockId + stockMode"
              :mode="stockMode"
              :points="stockChart.points"
              :bars="stockChart.bars"
            />
          </div>
          <div v-else class="chart-area market-empty">
            {{
              stockError ||
              (stockBusy || stockReady
                ? "正在获取个股走势…"
                : "选择成分股查看走势")
            }}
          </div>
        </section>

        <EtfCandidates
          v-if="view === 'hot'"
          :key="view + ':' + boardCode"
          :name="selected?.name ?? ''"
          :member-codes="stockRows.map((s) => s.code)"
          :quotes="etfs"
          :portfolios="etfHoldings"
          :portfolios-error="etfHoldingsError"
        />
      </div>

      <aside v-if="['hot', 'heat'].includes(view)" class="market-right">
        <section class="market-panel news-panel">
          <header class="panel-head">
            <div class="switch-group">
              <button
                :class="{ active: newsTab === 'board' }"
                @click="newsTab = 'board'"
              >
                板块资讯</button
              ><button
                :class="{ active: newsTab === 'market' }"
                @click="newsTab = 'market'"
              >
                市场快讯
              </button>
            </div>
          </header>
          <div class="news-list">
            <template v-if="newsTab === 'board'"
              ><article v-for="n in news?.items" :key="n.id">
                <a
                  v-if="n.url"
                  :href="n.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  :title="n.summary"
                  >{{ n.title }}</a
                ><span v-else>{{ n.title }}</span>
                <div>
                  <small>{{ n.media }}</small
                  ><time>{{ date(n.published_at) }}</time>
                </div>
              </article>
              <div v-if="!news?.items?.length" class="market-empty">
                {{ boardCode ? message(news) : "选择已接行情的板块查看资讯" }}
              </div></template
            ><template v-else
              ><article v-for="n in marketNews?.items" :key="n.id">
                <a
                  v-if="n.url"
                  :href="n.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  :title="n.summary"
                  >{{ n.title }}</a
                ><span v-else>{{ n.title }}</span
                ><time>{{ date(n.published_at ?? null) }}</time>
              </article>
              <div v-if="!marketNews?.items?.length" class="market-empty">
                正在读取市场快讯…
              </div></template
            >
          </div>
        </section>
        <section v-if="view === 'heat'" class="market-panel financial-panel">
          <header class="panel-head">
            <strong>财务分析</strong><span class="muted">样本中位数</span>
          </header>
          <div v-if="financial?.metrics" class="financial-content">
            <div
              v-for="m in financialLabels"
              :key="m.key"
              class="financial-metric"
            >
              <div>
                <span>{{ m.name }}</span
                ><b
                  :class="
                    m.key === 'debt_ratio'
                      ? ''
                      : direction(financial.metrics[m.key]?.value)
                  "
                  >{{ percent(financial.metrics[m.key]?.value) }}</b
                >
              </div>
              <div class="financial-track">
                <i
                  :style="{
                    width:
                      Math.min(
                        100,
                        Math.abs(Number(financial.metrics[m.key]?.value ?? 0)),
                      ) + '%',
                    background:
                      m.key === 'debt_ratio'
                        ? '#b28a35'
                        : Number(financial.metrics[m.key]?.value) < 0
                          ? '#579a7d'
                          : '#b86e65',
                  }"
                />
              </div>
              <small
                >{{ financial.metrics[m.key]?.count ?? 0 }}家公司有值</small
              >
            </div>
            <details>
              <summary>报告期与样本</summary>
              <div v-for="r in financial.rows" :key="r.code">
                {{ r.name }} {{ r.period }}
              </div>
            </details>
            <span v-if="financial.balance_error" class="muted">{{
              financial.balance_error
            }}</span>
          </div>
          <div v-else class="market-empty">{{ message(financial) }}</div>
          <footer
            class="panel-foot"
            title="按成交额选取前20只已支持成分股，各自最新报告期，不构成全板块评级"
          >
            前20样本 · 已覆盖{{ financial?.covered ?? "—" }}/{{
              financial?.sample_size ?? "—"
            }}
          </footer>
        </section>
        <section v-else class="market-panel breadth-panel">
          <header class="panel-head">
            <strong>涨跌分布</strong>
          </header>
          <div
            class="breadth-content"
            :aria-label="`${selected?.name ?? '板块'}涨跌分布`"
          >
            <div class="breadth-coverage">
              <span>成分行情已载入</span>
              <b
                >{{ currentMembers ? memberBreadth.loaded : "—" }} /
                {{ memberBreadth.membersTotal ?? "—" }}</b
              >
            </div>
            <div class="breadth-bar">
              <span :style="{ flex: memberBreadth.up }" /><i
                :style="{ flex: memberBreadth.flat }"
              /><em :style="{ flex: memberBreadth.down }" />
            </div>
            <div class="breadth-labels">
              <span class="up"
                >涨
                {{ breadthShare(memberBreadth.up, memberBreadth.total) }}</span
              ><span class="flat"
                >平
                {{
                  breadthShare(memberBreadth.flat, memberBreadth.total)
                }}</span
              ><span class="down"
                >跌
                {{
                  breadthShare(memberBreadth.down, memberBreadth.total)
                }}</span
              >
            </div>
            <div class="breadth-bands">
              <span class="breadth-sample-label"
                >已载入成分股 · 涨幅分层（只）</span
              >
              <div v-for="band in memberBreadth.bands" :key="band.label">
                <span>{{ band.label }}</span
                ><i
                  ><b
                    :class="band.tone"
                    :style="{
                      width: memberBreadth.loaded
                        ? `${(band.count / memberBreadth.loaded) * 100}%`
                        : '0%',
                    }" /></i
                ><strong>{{ currentMembers ? band.count : "—" }}</strong>
              </div>
            </div>
            <dl>
              <div>
                <dt>板块换手率</dt>
                <dd>{{ percent(selected?.turnover_rate) }}</dd>
              </div>
              <div>
                <dt>主力净额占比</dt>
                <dd :class="direction(selected?.net_ratio)">
                  {{ percent(selected?.net_ratio) }}
                </dd>
              </div>
            </dl>
          </div>
        </section>
      </aside>
    </div>

    <section v-else class="market-panel catalog-panel">
      <header class="panel-head">
        <strong>证券目录</strong
        ><label class="market-search"
          ><Search :size="14" /><input
            v-model="catalogQuery"
            aria-label="搜索证券"
            placeholder="名称 / 代码 / 拼音"
        /></label>
      </header>
      <BoardDataTable
        :rows="catalogTableRows"
        :columns="catalogColumns"
        :stock="true"
        :catalog="true"
        :column-widths="catalogWidths"
        @select="$emit('open', $event)"
        @open="$emit('open', $event)"
        @add="addWatch"
      />
      <footer class="panel-foot">
        <span>
          <template v-if="catalogQuoteTime">报价 {{ date(catalogQuoteTime) }}</template>
          <template v-if="catalogStatus && catalogStatus.covered < catalogStatus.total">
            {{ catalogQuoteTime ? ' · ' : '' }}已缓存 {{ catalogStatus.covered }}/{{ catalogStatus.total }}
            {{ catalogStatus.enabled && !catalogStatus.error ? ' · 后台补齐中' : '' }}
          </template>
        </span>
        <div v-if="!catalogQuery" class="pagination">
          <button :disabled="!catalogOffset" @click="catalogOffset -= 100">
            上一页</button
          ><span
            >{{ catalogOffset + 1 }}—{{
              catalogOffset + catalogRows.length
            }}</span
          ><button
            :disabled="catalogRows.length < 100"
            @click="catalogOffset += 100"
          >
            下一页
          </button>
        </div>
      </footer>
    </section>
    <div
      v-if="coverageOpen"
      class="coverage-overlay"
      @click.self="coverageOpen = false"
    >
      <section
        class="coverage-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="功能与数据覆盖"
      >
        <header>
          <h2>功能与数据覆盖</h2>
          <button aria-label="关闭功能说明" @click="coverageOpen = false">
            ×
          </button>
        </header>
        <p>
          报价以来源时间为准，盘中后台更新间隔30秒；自动更新服从设置。所有时间均为北京时间。
        </p>
        <table>
          <tbody>
            <tr>
              <th>已接数据</th>
              <td>
                行业/概念、成分股、分时/日K、1分钟涨速、今日及3/5/10日资金、订单大小分项、板块增仓、板块关键词资讯、样本财报、期货行情与可转债正股关联。
              </td>
            </tr>
            <tr>
              <th>历史轮动</th>
              <td>
                当前分类近10个实际交易日日K回填，覆盖
                {{ rotation?.covered ?? "—" }}/{{
                  rotation?.total ?? "—"
                }}。按当前分类回看，不是历史时点分类还原。
              </td>
            </tr>
            <tr>
              <th>来源差异</th>
              <td>
                板块分类为东方财富；ETF按名称、上位主题或披露前十大持仓与当前成分股的重合匹配；标注依据和报告期，不提供实时持仓占比。最新概念事件不再单设导航页。
              </td>
            </tr>
            <tr>
              <th>未接指标</th>
              <td>
                板块领先、热度值、主力净量、短线风向标、今日炒什么、ETF持仓占比尚未接通；分析页使用上证比较与成交额历史分位，名称及计算口径单独标注。
              </td>
            </tr>
            <tr>
              <th>增仓口径</th>
              <td>
                增仓占比为主力净额÷成交额；东方财富主力为超大单与大单合计。今日使用同源快照，2/3日按连续交易日净额之和÷成交额之和计算；3日历史未齐时使用来源原生3日占比；不是机构真实持仓，也不等于同花顺数值。当前2日历史覆盖
                {{ positions?.covered ?? "—" }}/{{
                  positions?.total ?? "—"
                }}，缺值不补零，排名按当前有值板块计算。
              </td>
            </tr>
            <tr>
              <th>图表</th>
              <td>
                分时使用来源交易日，日K为未复权，MA5/10/20；蓝线为板块、金线为上证对比。期货夜盘归下一交易日，成交量以合约张计。图表使用
                <a
                  href="https://www.tradingview.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  >TradingView Lightweight Charts</a
                >。
              </td>
            </tr>
            <tr>
              <th>涨停统计</th>
              <td>
                全板块涨停家数需要完整证券范围和涨停价，当前不以“涨幅≥9.9%”冒充；涨跌家数沿用来源，强势股统计注明已支持范围。
              </td>
            </tr>
            <tr>
              <th>其他截图入口</th>
              <td>
                港股/美股板块尚未接入；期股联动为国内期货与沪深普通A股的人工产业主题对应。债股联动按发行条款正股代码关联，涨跌差为债券涨幅减正股涨幅，不表示统计相关性；没有现行转股价时不推算溢价率。
              </td>
            </tr>
          </tbody>
        </table>
        <button class="primary-button" @click="coverageOpen = false">
          知道了
        </button>
      </section>
    </div>
  </section>
</template>

<style scoped src="../market.css"></style>
