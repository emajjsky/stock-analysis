<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from "vue";
import { ArrowUpRight, RefreshCw } from "lucide-vue-next";
import { api, post } from "../api";
import { action } from "../state";
import type { Bars } from "../types";
import type {
  MarketOverview,
  Intraday,
  RefreshStatus,
  CatalogStatus,
} from "../terminal";
import { compact, percent } from "../terminal";
import { money, date, direction } from "../format";
import StockChart from "../components/StockChart.vue";
import IntradayChart from "../components/IntradayChart.vue";
import NewsPanel from "../components/NewsPanel.vue";
const relatedStock = ref<{ id: string; name: string }>();
defineEmits<{ open: [id: string]; market: [] }>();
const overview = ref<MarketOverview>(),
  catalog = ref<CatalogStatus>(),
  status = ref<RefreshStatus>();
const symbol = ref("sh000001"),
  timeframe = ref("intraday"),
  bars = ref<Bars>(),
  intraday = ref<Intraday>(),
  chartBusy = ref(false),
  chartError = ref(""),
  error = ref(""),
  ranking = ref<"gainers" | "losers" | "amount">("gainers"),
  refreshBusy = ref(false);
const indexList = computed(() =>
  overview.value?.indices.length
    ? overview.value.indices
    : [
        ["sh000001", "上证指数"],
        ["sz399001", "深证成指"],
        ["sz399006", "创业板指"],
        ["sh000300", "沪深300"],
        ["sh000016", "上证50"],
        ["sh000905", "中证500"],
        ["sh000852", "中证1000"],
        ["sh000688", "科创50"],
      ].map(([symbol, name]) => ({
        symbol,
        name,
        price: null,
        change_pct: null,
      })),
);
const current = computed(() =>
  overview.value?.indices.find((i) => i.symbol === symbol.value),
);
const rows = computed(() => overview.value?.rankings[ranking.value] ?? []);
let stopped = false,
  timer: ReturnType<typeof setTimeout> | undefined;
