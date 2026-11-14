<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from "vue";
import {
  createChart,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type MouseEventParams,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Intraday } from "../terminal";
import { normalizedPoints, chartTimestamp } from "../terminal";
import { indicatorNumber } from "../indicatorCatalog";
import IndicatorTabs from './IndicatorTabs.vue';
import {minuteAmounts,quantityAverage,quantityText,type QuantityMode} from '../chartQuantity';
const props = defineProps<{ data: Intraday; previousClose?: string | null; compact?: boolean }>();
const el = ref<HTMLDivElement>();
let chart: IChartApi | undefined;
let observer: ResizeObserver | undefined;
let series: ISeriesApi<"Area"> | undefined;
let volumes: ISeriesApi<"Histogram"> | undefined;
let averageSeries: ISeriesApi<"Line"> | undefined;
let percentSeries: ISeriesApi<"Line"> | undefined;
let oscillatorHistogram: ISeriesApi<"Histogram"> | undefined;
const oscillatorLines = new Map<string, ISeriesApi<"Line">>();
const secondary = ref('MACD');
const quantityMode = ref<QuantityMode>('volume');
const quantityMAPeriods = ref([5,10]);
const quantityMAPeriodOptions = [5,10,20,60];
const quantityMAColors: Record<number,string> = {5:'#b78012',10:'#2458a6',20:'#8755a1',60:'#17806d'};
const quantityValues = computed(()=>quantityMode.value==='volume' ? props.data.points.map(p=>p.volume) : minuteAmounts(props.data.points));
const quantityMeans = computed(()=>quantityMAPeriodOptions.map(period=>({period,values:quantityAverage(quantityValues.value,period)})));
const quantityLines = new Map<number,ISeriesApi<'Line'>>();
const selectedQuantityIndex = computed(()=>props.data.points.findIndex(p=>chartTimestamp(p.time)===cursor.value?.time));
const quantityUnavailable = computed(()=>!quantityValues.value.some(value=>value!=null));
const quantityOptions = [{value:'volume',label:'成交量',description:'每分钟实际成交股数'},{value:'amount',label:'成交额',description:'按同源累计成交额差分，单位元'}];
function toggleQuantityMA(period:number, checked:boolean) {
  quantityMAPeriods.value = checked
    ? [...new Set([...quantityMAPeriods.value,period])].sort((a,b)=>a-b)
    : quantityMAPeriods.value.filter(item=>item!==period);
}
const panePositions = ref({volume:0,secondary:0});
const averageSupported = computed(()=>props.data.average_supported !== false && !['sh000001','sz399001','sz399006','sh000300','sh000016','sh000905','sh000852','sh000688'].includes(props.data.symbol));
function positionPanes() { const panes=chart?.panes(); if(panes?.length===3) panePositions.value={volume:panes[0]!.getHeight()+2,secondary:panes[0]!.getHeight()+panes[1]!.getHeight()+4}; }
const averageValue = computed(() => {
  const p = props.data.points.find(p => chartTimestamp(p.time) === cursor.value?.time);
  return averageSupported.value && p?.average_price ? Number(p.average_price).toFixed(2) : '—';
});
const oscillatorValues = computed(() => {
  const index = props.data.points.findIndex(p => chartTimestamp(p.time) === cursor.value?.time);
  const keys = secondary.value === 'MACD' ? [['macd_dif','DIF'],['macd_dea','DEA'],['macd','MACD']] : secondary.value === 'RSI' ? [['rsi6','RSI6'],['rsi14','RSI14']] : [];
  return keys.map(([key,label]) => ({ label, value:indicatorNumber(props.data.indicators?.[key!]?.[index]) }));
});
function setSecondary() {
  oscillatorHistogram?.applyOptions({ visible:secondary.value === 'MACD' });
  for (const [key,line] of oscillatorLines) line.applyOptions({ visible:secondary.value === 'MACD' ? key.startsWith('macd') : secondary.value === 'RSI' && key.startsWith('rsi') });
}

