<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import {
  ArrowLeft,
  Plus,
  Settings2,
  ExternalLink,
  RefreshCw,
} from "lucide-vue-next";
import { state, addWatch } from "../state";
import { api, post } from "../api";
import type {
  Bars,
  Profile,
  Signal,
  ResearchSyncResult,
  ResearchSection,
  ResearchSectionStatus,
  Security,
  ChartEvent,
} from "../types";
import { money, date, direction, label, safeUrl } from "../format";
import {
  publication,
  researchAccess,
  researchTime,
  sectionName,
} from "../research";
import type { Intraday, RefreshStatus } from "../terminal";
import IntradayChart from "../components/IntradayChart.vue";
import StockChart from "../components/StockChart.vue";
import EmptyState from "../components/EmptyState.vue";
import OrderBook from "../components/OrderBook.vue";
import ChipDistributionPanel from "../components/ChipDistributionPanel.vue";
import TradeTape from "../components/TradeTape.vue";
import ChartSelect from '../components/ChartSelect.vue';
import NewsPanel from "../components/NewsPanel.vue";
import StockAlgorithms from '../components/StockAlgorithms.vue';
const algorithmMarkers = ref<{time:string;text:string;direction:string}[]>([]);
import { quoteMetrics, signed } from "../stockQuote";
const props = defineProps<{ id: string }>();
defineEmits<{ back: []; rules: [id: string] }>();
const localSecurity = ref<Security>();
const ready = ref(false);
const security = computed(() =>
  localSecurity.value?.id === props.id
    ? localSecurity.value
    : state.securities.find((s) => s.id === props.id),
);
const signals = computed(() =>
  state.signals.filter((s) => s.security.id === props.id),
);
const timeframe = ref(props.id.startsWith("LIVE.") ? "intraday" : "1d"),
  intraday = ref<Intraday>(),
  data = ref<Bars>(),
  profile = ref<Profile>(),
  busy = ref(false),
  err = ref(""),
  tab = ref("公司资料"),
  researchBusy = ref(false),
  researchErrors = ref<Record<string, string>>({}),
  linkedNews = ref(true),
  adjustment = ref<'none' | 'qfq' | 'hfq'>('none'),
  quoteRefreshing = ref(false),
  adjustmentBusy = ref(false),
  adjustmentError = ref('');
const refreshStatus = ref<RefreshStatus>();
const chartSideTab = ref<'盘口'|'筹码'|'逐笔'>('盘口');
const chartCursorIndex = ref(-1);
const chartSideTabs = ['盘口','逐笔','筹码'] as const;
const adjustmentOptions = [
  {value:'qfq',label:'前复权',description:'按最新价格衔接历史走势'},
  {value:'hfq',label:'后复权',description:'按初始价格衔接历史走势'},
  {value:'none',label:'除权 / 不复权',description:'显示原始成交价格，保留除权缺口'},
];
function chooseAdjustment(value:string) {
  adjustment.value=value as 'none'|'qfq'|'hfq';
  if (timeframe.value==='intraday') timeframe.value='1d';
}
const adjustmentAttempts = new Map<string, { nextAt:number; failures:number }>();
const openedAt = ref(Date.now());
const elapsed = ref(0);
const profileLoading = ref(false);
const researchPending = computed(() => researchBusy.value || Boolean(profile.value?.research?.auto_refresh?.pending));
const hasChart = computed(() => timeframe.value === 'intraday' ? Boolean(intraday.value?.points.length) : Boolean(data.value?.bars.length));
const chartWaiting = computed(() => !hasChart.value && !err.value &&
  !(timeframe.value !== 'intraday' && adjustmentError.value && !adjustmentBusy.value) &&
  (busy.value || adjustmentBusy.value || (props.id.startsWith('LIVE.') && refreshStatus.value?.enabled !== false && elapsed.value < 60000)));
const chartEmptyDescription = computed(() => timeframe.value !== 'intraday' && adjustment.value !== 'none' && adjustmentError.value
  ? '复权历史暂未取得，可重试或切换“不复权”查看已保存行情。'
  : timeframe.value !== 'intraday' && adjustment.value === 'none' && !data.value?.bars.length
  ? '当前除权 / 不复权日线尚未载入，可点击右上角刷新同步历史。'
  : refreshStatus.value?.enabled === false
  ? '自动更新已关闭，可点击右上角刷新重试。'
  : '来源暂未返回可用数据，将自动检查；也可点击右上角刷新重试。');
