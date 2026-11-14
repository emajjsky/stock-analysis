<script setup lang="ts">
import { computed } from 'vue';
import type { Quote } from '../types';
import { money } from '../format';
import { compact as compactNumber, orderBookStats, priceDirection, signed } from '../stockQuote';
import QuoteFacts from './QuoteFacts.vue';
const props = defineProps<{ quote?: Quote | null; compact?: boolean }>();
const book = computed(() => props.quote?.order_book);
const blank = Array.from({ length: 5 }, (_, i) => ({ level: i + 1, price: null, volume: null }));
const asks = computed(() => [...(book.value?.asks ?? blank)].reverse());
const bids = computed(() => book.value?.bids ?? blank);
const maximum = computed(() => Math.max(1, ...[...asks.value, ...bids.value].map(x => x.volume ?? 0)));
const stats = computed(() => orderBookStats(book.value));
const imbalance = computed(() => stats.value.imbalance);
const totals = computed(() => [
  {label:'委买量',value:compactNumber(stats.value.buy,'手'),title:'当前五档买盘委托量之和，单位：手'},
  {label:'委卖量',value:compactNumber(stats.value.sell,'手'),title:'当前五档卖盘委托量之和，单位：手'},
  {label:'五档委差',value:stats.value.difference == null ? '—' : `${stats.value.difference > 0 ? '+' : ''}${compactNumber(stats.value.difference,'手')}`,title:'五档委买量减委卖量，不是成交资金流'},
  {label:'买卖价差',value:stats.value.spread == null ? '—' : money(stats.value.spread)+'元',title:'卖一价格减买一价格'},
]);
</script>
<template>
  <aside class="panel order-book" :class="{ 'order-book-compact':compact }" aria-label="买卖五档">
    <header v-if="!compact" class="book-pressure"><span title="五档委比＝(五档买量−五档卖量)/(五档买量＋五档卖量)，不等于成交资金流">五档委比</span><strong :class="imbalance==null ? '' : imbalance>0 ? 'up' : imbalance<0 ? 'down' : ''">{{ signed(imbalance,'%') }}</strong></header>
    <div class="book-columns"><span>档位</span><span>价格</span><span>委托量 / 手</span></div>
    <div v-for="row in asks" :key="'ask' + row.level" class="book-row">
      <span class="book-depth sell" :style="{ width: `${(row.volume ?? 0) / maximum * 100}%` }"></span>
      <span class="down">卖{{ ['一', '二', '三', '四', '五'][row.level - 1] }}</span>
      <strong :class="priceDirection(row.price, quote?.previous_close)">{{ money(row.price) }}</strong>
      <span>{{ money(row.volume, 0) }}</span>
    </div>
    <div class="book-divider" aria-hidden="true"></div>
    <div v-for="row in bids" :key="'bid' + row.level" class="book-row">
      <span class="book-depth buy" :style="{ width: `${(row.volume ?? 0) / maximum * 100}%` }"></span>
      <span class="up">买{{ ['一', '二', '三', '四', '五'][row.level - 1] }}</span>
      <strong :class="priceDirection(row.price, quote?.previous_close)">{{ money(row.price) }}</strong>
      <span>{{ money(row.volume, 0) }}</span>
    </div>
    <div class="book-limits"><div><span>涨停</span><strong class="up">{{ money(quote?.limit_up) }}</strong></div><div><span>跌停</span><strong class="down">{{ money(quote?.limit_down) }}</strong></div></div>
    <dl v-if="!compact" class="book-totals" aria-label="五档盘口统计"><div v-for="item in totals" :key="item.label" :title="item.title"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
    <QuoteFacts v-if="!compact" :quote="quote" />
    <slot v-if="!compact" />
    <footer v-if="!compact && !book" class="book-footer">暂未取得五档报价</footer>
  </aside>
</template>

<style scoped>
.book-totals { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 12px; margin:0; padding:4px 9px 7px; border-top:1px solid var(--line); }
.book-totals > div { display:flex; align-items:baseline; justify-content:space-between; gap:4px; min-width:0; line-height:24px; }
.book-totals dt { color:var(--muted); font-size:12px; white-space:nowrap; }
.book-totals dd { margin:0; font:600 13px/24px Consolas,"Microsoft YaHei",monospace; white-space:nowrap; }
</style>