let previousLine: IPriceLine | undefined;
let tradeDate = "";
let renderedPointCount = 0;
const cursor = ref<{ time: number; value: number; volume: number | null }>();
const change = computed(() => {
  const previous = Number(props.previousClose);
  return previous > 0 && cursor.value
    ? ((cursor.value.value / previous - 1) * 100).toFixed(2) + "%"
    : "—";
});
function syncData() {
  if (!series || !volumes) return;
  const points = normalizedPoints(props.data.points);
  const timeScale = chart?.timeScale();
  const previousRange = timeScale?.getVisibleLogicalRange();
  const followingLatest =
    !!previousRange && previousRange.to >= renderedPointCount - 1.5;
  const showingAll =
    followingLatest && !!previousRange && previousRange.from <= 0.5;
  const nextDate = points.at(-1)
    ? new Date(points.at(-1)!.time * 1000 + 8 * 3600000)
        .toISOString()
        .slice(0, 10)
    : "";
  series.setData(
    points.map((point) => ({
      time: point.time as UTCTimestamp,
      value: point.value,
    })),
  );
  syncQuantity();
  const sourceIndex = new Map(props.data.points.map((p,i)=>[chartTimestamp(p.time),i]));
  averageSeries?.setData(points.flatMap(p => {
    const raw = averageSupported.value ? props.data.points[sourceIndex.get(p.time)!]?.average_price : null;
    const value = raw == null ? NaN : Number(raw);
    return Number.isFinite(value) && value > 0 ? [{ time:p.time as UTCTimestamp, value }] : [];
  }));
  percentSeries?.setData(Number(props.previousClose) > 0 ? points.map(p=>({ time:p.time as UTCTimestamp, value:p.value })) : []);
  for (const [key,line] of oscillatorLines) line.setData(points.flatMap(p => {
    const raw = props.data.indicators?.[key]?.[sourceIndex.get(p.time)!];
    return raw == null ? [] : [{ time:p.time as UTCTimestamp,value:Number(raw) }];
  }));
  oscillatorHistogram?.setData(points.flatMap(p => {
    const raw = props.data.indicators?.macd?.[sourceIndex.get(p.time)!];
    return raw == null ? [] : [{ time:p.time as UTCTimestamp,value:Number(raw), color:Number(raw)>=0 ? '#b4233280' : '#087f5b80' }];
  }));
  cursor.value = points.at(-1);
  if (!renderedPointCount || tradeDate !== nextDate || showingAll)
    timeScale?.fitContent();
  else if (previousRange) {
    const to = followingLatest ? points.length - 1 : previousRange.to;
    timeScale?.setVisibleLogicalRange({
      from: to - (previousRange.to - previousRange.from),
      to,
    });
  }
  renderedPointCount = points.length;
  tradeDate = nextDate;
  if (previousLine) series.removePriceLine(previousLine);
  previousLine = undefined;
  if (Number(props.previousClose) > 0)
    previousLine = series.createPriceLine({
      price: Number(props.previousClose),
      color: "#bc8b1e",
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "昨收",
    });
}
function syncQuantity() {
  if(!volumes) return;
  const points=normalizedPoints(props.data.points);
  const sourceIndex=new Map(props.data.points.map((p,i)=>[chartTimestamp(p.time),i]));
  volumes.setData(points.map((p,i)=>{
    const value=quantityValues.value[sourceIndex.get(p.time)!];
    return {time:p.time as UTCTimestamp,...(value==null ? {} : {value,color:i && p.value<points[i-1]!.value ? '#087f5b70':'#b4233270'})};
  }));
  for(const {period,values} of quantityMeans.value) {
    const line=quantityLines.get(period);
    line?.setData(points.map(p=>{
      const value=values[sourceIndex.get(p.time)!];
      return {time:p.time as UTCTimestamp,...(value==null ? {} : {value})};
    }));
    line?.applyOptions({visible:quantityMAPeriods.value.includes(period)});
  }
}
function crosshair(param: MouseEventParams) {
  const point = normalizedPoints(props.data.points).find(
    (item) => item.time === param.time,
  );
  cursor.value = point ?? normalizedPoints(props.data.points).at(-1);
}
function draw() {
  if (!el.value) return;
  const priceRange = () => {
    const values = normalizedPoints(props.data.points).map(p=>p.value);
    if (averageSupported.value) for (const p of props.data.points) if (p.average_price != null && Number(p.average_price)>0) values.push(Number(p.average_price));
    if (Number(props.previousClose)>0) values.push(Number(props.previousClose));
    const minimum=Math.min(...values), maximum=Math.max(...values);
    const padding=minimum===maximum ? Math.max(0.01,minimum*0.001) : 0;
    return values.length ? {priceRange:{minValue:minimum-padding,maxValue:maximum+padding}} : null;
  };
  chart = createChart(el.value, {
    height: el.value.clientHeight,
    width: el.value.clientWidth,
    layout: { background: { color: "#fffef9" }, textColor: "#73756f", fontSize:props.compact ? 14 : 12, attributionLogo:false, panes:{separatorColor:'#d8d1bd',separatorHoverColor:'#f6ce45',enableResize:false} },
    grid: { vertLines: { visible: false }, horzLines: { color: "#eeeadd" } },
    localization: {
      locale: "zh-CN",
      timeFormatter: (time: number) =>
        new Intl.DateTimeFormat("zh-CN", {
          timeZone: "Asia/Shanghai",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date(time * 1000)),
    },
    timeScale: {
      rightOffset: 0,
      fixLeftEdge: true,
      fixRightEdge: true,
      rightBarStaysOnScroll: true,
      lockVisibleTimeRangeOnResize: true,
      minBarSpacing: 0.05,
      barSpacing: 8,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: number) =>
        new Intl.DateTimeFormat("zh-CN", {
          timeZone: "Asia/Shanghai",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date(time * 1000)),
    },
    handleScale: { mouseWheel: true },
    rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.08 } },
    leftPriceScale: { visible:true, scaleMargins:{ top:0.08, bottom:0.08 } },
  });
  series = chart.addSeries(AreaSeries, {
    lineColor: "#2458a6",
    topColor: "#2458a628",
    bottomColor: "#2458a602",
    lineWidth: 2,
    priceLineVisible: false,
    autoscaleInfoProvider: priceRange,
  });
  averageSeries = chart.addSeries(LineSeries, { color:'#bb8b13',lineWidth:2,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false, autoscaleInfoProvider:priceRange });
  percentSeries = chart.addSeries(LineSeries, { priceScaleId:'left',lineVisible:false,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,
    priceFormat:{ type:'custom',minMove:0.01,formatter:(value: number) => Number(props.previousClose)>0 ? ((value/Number(props.previousClose)-1)*100).toFixed(2)+'%' : '—' },
    autoscaleInfoProvider: priceRange,
  });
  volumes = chart.addSeries(
    HistogramSeries,
    {
      priceFormat: { type: "volume" },
      color: "#c6bba0",
      lastValueVisible: false,
      priceLineVisible: false,
    },
    1,
  );
  if (!props.compact) oscillatorHistogram = chart.addSeries(HistogramSeries,{ visible:true,lastValueVisible:false,priceLineVisible:false },2);
  for(const period of quantityMAPeriodOptions) quantityLines.set(period,chart.addSeries(LineSeries,
    {color:quantityMAColors[period],lineWidth:1,priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:quantityMAPeriods.value.includes(period)},1));
  for (const [key,color] of (props.compact ? [] : [['macd_dif','#2458a6'],['macd_dea','#bb8b13'],['rsi6','#bb8b13'],['rsi14','#2458a6']])) {
    oscillatorLines.set(key!, chart.addSeries(LineSeries,{ color:color!,visible:false,lineWidth:1,priceLineVisible:false,lastValueVisible:false },2));
  }
  chart.panes()[0].setStretchFactor(props.compact ? 0.78 : 0.54);
  chart.panes()[1].setStretchFactor(props.compact ? 0.22 : 0.18);
  if (!props.compact) chart.panes()[2].setStretchFactor(0.28);
  volumes
    .priceScale()
    .applyOptions({ scaleMargins: { top: 0.3, bottom: 0.04 }, visible: true });
  oscillatorHistogram?.priceScale().applyOptions({scaleMargins:{top:0.3,bottom:0.08}});
  syncData();
  setSecondary();
  requestAnimationFrame(positionPanes);
  chart.subscribeCrosshairMove(crosshair);
  requestAnimationFrame(() => chart?.timeScale().fitContent());
}
onMounted(() => {
  draw();
  observer = new ResizeObserver(() => {
    if (!chart || !el.value?.clientWidth || !el.value.clientHeight) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    chart.resize(el.value.clientWidth, el.value.clientHeight);
    // fixLeftEdge在宽度变化时也会移动范围；恢复原视野，兼顾全览与历史缩放。
    if (range) chart.timeScale().setVisibleLogicalRange(range);
    requestAnimationFrame(positionPanes);
  });
  if (el.value) observer.observe(el.value);
});
watch(() => [props.data, props.previousClose], syncData);
watch(secondary,setSecondary);
watch([quantityMode,quantityMAPeriods],syncQuantity);
onUnmounted(() => {
  observer?.disconnect();
  chart?.unsubscribeCrosshairMove(crosshair);
  chart?.remove();
});
</script>
<template>
  <div class="intraday-toolbar"><span><i class="legend-line price"></i>{{ averageSupported ? '价格' : '指数点位' }} <template v-if="averageSupported"><i class="legend-line average"></i>成交均价</template></span><span class="muted">分时 · 成交量 · 技术副图</span></div>
  <div class="chart-legend">
    <span class="chart-date">{{
      cursor
        ? new Intl.DateTimeFormat("zh-CN", {
            timeZone: "Asia/Shanghai",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }).format(new Date(cursor.time * 1000))
        : "—"
    }}</span>
    <span
      >现价 <strong>{{ cursor?.value.toFixed(2) ?? "—" }}</strong></span
    >
    <span
      >涨跌幅
      <strong :class="change.startsWith('-') ? 'down' : 'up'">{{
        change
      }}</strong></span
    >
    <span v-if="averageSupported">均价 <strong>{{ averageValue }}</strong></span>
    <span
      >昨收 <strong>{{ previousClose ?? "—" }}</strong></span
    >
    <span
      >分钟成交量
      <strong>{{
        cursor?.volume?.toLocaleString("zh-CN") ?? "—"
      }}</strong></span
    >
  </div>
  <div class="chart-stack">
    <div ref="el" class="stock-chart" aria-label="分时与成交量图" />
    <div class="pane-heading volume-heading" :style="{top:panePositions.volume+'px'}"><strong>{{ quantityMode==='volume' ? '成交量' : '成交额' }}</strong><span class="quantity-current">{{ quantityText(quantityValues[selectedQuantityIndex],quantityMode) }}</span><span v-if="quantityMAPeriods.length && !quantityUnavailable" class="quantity-average-values"><span v-for="item in quantityMeans.filter(item=>quantityMAPeriods.includes(item.period))" :key="item.period" :style="{color:quantityMAColors[item.period]}">MA{{ item.period }} {{ quantityText(item.values[selectedQuantityIndex],quantityMode) }}</span></span><span v-if="quantityUnavailable" class="quantity-unavailable">来源未提供分钟{{ quantityMode==='volume' ? '成交量' : '成交额' }}</span></div>
    <div class="pane-heading secondary-heading" :style="{top:panePositions.secondary+'px'}"><strong>{{ secondary }}</strong><span class="pane-values"><span v-for="item in oscillatorValues" :key="item.label">{{ item.label }} <b>{{ item.value }}</b></span></span></div>
    <div class="chart-pane-controls quantity-pane-controls" :style="{top:Math.max(0,panePositions.secondary-38)+'px'}"><div class="indicator-control-row"><strong>量图</strong><IndicatorTabs v-model="quantityMode" label="量图指标" :options="quantityOptions" /><span class="quantity-ma-controls" role="group" aria-label="均量线周期"><label v-for="period in quantityMAPeriodOptions" :key="period" class="quantity-ma-toggle" :style="{color:quantityMAColors[period]}"><input type="checkbox" :checked="quantityMAPeriods.includes(period)" :aria-label="`显示MA${period}均量线`" @change="toggleQuantityMA(period,($event.target as HTMLInputElement).checked)" />MA{{ period }}</label></span><span class="quantity-unit">{{ quantityMode==='volume' ? '单位：股' : '单位：元' }}</span><details class="quantity-unavailable-menu"><summary>更多量指标</summary><span title="分时换手率历史序列尚未接入">换手率：缺数据源</span><span title="需要逐笔主动买卖方向数据">内盘 / 外盘：缺逐笔数据</span><span title="需要实时成交量预测口径">虚拟成交量：待验证</span></details></div></div>
    <div class="chart-pane-controls secondary-pane-controls"><div class="indicator-control-row"><strong>副图</strong><IndicatorTabs v-model="secondary" label="分时副图" :options="[{value:'MACD',label:'MACD',description:'12,26,9'},{value:'RSI',label:'RSI',description:'6,14'}]" /></div></div>
  </div>
  <p class="chart-caption"><span class="intraday-source" :title="data.primary_error ?? data.source">{{ data.source }}{{ data.fallback ? '（备用）' : '' }}</span> · {{ data.trade_date ?? data.source_time?.slice(0,10) }} · 左轴涨跌幅 / 右轴价格 · 北京时间</p>
</template>