let chartController: AbortController | undefined;
const overviewController = new AbortController();
async function loadOverview() {
  const results = await Promise.allSettled([
    api<MarketOverview>("/market/overview", {
      signal: overviewController.signal,
    }),
    api<RefreshStatus>("/data/refresh", { signal: overviewController.signal }),
    api<CatalogStatus>("/data/catalog", { signal: overviewController.signal }),
  ]);
  if (stopped) return;
  const [o, s, c] = results;
  if (o.status === "fulfilled") {
    overview.value = o.value.data;
    error.value = "";
  } else
    error.value = o.reason instanceof Error ? o.reason.message : "行情读取失败";
  if (s.status === "fulfilled") status.value = s.value.data;
  if (c.status === "fulfilled") catalog.value = c.value.data;
}
async function loadChart(quiet = false) {
  chartController?.abort();
  const ctrl = new AbortController();
  chartController = ctrl;
  const selected = symbol.value,
    tf = timeframe.value;
  if (!quiet) chartBusy.value = true;
  chartError.value = "";
  try {
    if (tf === "intraday") {
      const r = await api<Intraday>(`/market/indices/${selected}/intraday`, {
        signal: ctrl.signal,
      });
      if (ctrl !== chartController || stopped) return;
      intraday.value = r.data;
      chartError.value = r.data.error ?? "";
    } else {
      const r = await api<Bars>(
        `/market/indices/${selected}/bars?timeframe=${tf}`,
        { signal: ctrl.signal },
      );
      if (ctrl !== chartController || stopped) return;
      bars.value = r.data;
    }
  } catch (e) {
    if (!ctrl.signal.aborted)
      chartError.value = e instanceof Error ? e.message : "图表读取失败";
  } finally {
    if (ctrl === chartController) chartBusy.value = false;
  }
}
watch([symbol, timeframe], () => {
  bars.value = undefined;
  intraday.value = undefined;
  loadChart();
});
async function poll() {
  await loadOverview();
  if (!chartBusy.value) await loadChart(true);
  if (!stopped) timer = setTimeout(poll, 10000);
}
async function refreshMarket() {
  if (refreshBusy.value) return;
  refreshBusy.value = true;
  const r = await action(() => post<RefreshStatus>("/market/refresh"));
  if (r) status.value = r.data;
  refreshBusy.value = false;
}
onMounted(() => {
  loadChart();
  poll();
});
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  chartController?.abort();
  overviewController.abort();
});
</script>
<template>
  <section class="terminal-heading">
    <div>
      <span class="eyebrow">MARKET DESK</span>
      <h1>市场行情</h1>
    </div>
    <div class="flex wrap">
      <span class="badge" :title="catalog?.error ?? catalog?.source ?? ''">{{
        catalog?.status === "RUNNING"
          ? "基础库更新中"
          : catalog?.status === "ERROR"
            ? "基础库更新异常"
            : catalog?.count
              ? `${catalog.count.toLocaleString()} 只证券`
              : "基础库准备中"
      }}</span
      ><span
        class="badge"
        :class="{ blue: status?.enabled }"
        :title="status?.error ?? '行情按数据源能力更新'"
        >{{
          !status
            ? "连接中"
            : status.running
              ? "更新中"
              : status?.error
                ? "更新异常"
                : status?.enabled
                  ? "自动更新"
                  : "更新已暂停"
        }}</span
      ><button
        class="icon-button"
        aria-label="刷新市场行情"
        :disabled="refreshBusy || status?.running"
        @click="refreshMarket"
      >
        <RefreshCw :size="16" />
      </button>
    </div>
  </section>
  <p v-if="error" class="error-line" role="alert">{{ error }}</p>
  <div class="index-tabs" role="tablist" aria-label="主要指数">
    <button
      v-for="i in indexList"
      :key="i.symbol"
      class="index-tile"
      :class="{ active: symbol === i.symbol }"
      role="tab"
      :aria-selected="symbol === i.symbol"
      @click="symbol = i.symbol"
    >
      <span>{{ i.name }}</span
      ><strong :class="direction(i.change_pct)">{{ money(i.price) }}</strong
      ><small :class="direction(i.change_pct)">{{
        percent(i.change_pct)
      }}</small>
    </button>
  </div>
  <div class="home-columns">
    <section class="panel index-panel">
      <header class="chart-toolbar">
        <div>
          <h2>{{ current?.name ?? "上证指数" }}</h2>
          <span class="tiny muted"
            >{{ current?.source ?? "行情待加载" }} ·
            {{ date(current?.source_time) }}</span
          >
        </div>
        <div class="tabs">
          <button
            v-for="[v, n] in [
              ['intraday', '分时'],
              ['1d', '日 K'],
              ['1w', '周 K'],
              ['1mo', '月 K'],
            ]"
            :key="v"
            :class="{ active: timeframe === v }"
            @click="timeframe = v"
          >
            {{ n }}
          </button>
        </div>
      </header>
      <div v-if="chartBusy" class="terminal-chart-empty" role="status">
        读取行情…
      </div>
      <IntradayChart
        v-else-if="timeframe === 'intraday' && intraday?.points.length"
        :data="intraday"
        :previous-close="current?.previous_close"
      /><StockChart
        v-else-if="timeframe !== 'intraday' && bars?.bars.length"
        :data="bars"
        :signals="[]"
      />
      <div v-else class="terminal-chart-empty">
        <span>{{
          timeframe === "intraday" ? "暂无分时数据" : "暂无历史 K 线"
        }}</span
        ><button class="text-button tiny" @click="loadChart()">重新读取</button>
      </div>
      <div class="terminal-metrics">
        <span
          >成交量
          <strong
            >{{ compact(current?.volume)
            }}{{ current?.volume != null ? " 股" : "" }}</strong
          ></span
        ><span
          >成交额
          <strong
            >{{ compact(current?.amount)
            }}{{ current?.amount != null ? " 元" : "" }}</strong
          ></span
        ><span v-if="chartError" class="error-line" :title="chartError"
          >图表更新异常</span
        ><span v-else-if="overview?.updated_at" class="muted tiny"
          >更新 {{ date(overview.updated_at) }}</span
        >
      </div>
      <details
        v-if="chartError || bars?.limitations.length"
        class="terminal-details"
      >
        <summary>数据详情</summary>
        <p class="tiny muted">
          {{ chartError || bars?.limitations.join("；") }}
        </p>
      </details>
    </section>
  </div>
  <div class="market-lower-grid top-gap">
  <section class="panel ranking-panel">
    <header class="market-panel-heading">
      <div class="market-panel-title">
        <h2>行情榜单</h2>
        <button class="text-button" @click="$emit('market')">全部证券 <ArrowUpRight :size="14" /></button>
      </div>
      <div class="tabs">
        <button
          v-for="[v, n] in [
            ['gainers', '涨幅榜 Top100'],
            ['losers', '跌幅榜 Top100'],
            ['amount', '成交额榜 Top100'],
          ] as const"
          :key="v"
          :class="{ active: ranking === v }"
          @click="ranking = v"
        >
          {{ n }}
        </button>
      </div>
    </header>
    <div
      v-if="rows.length"
      class="table-scroll ranking-scroll"
      role="region"
      aria-label="市场排行榜"
      tabindex="0"
    >
      <table>
        <thead>
          <tr>
            <th>证券</th>
            <th>代码</th>
            <th class="numeric">现价</th>
            <th class="numeric">涨跌幅</th>
            <th class="numeric">成交额</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id" tabindex="0"
            :class="{ 'related-stock': relatedStock?.id === s.id }"
            :aria-selected="relatedStock?.id === s.id"
            @click="relatedStock = { id: s.id, name: s.name }"
            @keydown.enter.self="relatedStock = { id: s.id, name: s.name }">
            <td>
              <button class="stock-link" @click.stop="$emit('open', s.id)">
                {{ s.name }}
              </button>
            </td>
            <td>{{ s.code }}</td>
            <td class="numeric" :class="direction(s.quote?.change_pct)">
              {{ money(s.quote?.price) }}
            </td>
            <td class="numeric" :class="direction(s.quote?.change_pct)">
              {{ percent(s.quote?.change_pct) }}
            </td>
            <td class="numeric">{{ compact(s.quote?.amount) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="compact-empty">榜单数据暂未接入</div>
    <p v-if="rows.length" class="ranking-caption tiny muted">
      {{ rows[0].quote?.source ?? "公开行情" }} · 抓取
      {{ date(rows[0].quote?.fetched_at) }} · {{ rows.length }} 只
    </p>
  </section>
  <NewsPanel :selected="relatedStock" @clear="relatedStock = undefined" @open="$emit('open', $event)" />
  </div>
</template>
