<script setup lang="ts">
import { computed } from 'vue';
import type { Bars, Quote } from '../types';
import { buildChipSnapshots } from '../chipDistribution';
import QuoteFacts from './QuoteFacts.vue';
const props=defineProps<{data?:Bars;selectedIndex:number;floatShares?:string|null;quote?:Quote|null}>();
const snapshots=computed(()=>buildChipSnapshots(props.data?.bars??[],Number(props.floatShares),140,`${props.data?.security_id??''}:${props.data?.timeframe??''}:${props.data?.adjustment??''}`));
const index=computed(()=>props.data?.bars.length ? props.selectedIndex<0 ? props.data.bars.length-1 : Math.min(props.selectedIndex,props.data.bars.length-1) : -1);
const snapshot=computed(()=>index.value<0 ? null : snapshots.value[index.value]??null);
const price=computed(()=>{
  const selectedClose=Number(props.data?.bars[index.value]?.close);
  return Number.isFinite(selectedClose)&&selectedClose>0 ? selectedClose : NaN;
});
const rows=computed(()=>{
  if(!snapshot.value) return [];
  const bins=snapshot.value.bins;
  const low=snapshot.value.cost90[0],high=snapshot.value.cost90[1];
  const span=high-low;
  if(!(span>0)) return [];
  const count=140,step=span/(count-1);
  const valueAt=(price:number)=>{
    const position=Math.max(0,Math.min(bins.length-1,(price-bins[0]!.price)/(bins[1]!.price-bins[0]!.price)));
    const left=Math.floor(position),right=Math.min(bins.length-1,left+1),weight=position-left;
    return bins[left]!.shares*(1-weight)+bins[right]!.shares*weight;
  };
  return Array.from({length:count},(_,i)=>({price:high-i*step,shares:valueAt(high-i*step)}));
});
const maximum=computed(()=>Math.max(1,...rows.value.map(row=>row.shares)));
const profileHeight=300;
const emptyReason=computed(()=>!props.data?.bars.length
  ? '当前口径暂无日线，请点击页面上方刷新以同步未复权历史'
  : !(Number(props.floatShares)>0)
    ? '行情源未提供有效流通股本，暂无法估算筹码分布'
    : '日线价格数据无效，暂无法估算筹码分布');
const priceLabelStride=computed(()=>Math.max(1,Math.ceil(rows.value.length/10)));
const lockedRatio=computed(()=>snapshot.value ? 1-snapshot.value.profitRatio : 0);
const costGap=computed(()=>snapshot.value&&price.value>0 ? (price.value/snapshot.value.averageCost-1)*100 : null);
const currentLine=computed(()=>{
  if(!rows.value.length||price.value<rows.value.at(-1)!.price||price.value>rows.value[0]!.price)return null;
  const high=rows.value[0]!.price,low=rows.value.at(-1)!.price;
  return `${11+(high-price.value)/(high-low||1)*(profileHeight-22)}px`;
});
function money(value:number|undefined) { return value==null||!Number.isFinite(value) ? '—' : value.toFixed(2); }
</script>