const researchPermission = computed(() =>
  researchAccess(profile.value, props.id),
);
function chinaDate(value: string | null | undefined) {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const time = Date.parse(value);
  return Number.isFinite(time) ? new Date(time + 8*3600000).toISOString().slice(0,10) : '';
}
const chartEvents = computed<ChartEvent[]>(() => [
  ...(profile.value?.financials ?? []).flatMap(item => {
    const date = chinaDate(item.published_at);
    return date ? [{ date, kind:'financial' as const, title:`${item.period} 财报披露` }] : [];
  }),
  ...(profile.value?.corporate_actions?.items ?? []).flatMap(item => item.ex_date
    ? [{ date:item.ex_date, kind:'ex_dividend' as const, title:item.plan || '除权除息' }] : []),
].sort((a,b)=>b.date.localeCompare(a.date)));
function researchSection(section: ResearchSection) {
  const research = profile.value?.research;
  const status = research?.section_status?.[section];
  if (status) return status;
  const evidence = profile.value?.evidence?.find((item) => item.section === section);
  const errorPrefix = `${sectionName(section)}：`;
  const error = research?.error
    ?.split('；')
    .find((item) => item.startsWith(errorPrefix))
    ?.slice(errorPrefix.length) ?? null;
  const available = Boolean(evidence || research?.sections.includes(section));
  return {
    status: error ? available ? 'STALE' : 'ERROR' : available ? 'SYNCED' : 'AVAILABLE',
    last_attempt_at: null,
    last_updated_at: evidence?.received_at ?? null,
    source: evidence?.source ?? null,
    error,
  } satisfies ResearchSectionStatus;
}
function sectionFreshness(section: ResearchSection) {
  const status = researchSection(section);
  const checkedAt = status.status === 'SYNCED' ? status.last_attempt_at ?? status.last_updated_at : status.last_updated_at;
  const updated = checkedAt
    ? `${status.status === 'SYNCED' ? '核验于' : '资料时间'} ${date(checkedAt)}`
    : "尚未取得资料";
  if (researchPending.value) return profile.value?.research?.sections.includes(section) ? '后台更新中，当前显示已保存资料' : '正在自动获取资料…';
  return status?.source ? `${status.source} · ${updated}` : profileLoading.value ? '正在读取资料…' : updated;
}
function sectionError(section: ResearchSection) {
  return researchErrors.value[section] ?? researchSection(section)?.error ?? "";
}
function sectionErrorContext(section: ResearchSection) {
  return researchSection(section)?.status === "STALE"
    ? "更新失败，当前显示上次成功资料。"
    : "暂未取得可用资料。";
}
let controller: AbortController | undefined;
let activateController: AbortController | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let researchController: AbortController | undefined;
let profileController: AbortController | undefined;
let adjustmentController: AbortController | undefined;
let profileRequest = 0;
let lastMarketPoll = 0;
let lastProfilePoll = 0;
watch(
  () => props.id,
  () => {
    researchController?.abort();
    researchController = undefined;
    researchBusy.value = false;
    researchErrors.value = {};
    profileController?.abort();
    profileLoading.value = false;
    profile.value = undefined;
    linkedNews.value = true;
  },
  { flush: "sync" },
);
async function loadProfile() {
  if (!ready.value || profileLoading.value || researchBusy.value) return;
  profileController?.abort();
  const current = new AbortController();
  profileController = current;
  const id = props.id;
  const version = ++profileRequest;
  profileLoading.value = true;
  lastProfilePoll = Date.now();
  try {
    const result = await api<Profile>(`/securities/${encodeURIComponent(id)}/profile`, { signal: current.signal });
    if (id === props.id && !current.signal.aborted && version === profileRequest)
      profile.value = result.data;
  } catch (error) {
    if (!current.signal.aborted && id === props.id)
      researchErrors.value = { ...researchErrors.value, company: error instanceof Error ? error.message : '资料读取失败' };
  } finally {
    if (current === profileController) profileLoading.value = false;
  }
}
async function load(quiet = false, includeProfile = !quiet) {
  if (!ready.value) return;
  controller?.abort();
  controller = new AbortController();
  const current = controller;
  const id = props.id;
  lastMarketPoll = Date.now();
  if (includeProfile) void loadProfile();
  if (!quiet) busy.value = true;
  err.value = "";
  if (!quiet) {
    data.value = undefined;
    intraday.value = undefined;
  }
  const tf = timeframe.value;
  try {
    const results = await Promise.allSettled([
      (tf === "intraday"
        ? api<Intraday>(
            `/market/intraday?security_id=${encodeURIComponent(props.id)}`,
            { signal: current.signal },
          )
        : api<Bars>(
            `/market/bars?security_id=${encodeURIComponent(props.id)}&timeframe=${tf}&adjustment=${timeframe.value === 'intraday' ? 'none' : adjustment.value}`,
            { signal: current.signal },
          )).then((result) => {
            if (current !== controller || current.signal.aborted) return;
            if (tf === 'intraday') {
              intraday.value = result.data as Intraday;
              err.value = intraday.value.error ?? '';
            } else data.value = result.data as Bars;
            busy.value = false;
          }),
      api<Security>(`/securities/${encodeURIComponent(props.id)}`, {
        signal: current.signal,
      }).then((result) => {
        if (current === controller && !current.signal.aborted && id === props.id) localSecurity.value = result.data;
      }),
      api<RefreshStatus>('/data/refresh', { signal: current.signal }).then((result) => {
        if (current === controller && !current.signal.aborted) refreshStatus.value = result.data;
      }),
    ]);
    if (current !== controller || current.signal.aborted) return;
    const b = results[0];
    if (b.status === "rejected")
      err.value = b.reason instanceof Error ? b.reason.message : "行情加载失败";
    else if (tf !== 'intraday' && adjustment.value !== 'none' &&
      (!data.value?.bars.length || data.value.history_refresh_due) && refreshStatus.value?.enabled)
      void syncAdjustment(true);
  } catch (e) {
    if (current.signal.aborted) return;
    err.value = e instanceof Error ? e.message : "加载失败";
  } finally {
    if (current === controller) busy.value = false;
  }
}
async function activate(id = props.id) {
  if(!id.startsWith('LIVE.')) adjustment.value='none';
  adjustmentController?.abort();
  adjustmentBusy.value = false;
  openedAt.value = Date.now();
  elapsed.value = 0;
  refreshStatus.value = undefined;
  adjustmentError.value = '';
  ready.value = false;
  localSecurity.value = undefined;
  data.value = undefined;
  intraday.value = undefined;
  timeframe.value = id.startsWith("LIVE.") ? "intraday" : "1d";
  controller?.abort();
  activateController?.abort();
  const ctrl = new AbortController();
  activateController = ctrl;
  busy.value = true;
  err.value = "";
  try {
    const r = await api<Security>(
      `/securities/${encodeURIComponent(id)}${id.startsWith("LIVE.") ? "/activate" : ""}`,
      id.startsWith("LIVE.")
        ? { method: "POST", body: "{}", signal: ctrl.signal }
        : { signal: ctrl.signal },
    );
    if (ctrl !== activateController || ctrl.signal.aborted) return;
    localSecurity.value = r.data;
    const pos = state.securities.findIndex((s) => s.id === id);
    if (pos < 0) state.securities.push(r.data);
    else state.securities[pos] = r.data;
    ready.value = true;
    await load();
  } catch (e) {
    if (!ctrl.signal.aborted) {
      busy.value = false;
      err.value = e instanceof Error ? e.message : "股票加载失败";
    }
  }
}
watch(
  () => props.id,
  (id) => { adjustment.value = 'none'; activate(id); },
  { immediate: true },
);
watch([timeframe, adjustment], async () => {
  adjustmentController?.abort();
  adjustmentBusy.value = false;
  adjustmentError.value = '';
  const id = props.id, tf = timeframe.value, mode = adjustment.value;
  await load(false, false);
  if (id !== props.id || tf !== timeframe.value || mode !== adjustment.value) return;
  if (timeframe.value !== 'intraday' && adjustment.value !== 'none' && !data.value?.bars.length)
    await syncAdjustment();
});
onMounted(() => {
  pollTimer = setInterval(() => {
    elapsed.value = Date.now() - openedAt.value;
    if (!ready.value) return;
    const interval = !security.value?.quote || !hasChart.value ? 2000 : 10000;
    if (!busy.value && Date.now() - lastMarketPoll >= interval) void load(true);
    if (Date.now() - lastProfilePoll >= (researchPending.value ? 2000 : 10000)) void loadProfile();
  }, 1000);
});
async function syncResearch(section: ResearchSection | 'all') {
  if (!researchPermission.value.enabled || researchBusy.value) return;
  researchErrors.value = section === 'all'
    ? { ...researchErrors.value, company: '', financials: '', announcements: '' }
    : { ...researchErrors.value, [section]: '' };
  researchBusy.value = true;
  profileController?.abort();
  profileLoading.value = false;
  ++profileRequest;
  const id = props.id;
  researchController?.abort();
  const current = new AbortController();
  researchController = current;
  try {
    await api<ResearchSyncResult>(
      `/securities/${encodeURIComponent(id)}/research/sync`,
      {
        method: "POST",
        body: JSON.stringify({
          sections: section === 'all' ? ['company', 'financials', 'announcements'] : [section],
        }),
        signal: current.signal,
      },
    );
    if (id !== props.id || current !== researchController) return;
    const profileVersion = ++profileRequest;
    const refreshed = await api<Profile>(
      `/securities/${encodeURIComponent(id)}/profile`,
      { signal: current.signal },
    );
    if (
      id === props.id &&
      current === researchController &&
      profileVersion === profileRequest
    )
      profile.value = refreshed.data;
  } catch (error) {
    if (
      id === props.id &&
      current === researchController &&
      !current.signal.aborted
    ) {
      const message = error instanceof Error ? error.message : "研究资料同步失败";
      researchErrors.value = {
        ...researchErrors.value,
        [section === 'all' ? 'company' : section]: message,
      };
    }
  } finally {
    if (id === props.id && current === researchController)
      researchBusy.value = false;
  }
}
async function refreshQuote() {
  if (quoteRefreshing.value || !props.id.startsWith('LIVE.')) return;
  quoteRefreshing.value = true;
  err.value = '';
  try {
    await post('/market/refresh?security_id='+encodeURIComponent(props.id));
    await post('/data/providers/tencent/sync', { security_ids: [props.id], sync_daily: timeframe.value !== 'intraday' && adjustment.value === 'none' });
    if (timeframe.value !== 'intraday' && adjustment.value !== 'none') await syncAdjustment();
    await load(true, false);
  } catch (error) {
    err.value = error instanceof Error ? error.message : '行情更新失败；仍显示已有缓存';
  } finally { quoteRefreshing.value = false; }
}
async function syncAdjustment(automatic = false) {
  if (adjustmentBusy.value || adjustment.value === 'none') return;
  const attemptKey = props.id + ':' + adjustment.value;
  const previousAttempt = adjustmentAttempts.get(attemptKey);
  if (automatic && Date.now() < (previousAttempt?.nextAt ?? 0)) return;
  adjustmentAttempts.set(attemptKey, { nextAt:Date.now()+900000, failures:previousAttempt?.failures ?? 0 });
  adjustmentBusy.value = true;
  adjustmentError.value = '';
  const current = new AbortController();
  adjustmentController = current;
  const id = props.id, mode = adjustment.value;
  try {
    await api(`/securities/${encodeURIComponent(id)}/history/sync?adjustment=${mode}`, { method: 'POST', body: '{}', signal: current.signal });
    if (current.signal.aborted || id !== props.id || mode !== adjustment.value) return;
    adjustmentAttempts.set(attemptKey, { nextAt:Date.now()+900000, failures:0 });
    await load(true, false);
  } catch (error) {
    if (!current.signal.aborted && current === adjustmentController) {
      adjustmentError.value = error instanceof Error ? error.message : '复权历史同步失败；保留已有数据';
      const failures = (previousAttempt?.failures ?? 0) + 1;
      adjustmentAttempts.set(attemptKey, { nextAt:Date.now()+Math.min(300000,30000*2**Math.min(failures-1,4)), failures });
    }
  } finally { if (current === adjustmentController) adjustmentBusy.value = false; }
}
onUnmounted(() => {
  profileController?.abort();
  adjustmentController?.abort();
  controller?.abort();
  activateController?.abort();
  clearInterval(pollTimer);
  researchController?.abort();
});
</script>
<template>
  <div class="backline">
    <button class="text-button" @click="$emit('back')">
      <ArrowLeft :size="15" />返回工作区</button
    ><span class="tiny muted">个股分析</span>
  </div>
  <section v-if="security" class="stock-header">
    <div>
      <div class="eyebrow">
        {{ security.exchange }} · {{ security.code }}
      </div>
      <h1>
        {{ security.name }}
        <span v-if="security.status !== 'NORMAL' && security.status !== 'LIVE_UNVERIFIED' && (!id.startsWith('LIVE.') || security.quote)" class="badge">{{
          label(security.status)
        }}</span>
      </h1>
    </div>
    <div class="flex">
      <button
        class="button"
        @click="addWatch(id)"
        :disabled="state.watchlists.some((w) => w.security_id === id)"
      >
        <Plus :size="15" />{{
          state.watchlists.some((w) => w.security_id === id)
            ? "已在自选"
            : "加入自选"
        }}</button
      ><button class="button primary" @click="$emit('rules', id)">
        <Settings2 :size="15" />监测设置
      </button>
    </div>
  </section>
  <section v-if="security" class="stock-quote-strip" aria-label="行情数据">
    <div class="stock-quote-primary" :title="security.quote ? `${security.quote.source} · ${date(security.quote.source_time)}${security.quote.stale ? ' · 缓存' : ' · 快照'}` : '正在获取行情'">
      <strong :class="direction(security.quote?.change_pct)">{{ money(security.quote?.price) }}</strong>
      <span :class="direction(security.quote?.change_pct)">{{ security.quote ? signed(security.quote.change) + ' · ' + signed(security.quote.change_pct,'%') : '等待行情' }}</span>
      <span v-if="!security.quote" class="quote-pending" role="status">{{ elapsed < 60000 ? '正在获取行情…' : '行情暂未取得' }}</span>
      <span v-if="security.quote?.mode === 'DEMO'" class="badge">合成演示</span>
    </div>
    <div class="stock-quote-metrics">
      <div v-for="metric in quoteMetrics(security.quote)" :key="metric.label">
        <span>{{ metric.label }}</span><strong :class="metric.tone">{{ metric.value }}</strong>
      </div>
    </div>
  </section>
  <div v-if="err" :class="hasChart ? 'chart-source-warning' : 'error-box'" role="status">
    {{ err.replace('，已保留缓存','') }}{{ hasChart ? '；当前显示上次成功数据。' : '；尚未取得可用分时数据。' }}
    <button class="button small" :disabled="quoteRefreshing" @click="ready ? refreshQuote() : activate()">
      重试
    </button>
  </div>
  <div class="stock-workspace">
    <div class="stock-main">
      <section class="panel chart-panel">
        <header class="chart-toolbar">
          <div class="tabs">
            <button
              :disabled="!id.startsWith('LIVE.')"
              :class="{ active: timeframe === 'intraday' }"
              :title="id.startsWith('LIVE.') ? '' : '演示及导入证券无分时数据'"
              @click="timeframe = 'intraday'"
            >
              分时
            </button>
            <button
              v-for="[v, n] in [
                ['1d', '日 K'],
                ['1w', '周 K'],
                ['1mo', '月 K'],
              ]"
              :class="{ active: timeframe === v }"
              @click="timeframe = v"
            >
              {{ n }}</button
            ><button disabled title="未接入分钟行情">分钟</button>
          </div>
          <div class="stock-chart-actions">
            <div v-if="id.startsWith('LIVE.')" class="adjustment-control"><span>复权</span><ChartSelect :model-value="adjustment" label="复权方式" :options="adjustmentOptions" @update:model-value="chooseAdjustment" /><small v-if="timeframe==='intraday'">选择后查看K线</small></div>
            <button class="icon-button" aria-label="刷新行情" title="刷新行情与当前图表" :disabled="quoteRefreshing" @click="refreshQuote"><RefreshCw :size="16" :class="{ spinning: quoteRefreshing }" /></button>
          </div>
        </header>
        <div class="stock-chart-market-grid">
          <div class="stock-chart-column">
        <p v-if="timeframe !== 'intraday' && adjustment !== 'none' && !data?.bars.length" class="adjustment-empty" role="status">
          {{ adjustmentBusy ? '正在同步' + (adjustment === 'qfq' ? '前复权' : '后复权') + '历史…' : adjustmentError || '本地还没有该复权口径的历史数据' }}
          <button v-if="adjustmentError && !adjustmentBusy" class="text-button" @click="syncAdjustment()">重试</button>
        </p>
        <div v-if="chartWaiting" class="stock-chart-loading" role="status" aria-live="polite">
          <RefreshCw :size="22" class="spinning" />
          <strong>{{ busy ? '正在读取行情…' : '正在获取' + (timeframe === 'intraday' ? '分时行情' : '历史 K 线') + '…' }}</strong>
          <span>首次载入需要一点时间，数据返回后自动显示</span>
        </div>
        <IntradayChart
          v-else-if="timeframe === 'intraday' && intraday?.points.length"
          :data="intraday"
          :previous-close="intraday.previous_close ?? security?.quote?.previous_close"
        />
        <StockChart
          v-else-if="timeframe !== 'intraday' && data?.bars.length"
          :data="data"
          :signals="timeframe === '1d' ? signals : []"
          :events="timeframe === '1d' ? chartEvents : []"
          :algorithm-markers="timeframe === '1d' ? algorithmMarkers : []"
          @cursor-change="chartCursorIndex = $event"
        /><EmptyState
          v-else
          :title="timeframe === 'intraday' ? '分时数据暂未取得' : '暂无历史 K 线'"
          :description="
            id.startsWith('LIVE.') ? chartEmptyDescription : '尚无已保存日线'
          "
        />
        <p v-if="timeframe !== 'intraday' && data?.bars.length && adjustmentError" class="error-line" role="status">{{ adjustmentError }}</p>
          </div>
          <div v-if="security?.id.startsWith('LIVE.')" class="stock-chart-sidebar">
            <div class="book-tabs sidebar-tabs" role="tablist" aria-label="盘口、逐笔与筹码">
              <button v-for="name in chartSideTabs" :key="name" role="tab" :aria-selected="chartSideTab===name" :class="{active:chartSideTab===name}" @click="chartSideTab=name">{{ name==='盘口' ? '买卖五档' : name==='逐笔' ? '逐笔成交' : '筹码分布' }}</button>
            </div>
            <OrderBook v-if="chartSideTab==='盘口'" :quote="security.quote"><TradeTape :security-id="id" :quote="security.quote" preview @open="chartSideTab='逐笔'" /></OrderBook>
            <TradeTape v-else-if="chartSideTab==='逐笔'" :security-id="id" :quote="security.quote" />
            <ChipDistributionPanel v-else :data="data" :selected-index="chartCursorIndex" :float-shares="security.quote?.float_shares" :quote="security.quote" />
          </div>
        </div>
      </section>
      <StockAlgorithms :security-id="id" @markers="algorithmMarkers=$event" />
      <section class="panel research-panel">
        <div class="tabs bordered">
          <button
            v-for="t in ['公司资料', '财务摘要', '财报与分红', '新闻与公告']"
            :class="{ active: tab === t }"
            @click="tab = t"
          >
            {{ t }}
          </button>
        </div>
        <div class="inset" v-if="tab === '公司资料'">
          <div class="research-heading">
            <div>
              <h3>主营与公司概况</h3>
              <p class="tiny muted">{{ sectionFreshness('company') }}</p>
            </div>
            <div class="research-actions">
              <button
                class="button small"
                :disabled="!researchPermission.enabled || researchPending"
                @click="syncResearch('all')"
              >
                <RefreshCw :size="14" :class="{ spinning: researchPending }" />{{ researchPending ? "自动更新中…" : "刷新资料" }}
              </button>
            </div>
          </div>
          <p v-if="!researchPermission.enabled" class="tiny muted">
            {{ researchPermission.reason }}
          </p>
          <p v-else-if="profile?.research && !profile.research.auto_refresh" class="tiny muted" role="status">资料自动更新需重启更新后的后端；当前可手动刷新。</p>
          <p v-else-if="profile?.research?.auto_refresh?.enabled === false" class="tiny muted">自动更新已关闭，当前显示已保存资料。</p>
          <p v-if="sectionError('company')" class="error-line" role="alert">{{ sectionErrorContext('company') }}{{ sectionError('company') }}</p>
          <p>
            {{ profile?.business ?? (researchPending || profileLoading ? "正在获取公司概况，返回后自动显示…" : "暂未取得公司概况") }}
          </p>
          <div class="facts-grid">
            <div v-for="f in profile?.facts" :key="f.label">
              <span>{{ f.label }}</span
              ><strong>{{ f.value }}</strong>
            </div>
          </div>

          <details v-if="profile?.evidence?.length || profile?.limitations.length" class="research-evidence-details">
            <summary>资料来源与口径</summary>
            <p v-for="item in [...new Set([...(profile?.research?.limitations ?? []), ...(profile?.limitations ?? [])])]" :key="item" class="tiny muted">{{ item }}</p>
            <details
              v-for="item in profile.evidence"
              :key="item.id"
              class="evidence-row"
            >
              <summary>
                {{ sectionName(item.section) }} · {{ item.source }}
              </summary>
              <small
                >可获知 {{ researchTime(item.available_at) }} · 抓取
                {{ researchTime(item.received_at) }}</small
              >
              <a
                v-if="safeUrl(item.source_url)"
                :href="safeUrl(item.source_url)!"
                target="_blank"
                rel="noopener noreferrer"
                >来源 <ExternalLink :size="11"
              /></a>
            </details>
          </details>
        </div>
        <div class="inset" v-else-if="tab === '财务摘要'">
          <div class="research-heading"><div><h3>财务摘要</h3><p class="tiny muted">人民币元 · 按报告期列示 · {{ sectionFreshness('financials') }}</p></div><button class="button small" :disabled="!researchPermission.enabled || researchPending" @click="syncResearch('financials')"><RefreshCw :size="14" :class="{ spinning: researchPending }" />{{ researchPending ? '自动更新中…' : '刷新财务' }}</button></div>
          <p v-if="sectionError('financials')" class="error-line" role="alert">{{ sectionErrorContext('financials') }}{{ sectionError('financials') }}</p>
          <div v-if="profile?.financials?.length" class="table-scroll">
            <table class="research-table">
              <thead>
                <tr>
                  <th>报告期</th>
                  <th>披露日 / 精度</th>
                  <th>营业收入（元）</th>
                  <th>营收同比</th>
                  <th>归母净利（元）</th>
                  <th>净利同比</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in profile.financials"
                  :key="item.period + item.raw_hash"
                >
                  <td>{{ item.period }}</td>
                  <td>
                    {{
                      publication(item.published_at, item.publication_precision)
                    }}
                  </td>
                  <td>{{ money(item.total_revenue) }}</td>
                  <td>{{ signed(item.revenue_yoy,'%') }}</td>
                  <td>{{ money(item.parent_net_profit) }}</td>
                  <td>{{ signed(item.profit_yoy,'%') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="research-empty">{{ researchPending || profileLoading ? '正在获取财务数据…' : '暂未取得财务数据，来源恢复后自动补齐。' }}</p>
        </div>
        <div v-else-if="tab === '财报与分红'" class="inset">
          <div class="research-heading"><div><h3>财报与分红</h3><p class="tiny muted">按披露日与除权日列示 · 日K图以圆点标记</p></div><button class="button small" :disabled="!researchPermission.enabled || researchPending" @click="syncResearch('all')">{{ researchPending ? '更新中…' : '刷新资料' }}</button></div>
          <p v-if="profile?.corporate_actions?.error" class="error-line">{{ profile.corporate_actions.error }}</p>
          <div class="corporate-actions" v-if="profile?.corporate_actions?.items?.length">
            <article v-for="item in profile.corporate_actions.items" :key="item.period + ':' + item.ex_date">
              <time>{{ item.ex_date || '除权日待定' }}</time><div><strong>{{ item.plan || '分配方案待披露' }}</strong><p>{{ item.status }} · 登记日 {{ item.record_date || '待定' }} · 披露日 {{ item.published_at || '未知' }}</p></div>
            </article>
          </div>
          <p v-else class="research-empty">{{ researchPending || profileLoading ? '正在获取分红与除权资料…' : '来源尚无可用分红记录' }}</p>
          <div class="corporate-actions"><article v-for="item in profile?.financials" :key="item.period"><time>{{ chinaDate(item.published_at) || '披露日未知' }}</time><div><strong>{{ item.period }} 财务报告</strong><p>营收同比 {{ signed(item.revenue_yoy,'%') }} · 归母净利同比 {{ signed(item.profit_yoy,'%') }}</p></div></article></div>
          <p class="tiny muted" v-if="profile?.corporate_actions?.source">{{ profile.corporate_actions.source }} · 更新于 {{ date(profile.corporate_actions.received_at) }}</p>
        </div>
        <div v-else-if="tab === '新闻与公告'" class="stock-news-wrap">
          <NewsPanel
            :selected="linkedNews && security ? { id: security.id, name: security.name } : undefined"
            @clear="linkedNews = false"
          />
        </div>
      </section>
    </div>
  </div>
</template>
