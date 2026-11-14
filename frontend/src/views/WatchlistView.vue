<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  ArrowUpRight,
  ChevronRight,
  Plus,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Info,
  SlidersHorizontal,
  PanelRightClose,
  PanelRightOpen,
  ArrowDown,
  ArrowUp,
} from "lucide-vue-next";
import { api, post } from "../api";
import { action, refresh, state } from "../state";
import type { Intraday, RefreshStatus } from "../terminal";
import type { WatchItem } from "../types";
import { direction, money } from "../format";
import { amountWan, quoteTime, quoteDay, olderChart } from '../watchlistQuote';
import { percent } from "../terminal";
import IntradayChart from "../components/IntradayChart.vue";
import OrderBook from '../components/OrderBook.vue';
import { watchColumns, defaultColumns, normalizeColumns, columnText, columnDirection, sortWatches, type ColumnKey } from '../watchlistColumns';

const emit = defineEmits<{
  open: [id: string];
  market: [];
}>();

const group = ref("全部");
const query = ref("");
const selectedId = ref("");
const preferencesKey = 'watchlist-view-v1';
function readPreferences(): { columns?: unknown; detailVisible?: boolean } {
  try {
    const value=JSON.parse(localStorage.getItem(preferencesKey) ?? 'null');
    return value && typeof value==='object' ? value : {};
  } catch { return {}; }
}
const preferences=readPreferences();
const columnKeys=ref(normalizeColumns(preferences.columns));
const detailVisible=ref(preferences.detailVisible!==false);
const detailPanel=ref<'chart'|'book'>('chart');
const columnMenu=ref<HTMLDetailsElement>();
const tableScroll=ref<HTMLDivElement>();
const horizontalOverflow=ref(false);
const frozenNameWidth=ref(116);
const visibleColumns=computed(()=>watchColumns.filter(c=>columnKeys.value.includes(c.key)));
const tableWidth=computed(()=>visibleColumns.value.reduce((sum,c)=>sum+c.width,28));
const sortKey=ref<ColumnKey|null>(null);
const sortDirection=ref<'asc'|'desc'>('desc');
function sortBy(key: ColumnKey) {
  if (sortKey.value!==key) { sortKey.value=key; sortDirection.value='desc'; }
  else if (sortDirection.value==='desc') sortDirection.value='asc';
  else sortKey.value=null;
}
function toggleColumn(key: ColumnKey) {
  if (watchColumns.find(c=>c.key===key)?.required) return;
  columnKeys.value=normalizeColumns(columnKeys.value.includes(key) ? columnKeys.value.filter(c=>c!==key) : [...columnKeys.value,key]);
}
function closeColumnMenu(event: Event) {
  if (columnMenu.value && !columnMenu.value.contains(event.target as Node)) columnMenu.value.open=false;
}
watch([columnKeys, detailVisible],()=>{
  try { localStorage.setItem(preferencesKey,JSON.stringify({columns:columnKeys.value,detailVisible:detailVisible.value})); } catch { /* 展示偏好保存失败不影响行情。 */ }
  if (sortKey.value && !columnKeys.value.includes(sortKey.value)) sortKey.value=null;
});
let tableObserver: ResizeObserver | undefined;
function measureTable() {
  horizontalOverflow.value=Boolean(tableScroll.value && tableScroll.value.scrollWidth>tableScroll.value.clientWidth+1);
  frozenNameWidth.value=tableScroll.value?.querySelector('th')?.getBoundingClientRect().width ?? 116;
}
watch(tableScroll,(el)=>{
  tableObserver?.disconnect();
  if (el) { tableObserver?.observe(el); measureTable(); }
});
watch([visibleColumns,detailVisible],()=>{ void nextTick(measureTable); });
const intraday = ref<Intraday>();
const chartBusy = ref(false);
const chartError = ref("");
const refreshBusy = ref(false);
const status = ref<RefreshStatus>();
const quoteError = ref('');
const quoteController = new AbortController();
let chartController: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;

