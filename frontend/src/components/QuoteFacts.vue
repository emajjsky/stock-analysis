<script setup lang="ts">
import { computed } from 'vue';
import type { Quote } from '../types';
import { money, date } from '../format';
import { compact } from '../stockQuote';

const props = defineProps<{ quote?: Quote | null }>();
function lots(value: unknown) {
  return value == null || value === '' ? '—' : compact(Number(value) / 100, '手');
}
const facts = computed(() => {
  const q = props.quote;
  return [
    { label:'外盘', value:lots(q?.buy_volume) },
    { label:'内盘', value:lots(q?.sell_volume) },
    { label:'市净率', value:money(q?.pb) },
    { label:'市盈TTM', title:'市盈率（TTM）', value:money(q?.pe_ttm) },
    { label:'市盈静', title:'静态市盈率', value:money(q?.pe_static) },
    { label:'流通值', title:'流通市值（元）', value:compact(q?.float_market_cap) },
    { label:'总股本', value:compact(q?.total_shares,'股') },
    { label:'流通股', title:'流通股本', value:compact(q?.float_shares,'股') },
  ];
});
</script>

<template>
  <section class="quote-facts" aria-label="成交与估值补充">
    <header><h3>成交与估值</h3><time :title="`${quote?.source ?? '公开行情'} · ${quote?.stale ? '缓存报价' : '行情快照'} · 非持续实时推送`">{{ date(quote?.source_time ?? quote?.as_of) }}</time></header>
    <dl><div v-for="fact in facts" :key="fact.label"><dt :title="fact.title ?? fact.label">{{ fact.label }}</dt><dd :title="fact.value">{{ fact.value }}</dd></div></dl>
  </section>
</template>

<style scoped>
.quote-facts { min-width:0; flex:none; border-top:1px solid var(--line); }
.quote-facts header { display:flex; align-items:baseline; justify-content:space-between; gap:6px; padding:7px 9px 4px; }
.quote-facts h3 { margin:0; font-size:13px; font-weight:600; }
.quote-facts time { color:var(--muted); font:11px/1.4 Consolas,monospace; white-space:nowrap; }
.quote-facts dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); column-gap:12px; margin:0; padding:0 9px 6px; }
.quote-facts dl > div { display:flex; align-items:baseline; justify-content:space-between; gap:4px; min-width:0; min-height:22px; line-height:22px; }
.quote-facts dt { color:var(--muted); font-size:12px; white-space:nowrap; }
.quote-facts dd { min-width:0; margin:0; text-align:right; font:600 13px/22px Consolas,"Microsoft YaHei",monospace; font-variant-numeric:tabular-nums; white-space:nowrap; }
</style>
