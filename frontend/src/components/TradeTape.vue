<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { Quote } from '../types';
import type { TradeTape as TradeTapeData, TradePrint } from '../terminal';
import { api } from '../api';
import { money } from '../format';
import { compact } from '../stockQuote';

const props = defineProps<{ securityId: string; quote?: Quote | null; preview?: boolean }>();
const emit = defineEmits<{ open: [] }>();
const data = ref<TradeTapeData>();
const error = ref('');
const busy = ref(false);
const filter = ref<'ALL' | 'BUY_LARGE' | 'SELL_LARGE'>('ALL');
let timer: ReturnType<typeof setInterval> | undefined;
let controller: AbortController | undefined;
const summary = computed(() => [
  { label:'外盘', value:props.quote?.buy_volume == null ? '—' : compact(Number(props.quote.buy_volume) / 100, '手') },
  { label:'内盘', value:props.quote?.sell_volume == null ? '—' : compact(Number(props.quote.sell_volume) / 100, '手') },
]);
function isLarge(trade: TradePrint) {
  return trade.price != null && Number(trade.price) * trade.volume_lots * 100 >= 200000;
}
const visibleTrades = computed(() => {
  const trades = (data.value?.trades ?? []).filter(trade => {
  if (filter.value === 'BUY_LARGE') return trade.side === 'BUY' && isLarge(trade);
  if (filter.value === 'SELL_LARGE') return trade.side === 'SELL' && isLarge(trade);
  return true;
  }).slice().reverse();
  return props.preview ? trades.slice(0,5) : trades;
});
async function refresh() {
  if (busy.value) return;
  busy.value = true;
  const current = new AbortController();
  controller = current;
  try {
    const result = await api<TradeTapeData>(`/market/trades?security_id=${encodeURIComponent(props.securityId)}`, { signal:current.signal });
    if (controller !== current || current.signal.aborted) return;
    data.value = result.data;
    error.value = '';
  } catch (cause) {
    if (current.signal.aborted) return;
    error.value = cause instanceof Error ? cause.message : '逐笔成交读取失败';
  } finally {
    if (controller === current) busy.value = false;
  }
}
watch(() => props.securityId, () => {
  controller?.abort();
  controller = undefined;
  busy.value = false;
  data.value = undefined;
  error.value = '';
  void refresh();
});
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 15000); });
onUnmounted(() => { if (timer) clearInterval(timer); controller?.abort(); });
</script>

<template>
  <section class="trade-tape" :class="{ 'trade-preview':preview }" :aria-label="preview ? '最近成交' : '逐笔成交'">
    <header v-if="preview" class="trade-preview-heading"><h3>最近成交</h3><button class="text-button" @click="emit('open')">更多 ›</button></header>
    <div v-if="!preview" class="trade-summary">
      <div v-for="item in summary" :key="item.label"><span>{{ item.label }}:</span><strong>{{ item.value }}</strong></div>
    </div>
    <div v-if="!preview" class="trade-filter" role="group" aria-label="逐笔成交筛选">
      <button :class="{active:filter==='ALL'}" @click="filter='ALL'">全部</button>
      <button :class="{active:filter==='BUY_LARGE'}" @click="filter='BUY_LARGE'">&gt;20万外盘</button>
      <button :class="{active:filter==='SELL_LARGE'}" @click="filter='SELL_LARGE'">&gt;20万内盘</button>
    </div>
    <div class="trade-columns"><span>时间</span><span>价格</span><span>手数</span></div>
    <div class="trade-rows" aria-live="polite">
      <div v-for="(trade,index) in visibleTrades" :key="`${trade.time}-${index}`" class="trade-row" :class="{buy:trade.side==='BUY',sell:trade.side==='SELL'}">
        <time>{{ trade.time }}</time><strong>{{ money(trade.price) }}<span v-if="isLarge(trade)" class="large-trade-mark">●</span></strong><span>{{ compact(trade.volume_lots) }}</span>
      </div>
      <p v-if="!visibleTrades.length && !error && !busy" class="trade-empty">{{ data?.trades.length ? '当前筛选无逐笔成交' : '暂无逐笔成交' }}</p>
      <p v-if="busy && !data" class="trade-empty">正在读取逐笔成交…</p>
      <p v-if="error" class="trade-error" role="status">{{ error }}</p>
    </div>
    <footer class="trade-footer"><span>{{ data?.source ?? '东方财富公开逐笔成交' }}</span><span>{{ busy ? '更新中' : data?.fetched_at ? new Date(data.fetched_at).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '—' }}</span></footer>
  </section>
</template>

<style scoped>
.trade-tape { display:flex; flex:1; min-height:0; flex-direction:column; overflow:hidden; border:1px solid var(--line); background:var(--surface); }
.trade-summary { display:grid; grid-template-columns:1fr 1fr; gap:8px 10px; padding:10px; border-bottom:1px solid var(--line); }
.trade-summary > div { display:flex; justify-content:space-between; gap:5px; min-width:0; font-size:12px; }
.trade-summary span { color:var(--muted); white-space:nowrap; }
.trade-summary strong { overflow:hidden; color:var(--ink); font-size:13px; font-variant-numeric:tabular-nums; text-overflow:ellipsis; white-space:nowrap; }
.trade-filter { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:4px; padding:7px 8px; border-bottom:1px solid var(--line); }
.trade-filter button { min-width:0; padding:5px 2px; border:1px solid transparent; background:transparent; color:var(--muted); font-size:11px; white-space:nowrap; }
.trade-filter button.active { border-color:var(--line); background:#f4f0e3; color:var(--ink); font-weight:600; }
.trade-columns,.trade-row { display:grid; grid-template-columns:minmax(70px,1fr) minmax(48px,.75fr) minmax(42px,.55fr); align-items:center; gap:4px; padding:6px 9px; font-variant-numeric:tabular-nums; }
.trade-columns { border-bottom:1px solid var(--line); color:var(--muted); font-size:11px; }
.trade-columns span:last-child,.trade-row > span { text-align:right; }
.trade-rows { flex:1; min-height:0; overflow:auto; scrollbar-gutter:stable; }
.trade-row { min-height:27px; color:var(--muted); font-size:12px; }
.trade-row strong { color:var(--ink); font-size:12px; }
.trade-row.buy strong { color:#b42332; }
.trade-row.sell strong { color:#087f5b; }
.large-trade-mark { margin-left:4px; color:#d000b5; font-size:10px; }
.trade-empty,.trade-error { margin:0; padding:14px 9px; color:var(--muted); font-size:12px; }
.trade-error { color:#9b3127; }
.trade-footer { display:flex; justify-content:space-between; gap:4px; padding:7px 9px; border-top:1px solid var(--line); color:var(--muted); font-size:10px; }
.trade-tape.trade-preview { flex:none; border:0; border-top:1px solid var(--line); }
.trade-preview-heading { display:flex; align-items:baseline; justify-content:space-between; padding:6px 9px 3px; }
.trade-preview-heading h3 { margin:0; font-size:13px; font-weight:600; }
.trade-preview-heading button { font-size:12px; }
.trade-preview .trade-rows { flex:none; max-height:140px; scrollbar-gutter:auto; }
.trade-preview .trade-columns { padding-block:2px; }
.trade-preview .trade-row { min-height:22px; padding-block:1px; font-size:13px; line-height:20px; }
.trade-preview .trade-row strong { font-size:13px; line-height:20px; }
.trade-preview .trade-footer { padding-block:4px; }
</style>