const groups = computed(() => [
  "全部",
  ...new Set(state.watchlists.map((item) => item.group_name)),
]);
const watches = computed(() =>
  sortWatches(state.watchlists.filter((item) => {
    const text = `${item.security.code}${item.security.name}`;
    return (
      (group.value === "全部" || item.group_name === group.value) &&
      (!query.value.trim() || text.includes(query.value.trim()))
    );
  }),sortKey.value,sortDirection.value),
);
const selected = computed(() =>
  watches.value.find((item) => item.security_id === selectedId.value) ??
  watches.value[0],
);
const selectedSecurity = computed(() => selected.value?.security);
const chartIsOld = computed(() => olderChart(intraday.value?.trade_date, selectedSecurity.value?.quote?.as_of));
const latestQuote = computed(() => state.watchlists.map(w => w.security.quote?.as_of).filter((v): v is string => Boolean(v)).sort().at(-1));
function select(id: string) {
  selectedId.value = id;
}
async function loadChart(quiet = false, activate = false) {
  if (disposed) return;
  chartController?.abort();
  chartBusy.value = false;
  const id = selected.value?.security_id;
  if (!id || !id.startsWith("LIVE.")) {
    intraday.value = undefined;
    chartError.value = "演示或导入证券暂无分时数据";
    return;
  }
  const controller = new AbortController();
  chartController = controller;
  if (!quiet) chartBusy.value = true;
  chartError.value = "";
  try {
    // 切股和个股详情一样登记访问，旧缓存也进入本轮分时更新范围。
    if (activate) await post(`/securities/${encodeURIComponent(id)}/activate`);
    if (controller !== chartController || disposed) return;
    const result = await api<Intraday>(
      `/market/intraday?security_id=${encodeURIComponent(id)}`,
      { signal: controller.signal },
    );
    if (controller !== chartController || disposed) return;
    intraday.value = result.data;
    chartError.value = result.data.error ?? "";
  } catch (error) {
    if (!controller.signal.aborted)
      chartError.value = error instanceof Error ? error.message : "分时数据读取失败";
  } finally {
    if (controller === chartController) chartBusy.value = false;
  }
}
async function loadQuotes() {
  const results = await Promise.allSettled([
    api<WatchItem[]>('/watchlists', { signal: quoteController.signal }),
    api<RefreshStatus>('/data/refresh', { signal: quoteController.signal }),
  ]);
  if (disposed) return;
  if (results[0].status === 'fulfilled') {
    state.watchlists = results[0].value.data;
    quoteError.value = '';
  } else quoteError.value = '更新暂未成功，正在重试';
  if (results[1].status === 'fulfilled') status.value = results[1].value.data;
}
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    await loadQuotes();
    if (!disposed && detailVisible.value && detailPanel.value==='chart') await loadChart(true);
    if (!disposed) schedule();
  }, 5000);
}
async function refreshPage() {
  if (refreshBusy.value) return;
  refreshBusy.value = true;
  try {
    const result = await action(() => post("/market/refresh"), "已请求更新自选行情");
    if (result) {
      await refresh();
      await loadChart();
    }
  } finally {
    refreshBusy.value = false;
  }
}
async function remove(item: WatchItem) {
  if (!confirm(`移出${item.security.name}？历史信号和持仓不会删除。`)) return;
  await action(
    () => api(`/watchlists/${item.id}`, { method: "DELETE" }),
    "已移出自选",
  );
  await refresh();
}
watch(
  watches,
  (items) => {
    if (!items.some((item) => item.security_id === selectedId.value))
      selectedId.value = items[0]?.security_id ?? "";
  },
  { immediate: true },
);
watch(selectedId, () => {
  intraday.value = undefined;
  loadChart(false, true);
}, { immediate: true });
watch([detailVisible,detailPanel],()=>{
  if (detailVisible.value && detailPanel.value==='chart') void loadChart(true);
});
onMounted(() => {
  tableObserver=new ResizeObserver(measureTable);
  if (tableScroll.value) tableObserver.observe(tableScroll.value);
  document.addEventListener('pointerdown',closeColumnMenu);
  void loadQuotes(); schedule();
});
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
  chartController?.abort();
  quoteController.abort();
  tableObserver?.disconnect();
  document.removeEventListener('pointerdown',closeColumnMenu);
});
</script>