<template>
  <aside class="panel chip-panel" aria-label="筹码分布估算">
    <header class="chip-heading"><h2>筹码分布</h2><span>{{ data?.bars[index]?.time ?? '等待日线' }}</span></header>
    <div v-if="snapshot" class="chip-summary chip-summary-expanded">
      <div><span>收盘获利</span><strong class="up">{{ (snapshot.profitRatio*100).toFixed(1) }}%</strong></div>
      <div><span>套牢盘</span><strong class="down">{{ (lockedRatio*100).toFixed(1) }}%</strong></div>
      <div><span>平均成本</span><strong>{{ money(snapshot.averageCost) }}</strong></div>
      <div><span>成本峰</span><strong>{{ money(snapshot.peakCost) }}</strong></div>
      <div><span>成本偏离</span><strong :class="(costGap??0)>=0?'up':'down'">{{ costGap==null?'—':`${costGap>=0?'+':''}${costGap.toFixed(2)}%` }}</strong></div>
      <div><span>估算筹码</span><strong>{{ (snapshot.estimatedShares/10000).toFixed(1) }}万股</strong></div>
    </div>
    <div v-if="snapshot" class="chip-balance" role="img" :aria-label="`估算获利盘 ${(snapshot.profitRatio*100).toFixed(1)}%，套牢盘 ${(lockedRatio*100).toFixed(1)}%`"><i class="profitable" :style="{width:`${snapshot.profitRatio*100}%`}" /><i class="locked" :style="{width:`${lockedRatio*100}%`}" /></div>
    <div v-if="snapshot" class="chip-profile" :style="{height:profileHeight+'px',gridTemplateRows:`repeat(${rows.length}, 2px)`}" role="img" :aria-label="`筹码成本分布，显示90%成本区间 ${money(snapshot.cost90[0])}至${money(snapshot.cost90[1])}，收盘价 ${money(price)}`">
      <div v-for="(row,rowIndex) in rows" :key="row.price.toFixed(4)" class="chip-row">
        <span class="chip-price">{{ rowIndex%priceLabelStride===0?money(row.price):'' }}</span>
        <div class="chip-track" :title="`${money(row.price)} 元 · 估算 ${Math.round(row.shares).toLocaleString('zh-CN')} 股`"><i :class="row.price<=price?'chip-profitable':'chip-underwater'" :style="{width:`${row.shares/maximum*100}%`}"></i></div>
      </div>
      <div v-if="currentLine" class="chip-current-price" :style="{top:currentLine}"><span>收盘价 {{ money(price) }}</span></div>
    </div>
    <div v-if="snapshot" class="chip-legend"><span><i class="locked" />套牢盘</span><span><i class="profitable" />获利盘</span></div>
    <div v-if="snapshot" class="chip-ranges">
      <div><span><i class="range90" />90%筹码区间</span><strong>{{ money(snapshot.cost90[0]) }}–{{ money(snapshot.cost90[1]) }}</strong><small>集中度 {{ (snapshot.concentration90*100).toFixed(2) }}%</small></div>
      <div><span><i class="range70" />70%筹码区间</span><strong>{{ money(snapshot.cost70[0]) }}–{{ money(snapshot.cost70[1]) }}</strong><small>集中度 {{ (snapshot.concentration70*100).toFixed(2) }}%</small></div>
      <div class="chip-range-overlap"><span>70%/90%区间宽度比</span><strong>{{ (snapshot.intervalWidthRatio*100).toFixed(2) }}%</strong></div>
    </div>
    <div v-else class="chip-empty">{{ emptyReason }}</div>
    <div v-if="snapshot" class="chip-unavailable-cost" title="筹码由日线量价模型估算，没有机构或主力账户持仓明细">主力持仓成本 <strong>未接入数据</strong></div>
    <QuoteFacts v-if="quote" :quote="quote" />
    <p class="chip-source">按{{ data?.bars.length??0 }}根{{ data?.timeframe==='1w'?'周':data?.timeframe==='1mo'?'月':'日' }}K的量价与流通股本估算；价格沿用当前复权口径，不是原始持仓数据</p>
  </aside>
</template>

<style scoped>
.chip-summary-expanded { grid-template-columns:repeat(2,minmax(0,1fr)); }
.chip-summary-expanded > div { min-width:0; flex-direction:row; align-items:baseline; justify-content:space-between; gap:4px; min-height:23px; line-height:23px; }
.chip-summary-expanded strong { font-variant-numeric:tabular-nums; }
.chip-summary-expanded > div:last-child { grid-column:1/-1; }
.chip-panel { display:flex; flex-direction:column; flex:1; overflow-y:auto; scrollbar-width:thin; }
.chip-heading,.chip-summary,.chip-profile,.chip-ranges,.chip-legend,.chip-source,.chip-unavailable-cost { flex:none; }
.chip-balance { display:flex; flex:none; height:4px; margin:0 10px 4px; background:#eee9dc; }
.chip-balance .profitable { background:#b42332b8; }
.chip-balance .locked { background:#397dccb8; }
.chip-unavailable-cost { display:flex; justify-content:space-between; gap:8px; padding:7px 10px; border-bottom:1px solid var(--line); color:var(--muted); font-size:12px; }
.chip-unavailable-cost strong { color:var(--muted); font-size:12px; font-weight:500; }
.chip-profile { min-height:0; display:grid; grid-template-columns:minmax(0,1fr); align-content:start; padding:10px; }
.chip-row { position:relative; height:2px; min-height:0; flex:none; }
.chip-price { position:absolute; left:0; top:1px; width:42px; transform:translateY(-50%); line-height:10px; pointer-events:none; }
.chip-track { grid-column:2; align-self:start; height:1px; max-height:1px; }
.chip-legend { display:flex; gap:16px; padding:5px 10px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }
.chip-legend span,.chip-ranges span { display:flex; align-items:center; gap:5px; }
.chip-legend i,.chip-ranges i { display:inline-block; width:10px; height:10px; flex:none; }
.chip-legend .locked { background:#397dccb8; }
.chip-legend .profitable { background:#b42332b8; }
.chip-ranges { display:grid; gap:5px; padding:6px 10px; border-top:1px solid var(--line); }
.chip-ranges > div { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:3px 8px; font-size:11px; }
.chip-ranges strong { font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.chip-ranges small { grid-column:2; color:var(--muted); text-align:right; font-size:10px; }
.chip-ranges .range90 { background:#777; }
.chip-ranges .range70 { background:#f6ce45; }
.chip-range-overlap { padding-top:5px; border-top:1px dashed var(--line); color:var(--muted); }
.chip-range-overlap strong { color:var(--ink); }
</style>