<template>
  <section class="watchlist-page">
    <header class="watchlist-toolbar" aria-label="自选股工具栏">
      <div class="watchlist-groups" aria-label="自选分组">
        <button v-for="item in groups" :key="item" :class="{ active: group === item }" :aria-pressed="group === item" @click="group = item">{{ item }}<span>{{ item === '全部' ? state.watchlists.length : state.watchlists.filter(w => w.group_name === item).length }}</span></button>
      </div>
      <div class="watchlist-heading-actions">
        <label class="input-search watchlist-search"><Search :size="15" /><input v-model="query" placeholder="搜索自选股" aria-label="筛选自选股" /></label>
        <details ref="columnMenu" class="watch-column-menu" @keydown.esc="columnMenu && (columnMenu.open=false)">
          <summary class="button" aria-label="列设置"><SlidersHorizontal :size="16" />列设置</summary>
          <div class="watch-column-options">
            <div class="watch-column-heading"><strong>显示哪些行情</strong><button class="text-button" @click="columnKeys=[...defaultColumns]">恢复默认</button></div>
            <p>名称和代码固定在左侧，其余指标可左右滚动。</p>
            <div class="watch-column-choices"><label v-for="column in watchColumns" :key="column.key"><input type="checkbox" :checked="columnKeys.includes(column.key)" :disabled="column.required" @change="toggleColumn(column.key)" />{{ column.label }}<small v-if="column.unit">（{{ column.unit }}）</small></label></div>
          </div>
        </details>
        <button class="button watch-detail-toggle" :aria-expanded="detailVisible" aria-controls="watch-detail" :aria-label="detailVisible ? '收起右侧详情' : '展开右侧详情'" @click="detailVisible=!detailVisible"><component :is="detailVisible ? PanelRightClose : PanelRightOpen" :size="16" /><span>{{ detailVisible ? '收起详情' : '展开详情' }}</span></button>
        <button class="button" @click="emit('market')"><Plus :size="15" />添加自选</button>
        <button class="icon-button watch-refresh" aria-label="刷新行情" title="刷新行情" :disabled="refreshBusy" @click="refreshPage"><RefreshCw :size="17" :class="{ spinning: refreshBusy }" /></button>
      </div>
    </header>
    <p v-if="quoteError" class="watch-update-error" role="status">{{ quoteError }}</p>
    <div class="watchlist-layout" :class="{ 'watchlist-expanded': !detailVisible }">
      <section class="panel watchlist-table-panel" aria-label="自选股行情">
        <div v-if="watches.length" ref="tableScroll" class="table-scroll watchlist-table-scroll" role="region" :aria-label="horizontalOverflow ? '自选行情表格，可横向滚动' : '自选行情表格'" tabindex="0">
          <table class="watchlist-table" :style="{ minWidth:tableWidth+'px', '--watch-name-width':frozenNameWidth+'px' }">
            <colgroup><col v-for="column in visibleColumns" :key="column.key" :style="{ width:column.width+'px' }" /><col style="width:28px" /></colgroup>
            <thead><tr><th v-for="column in visibleColumns" :key="column.key" scope="col" :data-column="column.key" :class="[column.key==='name' || column.key==='code' ? 'watch-frozen watch-'+column.key : 'numeric', { 'is-sorted':sortKey===column.key }]" :aria-sort="sortKey===column.key ? (sortDirection==='asc' ? 'ascending' : 'descending') : 'none'"><button class="watch-sort" :title="sortKey===column.key ? (sortDirection==='desc' ? '点击升序排列' : '点击恢复原顺序') : '点击降序排列'" @click="sortBy(column.key)"><span>{{ column.label }}<small v-if="column.unit">（{{ column.unit }}）</small></span><ArrowDown v-if="sortKey===column.key && sortDirection==='desc'" :size="12" /><ArrowUp v-else-if="sortKey===column.key" :size="12" /><span v-else class="watch-sort-hint" aria-hidden="true">↕</span></button></th><th scope="col" class="watch-actions-header" aria-label="操作" /></tr></thead>
            <tbody>
              <tr v-for="item in watches" :key="item.id" :class="{ selected: selected?.id === item.id }" @click="select(item.security_id)">
                <td v-for="column in visibleColumns" :key="column.key" :data-column="column.key" :class="[column.key==='name' || column.key==='code' ? 'watch-frozen watch-'+column.key : 'numeric watch-value', columnDirection(item.security.quote,column.key), { 'quote-price':column.key==='price', 'quote-change':column.key==='change_pct', 'watch-amount':column.key==='amount', 'watch-time':column.key==='time' }]">
                  <button v-if="column.key==='name'" class="watch-stock" :title="item.security.name" @click.stop="select(item.security_id)" @dblclick="emit('open',item.security_id)"><span class="watch-stock-name"><strong>{{ item.security.name }}</strong><ChevronRight :size="13" /></span></button>
                  <time v-else-if="column.key==='time'" :title="quoteDay(item.security.quote?.as_of)">{{ columnText(item,column.key) }}</time>
                  <template v-else>{{ columnText(item,column.key) }}</template>
                </td>
                <td class="watch-remove"><button class="icon-button row-action" aria-label="移出自选" title="移出自选" @click.stop="remove(item)"><Trash2 :size="14" /></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="watchlist-empty"><Star :size="28" /><strong>{{ query || group !== '全部' ? '没有匹配的自选股' : '添加你的第一只自选股' }}</strong><span>从搜索或市场中选择股票，加入后自动更新行情。</span></div>
        <footer class="watchlist-table-footer"><span>{{ watches.length }} 只股票<span v-if="horizontalOverflow && watches.length" class="watch-scroll-hint">左右滚动查看更多</span></span><div class="watch-source-note"><span :title="quoteDay(latestQuote)">{{ quoteTime(latestQuote) }}</span><details><summary aria-label="行情来源说明" title="行情来源说明"><Info :size="14" /></summary><p>报价与分时使用公开行情源，可能存在延迟。页面每 5 秒读取最新缓存，后台盘中每 {{ status?.interval_seconds ?? 30 }} 秒获取行情，休市降低频率。源时间见各股票；不代表逐笔推送。</p></details></div></footer>
      </section>
      <aside v-show="detailVisible" id="watch-detail" class="panel watch-detail" aria-label="选中股票详情">
        <template v-if="selectedSecurity && selected">
          <header class="watch-detail-header"><div><h2>{{ selectedSecurity.name }}</h2><span>{{ selectedSecurity.code }}</span></div><button class="text-button watch-open-detail" @click="emit('open', selected.security_id)">个股详情 <ArrowUpRight :size="15" /></button></header>
          <div class="watch-detail-quote"><strong :class="direction(selectedSecurity.quote?.change_pct)">{{ money(selectedSecurity.quote?.price) }}</strong><div :class="direction(selectedSecurity.quote?.change_pct)"><span>{{ selectedSecurity.quote?.change != null ? `${Number(selectedSecurity.quote.change) > 0 ? '+' : ''}${money(selectedSecurity.quote.change)}` : '—' }}</span><span>{{ percent(selectedSecurity.quote?.change_pct) }}</span></div></div>
          <div class="watch-detail-chart">
            <div class="watch-detail-chart-head"><div class="watch-detail-tabs" role="tablist" aria-label="行情详情视图"><button role="tab" :aria-selected="detailPanel==='chart'" :class="{active:detailPanel==='chart'}" @click="detailPanel='chart'">分时</button><button role="tab" :aria-selected="detailPanel==='book'" :class="{active:detailPanel==='book'}" @click="detailPanel='book'">五档</button></div><div v-if="detailPanel==='chart'" class="watch-chart-legend"><span><i />价格</span><span><i />均价</span></div><time>{{ (detailPanel==='chart' ? intraday?.trade_date : undefined)?.slice(5).replace('-', '/') || quoteDay(selectedSecurity.quote?.as_of).slice(5).replace('-', '/') }}</time></div>
            <OrderBook v-if="detailPanel==='book'" :quote="selectedSecurity.quote" compact />
            <template v-else>
            <p v-if="chartIsOld" class="watch-chart-notice" role="status">分时仍为 {{ intraday?.trade_date }}，正在更新</p>
            <p v-else-if="chartError && intraday?.points.length" class="watch-chart-notice" role="status">分时暂未更新，保留上次走势</p>
            <div v-if="chartBusy && !intraday?.points.length" class="watch-chart-state"><RefreshCw :size="18" class="spinning" />正在获取分时…</div>
            <IntradayChart v-else-if="intraday?.points.length" :data="intraday" :previous-close="intraday.previous_close ?? selectedSecurity.quote?.previous_close" compact />
            <div v-else class="watch-chart-state"><span>{{ chartError || '正在获取分时…' }}</span></div>
            </template>
          </div>
          <dl class="watch-metric-grid">
            <div><dt>今开</dt><dd>{{ money(selectedSecurity.quote?.open) }}</dd></div><div><dt>昨收</dt><dd>{{ money(selectedSecurity.quote?.previous_close) }}</dd></div>
            <div><dt>最高</dt><dd :class="direction(Number(selectedSecurity.quote?.high) - Number(selectedSecurity.quote?.previous_close))">{{ money(selectedSecurity.quote?.high) }}</dd></div><div><dt>最低</dt><dd :class="direction(Number(selectedSecurity.quote?.low) - Number(selectedSecurity.quote?.previous_close))">{{ money(selectedSecurity.quote?.low) }}</dd></div>
            <div><dt>成交额<small>（万元）</small></dt><dd>{{ amountWan(selectedSecurity.quote?.amount) }}</dd></div><div><dt>换手率</dt><dd>{{ selectedSecurity.quote?.turnover_rate != null ? money(selectedSecurity.quote.turnover_rate) + '%' : '—' }}</dd></div>
            <div><dt>量比</dt><dd>{{ money(selectedSecurity.quote?.volume_ratio) }}</dd></div><div><dt>市盈率</dt><dd>{{ money(selectedSecurity.quote?.pe_ttm) }}</dd></div>
          </dl>
        </template>
        <div v-else class="watch-detail-empty"><Star :size="26" /><strong>选择一只自选股</strong><span>查看报价与分时走势</span></div>
      </aside>
    </div>
  </section>
</template>
