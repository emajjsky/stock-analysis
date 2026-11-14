<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from "vue";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
  type SeriesMarker,
} from "lightweight-charts";
import type { Bars, Signal, ChartEvent } from "../types";
import { secondaryIndicators, mainIndicators, indicatorNumber } from "../indicatorCatalog";
import IndicatorTabs from './IndicatorTabs.vue';
import { quantityAverage, quantityText, type QuantityMode } from '../chartQuantity';
import { readMas, saveMas, defaultMas, movingAverage } from '../chartPreferences';
import { calculateIndicatorSignals, indicatorSignalAnchor } from '../indicatorSignals';

const PANE = { PRICE: 0, QUANTITY: 1, INDICATOR: 2 } as const;
const props = defineProps<{ data: Bars; signals: Signal[]; events?: ChartEvent[]; algorithmMarkers?:{time:string;text:string;direction:string}[] }>();
const emit = defineEmits<{ cursorChange: [index: number] }>();
const el = ref<HTMLDivElement>();
const selectedRange = ref("1y");
const secondary = ref("MACD");
const mainIndicator = ref("MA");
const quantityMode = ref<QuantityMode>('volume');
const quantityMAPeriods = ref([5,10]);
const quantityMAPeriodOptions = [5,10,20,60];
const quantityMAColors: Record<number,string> = {5:'#b78012',10:'#2458a6',20:'#8755a1',60:'#17806d'};
const quantityValues = computed(() => props.data.bars.map(b=>{
  if (quantityMode.value === 'volume') return b.volume;
  const amount = b.amount == null ? null : Number(b.amount);
  return amount != null && Number.isFinite(amount) ? amount : null;
}));
const quantityMeans = computed(()=>quantityMAPeriodOptions.map(period=>({period,values:quantityAverage(quantityValues.value,period)})));
const quantityOptions = [{value:'volume',label:'成交量',description:'当前K线周期成交股数'},{value:'amount',label:'成交额',description:'来源实际成交金额；缺失不估算'}];
const secondaryConfig = computed(() => secondaryIndicators.find(x => x.id === secondary.value)!);
const mainConfig = computed(() => mainIndicators.find(x => x.id === mainIndicator.value)!);
const maSettings = ref(readMas());
const maColors = ['#b78012','#2458a6','#8755a1','#17806d','#c45236','#68707a','#b23d78','#655a9e'];
const maUnit = computed(()=>props.data.timeframe==='1w' ? '周' : props.data.timeframe==='1mo' ? '月' : '日');
const mainOptions = mainIndicators.map(x=>({value:x.id,label:x.name,description:x.description}));
const secondaryOptions = secondaryIndicators.map(x=>({value:x.id,label:x.id,description:x.parameters}));
const panePositions = ref({volume:0,secondary:0});
const adjustmentLabel = computed(()=>props.data.adjustment==='QFQ' ? '前复权' : props.data.adjustment==='HFQ' ? '后复权' : '除权 / 不复权');
const last = ref<Record<string, string | number | null>>({});
let chart: IChartApi | undefined;
let resize: ResizeObserver | undefined;
let candles: ISeriesApi<"Candlestick", Time> | undefined;
let volume: ISeriesApi<"Histogram", Time> | undefined;
let histogram: ISeriesApi<"Histogram", Time> | undefined;
let markers: ISeriesMarkersPluginApi<Time> | undefined;
const movingAverages = new Map<number, ISeriesApi<"Line", Time>>();
const indicatorLines = new Map<string, ISeriesApi<"Line", Time>>();
const mainLines = new Map<string, ISeriesApi<"Line", Time>>();
const referenceLines = new Map<string, ISeriesApi<"Line", Time>[]>();
const quantityLines = new Map<number, ISeriesApi<"Line", Time>>();
const indicatorMarkers = new Map<string, ISeriesMarkersPluginApi<Time>>();
const rangeChoices = [
  { id: "1w", label: "一周", days: 5 },
  { id: "1m", label: "一月", days: 22 },
  { id: "3m", label: "三月", days: 66 },
  { id: "6m", label: "半年", days: 125 },
  { id: "1y", label: "一年", days: 250 },
  { id: "3y", label: "三年", days: 750 },
  { id: "5y", label: "五年", days: 1250 },
  { id: "all", label: "全部", days: Infinity },
];
const isDynamic = computed(() => !!props.data.current_bar && last.value.time === props.data.current_bar.time);
const quoteTime = computed(() => props.data.current_bar
  ? new Date(props.data.current_bar.source_time).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
  : '');
const currentValues = computed(() => [
  { label: "开", value: last.value.open },
  { label: "高", value: last.value.high },
  { label: "低", value: last.value.low },
  { label: isDynamic.value ? "最新" : "收", value: last.value.close },
]);
const cursorIndex = ref(-1);
const barIndexByDate = computed(() => new Map(props.data.bars.map((bar,index)=>[bar.time.slice(0,10),index])));
const indicatorValues = computed(() => {
  const index =
    cursorIndex.value >= 0 ? cursorIndex.value : props.data.bars.length - 1;
  const items = secondaryConfig.value.lines.map(line => ({ label: line.label, value: indicatorNumber(props.data.indicators[line.key]?.[index]) }));
  if (secondary.value === 'MACD') items.push({ label:'MACD', value: indicatorNumber(props.data.indicators.macd?.[index]) });
  return items;
});
const mainValues = computed(() => {
  const index = cursorIndex.value >= 0 ? cursorIndex.value : props.data.bars.length - 1;
  return mainConfig.value.lines.map(line => ({ label:line.label, value:indicatorNumber(props.data.indicators[line.key]?.[index]) }));
});

const maValues = computed(() => {
  const index =
    cursorIndex.value >= 0 ? cursorIndex.value : props.data.bars.length - 1;
  return maSettings.value.flatMap((setting,slot)=>setting.visible ? [{period:setting.period,color:maColors[slot],
    value:indicatorNumber(movingAverage(props.data.bars.map(b=>Number(b.close)),setting.period)[index])}] : []);
});
const selectedQuantityIndex = computed(()=>cursorIndex.value>=0 ? cursorIndex.value : props.data.bars.length-1);
const selectedQuantity = computed(()=>quantityText(quantityValues.value[selectedQuantityIndex.value],quantityMode.value));
function toggleQuantityMA(period:number, checked:boolean) {
  quantityMAPeriods.value = checked
    ? [...new Set([...quantityMAPeriods.value,period])].sort((a,b)=>a-b)
    : quantityMAPeriods.value.filter(item=>item!==period);
}
const quantityUnavailable = computed(()=>!quantityValues.value.some(value=>value!=null));
const quantityCoverage = computed(() => {
  const known = quantityValues.value.filter(value=>value!=null).length;
  return `${known.toLocaleString('zh-CN')} / ${quantityValues.value.length.toLocaleString('zh-CN')}`;
});
const referenceLevels: Record<string, { value:number; label:string }[]> = {
  MACD: [{value:0,label:'零轴'}],
  KDJ: [{value:20,label:'超卖20'},{value:50,label:'中轴50'},{value:80,label:'超买80'}],
  RSI: [{value:30,label:'超卖30'},{value:50,label:'中轴50'},{value:70,label:'超买70'}],
  'W&R': [{value:20,label:'超买20'},{value:50,label:'中轴50'},{value:80,label:'超卖80'}],
  MTM: [{value:0,label:'零轴'}],
  VR: [{value:100,label:'平衡100'}],
  ARBR: [{value:100,label:'平衡100'}],
  DMI: [{value:20,label:'趋势20'}],
  BIAS: [{value:0,label:'零轴'}],
  DMA: [{value:0,label:'零轴'}],
  ASI: [{value:0,label:'零轴'}],
  TRIX: [{value:0,label:'零轴'}],
  DPO: [{value:0,label:'零轴'}],
  CCI: [{value:-100,label:'超卖-100'},{value:0,label:'零轴'},{value:100,label:'超买100'}],
  ROC: [{value:0,label:'零轴'}],
  MFI: [{value:20,label:'超卖20'},{value:50,label:'中轴50'},{value:80,label:'超买80'}],
  PVT: [{value:0,label:'零轴'}],
  ADL: [{value:0,label:'零轴'}],
};
function referenceFor(indicator:string) { return referenceLevels[indicator] ?? []; }
const indicatorReferenceText = computed(() => referenceFor(secondary.value).map(item=>item.label).join(' · '));
function positionPanes() {
  const panes=chart?.panes();
  if(panes?.length===3) panePositions.value={volume:panes[PANE.PRICE]!.getHeight()+2,secondary:panes[PANE.PRICE]!.getHeight()+panes[PANE.QUANTITY]!.getHeight()+4};
}
let firstTime = "";

function timeFor(bar: (typeof props.data.bars)[number]): Time {
  return bar.time.slice(0, 10) as Time;
}

function setRange() {
  if (!chart || !props.data.bars.length) return;
  if (selectedRange.value === "all") {
    chart.timeScale().fitContent();
    return;
  }
  const choice = rangeChoices.find((item) => item.id === selectedRange.value);
  if (!choice) return;
  const date = new Date(
    props.data.bars.at(-1)!.time.slice(0, 10) + "T00:00:00Z",
  );
  if (choice.id === "1w") date.setUTCDate(date.getUTCDate() - 7);
  if (choice.id === "1m") date.setUTCMonth(date.getUTCMonth() - 1);
  if (choice.id === "3m") date.setUTCMonth(date.getUTCMonth() - 3);
  if (choice.id === "6m") date.setUTCMonth(date.getUTCMonth() - 6);
  if (choice.id === "1y") date.setUTCFullYear(date.getUTCFullYear() - 1);
  if (choice.id === "3y") date.setUTCFullYear(date.getUTCFullYear() - 3);
  if (choice.id === "5y") date.setUTCFullYear(date.getUTCFullYear() - 5);
  const cutoff = date.toISOString().slice(0, 10);
  const start = props.data.bars.findIndex((bar) => bar.time >= cutoff);
  const end = props.data.bars.length - 1;
  chart
    .timeScale()
    .setVisibleLogicalRange({ from: Math.max(0, start), to: end + 1 });
}

function selectRange(range: string) {
  selectedRange.value = range;
  chart?.applyOptions({ handleScale: { mouseWheel: range !== "all" } });
  setRange();
}

function preserveTimeRange(work: () => void) {
  const visible = chart?.timeScale().getVisibleLogicalRange();
  work();
  if (visible) requestAnimationFrame(() => chart?.timeScale().setVisibleLogicalRange(visible));
}

function syncMarkers(rows: typeof props.data.bars) {
  if (!markers) return;
  const times = new Set(rows.map((bar) => bar.time.slice(0, 10)));
  markers.setMarkers(
    [...props.signals
      .filter((signal) => times.has(signal.confirmed_at.slice(0, 10)))
      .map((signal) => ({
        time: signal.confirmed_at.slice(0, 10) as Time,
        position: signal.kind.includes("SELL") ? "aboveBar" : "belowBar",
        color: signal.status === "CONFIRMED" ? "#2458a6" : "#9b9b9b",
        shape: signal.kind === "WATCH" ? "circle" : signal.kind.includes("SELL") ? "arrowDown" : "arrowUp",
        text: signal.kind === "WATCH" ? "关注" : signal.kind.includes("SELL") ? "卖出" : "买入",
      }) satisfies SeriesMarker<Time>),
      ...(props.algorithmMarkers ?? []).filter(m => times.has(m.time.slice(0,10))).map(m=>({time:m.time.slice(0,10) as Time,position:'belowBar' as const,color:'#2458a6',shape:'circle' as const,text:m.text})),
      ...(props.events ?? []).filter(event => times.has(event.date)).map(event => ({
        time:event.date as Time, position:'aboveBar' as const, color:'#8755a1',
        shape:'circle' as const, text:event.kind === 'ex_dividend' ? '除权' : '财报',
      })),
    ].sort((a, b) => String(a.time).localeCompare(String(b.time))),
  );
}

function syncIndicatorMarkers(rows: typeof props.data.bars) {
  const signals = calculateIndicatorSignals(secondary.value, props.data.indicators, rows.map(bar => Number(bar.close)));
  const active = indicatorMarkers.get(secondary.value);
  for (const [indicator, plugin] of indicatorMarkers) {
    if (plugin !== active) {
      plugin.setMarkers([]);
      continue;
    }
    plugin.setMarkers(signals.map(signal => ({
      time: timeFor(rows[signal.index]!) as Time,
      position: signal.kind === 'BUY' ? 'belowBar' : 'aboveBar',
      color: signal.kind === 'BUY' ? '#b42332' : '#087f5b',
      shape: ['W&R', 'RSI', 'MFI', 'CCI'].includes(indicator)
        ? 'circle'
        : signal.kind === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: signal.kind === 'BUY' ? '买' : '卖',
    }) satisfies SeriesMarker<Time>));
  }
}

function syncData() {
  if (!candles || !volume || !histogram || !markers) return;
  const rows = props.data.bars;
  const previousRange = chart?.timeScale().getVisibleRange();
  const prepended = firstTime !== "" && firstTime !== rows[0]?.time;
  const toLine = (key: string) =>
    rows.flatMap((bar, i) => {
      const value = props.data.indicators[key]?.[i];
      return value === null || value === undefined
        ? []
        : [{ time: timeFor(bar), value: Number(value) }];
    });
  candles.setData(
    rows.map((bar) => ({
      time: timeFor(bar),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    })),
  );
  for (const [slot, series] of movingAverages) {
    const values=movingAverage(rows.map(b=>Number(b.close)),maSettings.value[slot]!.period);
    series.setData(rows.flatMap((bar,i)=>values[i]==null ? [] : [{time:timeFor(bar),value:values[i]!}]));
  }
  syncQuantity();
  histogram.setData(
    rows.flatMap((bar, i) => {
      const value = props.data.indicators.macd?.[i];
      return value == null
        ? []
        : [
            {
              time: timeFor(bar),
              value: Number(value),
              color: Number(value) >= 0 ? "#b4233280" : "#087f5b80",
            },
          ];
    }),
  );
  for (const [key, series] of [...indicatorLines, ...mainLines]) series.setData(toLine(key));
  for (const [key, lines] of referenceLines) {
    referenceFor(key).forEach((item, index) => lines[index]?.setData(rows.map(bar => ({ time:timeFor(bar), value:item.value }))));
  }
  syncMarkers(rows);
  syncIndicatorMarkers(rows);
  const latest = rows.at(-1);
  const selected = rows[cursorIndex.value] ?? latest;
  if (selected)
    last.value = {
      time: selected.time,
      open: selected.open,
      high: selected.high,
      low: selected.low,
      close: selected.close,
      volume: selected.volume,
    };
  if (prepended && selectedRange.value === "all")
    chart?.timeScale().fitContent();
  else if (prepended && previousRange)
    chart?.timeScale().setVisibleRange(previousRange);
  firstTime = rows[0]?.time ?? "";
}

function syncQuantity() {
  if(!volume) return;
  volume.setData(props.data.bars.map((bar,i)=>({time:timeFor(bar),...(quantityValues.value[i]==null ? {} : {
    value:quantityValues.value[i]!,color:Number(bar.close)>=Number(bar.open)?'#b42332':'#087f5b'})})));
  for(const {period,values} of quantityMeans.value) {
    const line=quantityLines.get(period);
    line?.setData(props.data.bars.map((bar,i)=>({time:timeFor(bar),...(values[i]==null ? {} : {value:values[i]!})})));
    line?.applyOptions({visible:quantityMAPeriods.value.includes(period)});
  }
}
function setIndicator() {
  preserveTimeRange(() => {
    histogram?.applyOptions({ visible: secondary.value === 'MACD' });
    const visible = new Set(secondaryConfig.value.lines.map(line => line.key));
    for (const [key, line] of indicatorLines) line.applyOptions({ visible: visible.has(key) });
    for (const [key, lines] of referenceLines) {
      const show = referenceFor(key).length > 0 && key === secondary.value;
      for (const line of lines) line.applyOptions({ visible: show });
    }
    syncIndicatorMarkers(props.data.bars);
  });
}
function setMainIndicator() {
  preserveTimeRange(() => {
    const visible = new Set(mainConfig.value.lines.map(line => line.key));
    for (const [key, line] of mainLines) line.applyOptions({ visible: visible.has(key) });
    for (const [slot, line] of movingAverages) line.applyOptions({ visible: mainIndicator.value === 'MA' && maSettings.value[slot]!.visible });
  });
}

function updateLegend(param: MouseEventParams<Time>) {
  if (!candles) return;
  const time =
    typeof param.time === "object"
      ? `${param.time.year}-${String(param.time.month).padStart(2, "0")}-${String(param.time.day).padStart(2, "0")}`
      : String(param.time ?? "");
  cursorIndex.value = barIndexByDate.value.get(time) ?? -1;
  emit('cursorChange', cursorIndex.value);
  const bar = props.data.bars[cursorIndex.value] ?? props.data.bars.at(-1);
  if (bar)
    last.value = {
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
    };
}

function create() {
  if (!el.value) return;
  if (props.data.timeframe === "1w") selectedRange.value = "3y";
  if (props.data.timeframe === "1mo") selectedRange.value = "all";
  chart = createChart(el.value, {
    height: el.value.clientHeight,
    width: el.value.clientWidth,
    layout: {
      background: { color: "#fffef9" },
      textColor: "#505563",
      fontFamily: "Consolas, monospace",
      attributionLogo: false,
      panes:{separatorColor:'#d8d1bd',separatorHoverColor:'#f6ce45',enableResize:false},
    },
    grid: { vertLines: { color: "#f0eee6" }, horzLines: { color: "#eae8df" } },
    rightPriceScale: {
      borderColor: "#d6d5ce",
      scaleMargins: { top: 0.09, bottom: 0.08 },
    },
    timeScale: {
      borderColor: "#d6d5ce",
      rightOffset: 0,
      fixRightEdge: true,
      rightBarStaysOnScroll: true,
      lockVisibleTimeRangeOnResize: true,
      minBarSpacing: 0.05,
      barSpacing: 8,
    },
    handleScale: { mouseWheel: selectedRange.value !== "all" },
    crosshair: {
      vertLine: { labelBackgroundColor: "#24262b" },
      horzLine: { labelBackgroundColor: "#24262b" },
    },
    localization: { locale: "zh-CN" },
  });
  chart.addPane();
  chart.addPane();
  chart.panes()[PANE.PRICE].setStretchFactor(0.50);
  chart.panes()[PANE.QUANTITY].setStretchFactor(0.22);
  chart.panes()[PANE.INDICATOR].setStretchFactor(0.28);
  candles = chart.addSeries(
    CandlestickSeries,
    {
      upColor: "#b42332",
      downColor: "#087f5b",
      borderVisible: false,
      wickUpColor: "#b42332",
      wickDownColor: "#087f5b",
    },
    PANE.PRICE,
  );
  for (const [slot,setting] of maSettings.value.entries()) {
    movingAverages.set(
      slot,
      chart.addSeries(
        LineSeries,
        {
          color: maColors[slot],
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
          visible: setting.visible,
        },
        PANE.PRICE,
      ),
    );
  }
  volume = chart.addSeries(
    HistogramSeries,
    {
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    },
    PANE.QUANTITY,
  );
  volume
    .priceScale()
    .applyOptions({ scaleMargins: { top: 0.16, bottom: 0.04 }, visible: true });
  for(const period of quantityMAPeriodOptions) quantityLines.set(period,chart.addSeries(LineSeries,
    {color:quantityMAColors[period],lineWidth:1,priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:quantityMAPeriods.value.includes(period)},PANE.QUANTITY));
  histogram = chart.addSeries(
    HistogramSeries,
    {
      priceFormat: { type: "price", precision: 3, minMove: 0.001 },
      lastValueVisible: false,
      priceLineVisible: false,
    },
    PANE.INDICATOR,
  );
  for (const config of secondaryIndicators) {
    for (const {key,color} of config.lines) {
      indicatorLines.set(key, chart.addSeries(LineSeries, { color, lineWidth:1, priceLineVisible:false,
        lastValueVisible:false, visible:false, priceFormat:{type:'price',precision:3,minMove:0.001} },PANE.INDICATOR));
    }
    referenceLines.set(config.id, referenceFor(config.id).map((item) => chart!.addSeries(LineSeries, {
      color:'#b9ad8d', lineWidth:1, lineStyle:LineStyle.Dashed, priceLineVisible:false,
      lastValueVisible:false, visible:false, crosshairMarkerVisible:false,
      priceFormat:{type:'price',precision:3,minMove:0.001},
    },PANE.INDICATOR)));
    const anchor = indicatorSignalAnchor(config.id);
    const anchorSeries = anchor ? indicatorLines.get(anchor) : undefined;
    if (anchorSeries) indicatorMarkers.set(config.id, createSeriesMarkers(anchorSeries, []));
  }
  for (const config of mainIndicators) {
    for (const {key,color} of config.lines) {
      mainLines.set(key, chart.addSeries(LineSeries, { color, lineWidth:1, priceLineVisible:false,
        lastValueVisible:false, visible:false, ...(key === 'sar' ? { lineVisible:false, pointMarkersVisible:true, pointMarkersRadius:2 } : {}) },PANE.PRICE));
    }
  }
  markers = createSeriesMarkers(candles, []);
  histogram.priceScale().applyOptions({scaleMargins:{top:0.3,bottom:0.08}});
  chart.subscribeCrosshairMove(updateLegend);
  syncData();
  setIndicator();
  setMainIndicator();
  requestAnimationFrame(setRange);
  requestAnimationFrame(positionPanes);
}

onMounted(() => {
  create();
  resize = new ResizeObserver(() => {
    if (!chart || !el.value?.clientWidth || !el.value.clientHeight) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    chart.resize(el.value.clientWidth, el.value.clientHeight);
    if (range) chart.timeScale().setVisibleLogicalRange(range);
    requestAnimationFrame(positionPanes);
  });
  if (el.value) resize.observe(el.value);
});
watch(() => props.data, syncData);
watch(() => props.signals, syncData);
watch(secondary, setIndicator);
watch(mainIndicator, setMainIndicator);
watch([quantityMode,quantityMAPeriods],syncQuantity);
watch(() => props.events, syncData);
watch(() => props.algorithmMarkers, syncData, {deep:true});
watch(maSettings, (settings)=>{
  if(settings.some(s=>!Number.isInteger(s.period) || s.period<1 || s.period>500)) return;
  saveMas(settings); syncData(); setMainIndicator();
}, {deep:true});
onUnmounted(() => {
  resize?.disconnect();
  chart?.unsubscribeCrosshairMove(updateLegend);
  chart?.remove();
});
</script>

<template>
  <div class="chart-control-strip">
    <div class="tabs chart-ranges" aria-label="K线显示范围">
      <button v-for="choice in rangeChoices" :key="choice.id" :class="{active:selectedRange===choice.id}" :aria-pressed="selectedRange===choice.id" @click="selectRange(choice.id)">{{ choice.label }}</button>
    </div>
    <span class="chart-adjustment-label">{{ adjustmentLabel }}</span>
  </div>
  <div class="indicator-control-row main-indicator-row"><strong>主图</strong><IndicatorTabs v-model="mainIndicator" label="主图指标" :options="mainOptions" /></div>
  <div class="chart-legend" aria-live="polite">
    <span class="chart-date">{{ last.time }}</span>
    <span v-if="isDynamic" class="badge" :class="{stale:data.current_bar?.stale}" :title="'当日快照随行情刷新，尚未归入完成历史'">当日动态 · {{ quoteTime }}{{ data.current_bar?.stale ? ' · 缓存' : '' }}</span>
    <span v-for="item in currentValues" :key="item.label">{{ item.label }} <strong>{{ item.value ?? '—' }}</strong></span>
  </div>
  <div v-if="mainIndicator==='MA'" class="chart-legend chart-ma-values">
    <details class="ma-picker"><summary>均线设置 <span>{{ maValues.length }} 条已选</span></summary>
      <div class="ma-settings">
        <strong>均线周期与显示</strong><p>当前为{{ maUnit }}K，周期单位为{{ maUnit }}；勾选即显示。</p>
        <label v-for="(setting,slot) in maSettings" :key="slot"><input type="checkbox" v-model="setting.visible" :aria-label="`显示第${slot+1}条均线`" /><i :style="{background:maColors[slot]}"></i><input type="number" v-model.number="setting.period" min="1" max="500" step="1" :aria-label="`第${slot+1}条均线周期`" />{{ maUnit }}均线</label>
        <button class="text-button" @click="maSettings=defaultMas()">恢复默认</button>
      </div>
    </details>
    <span v-for="(item,i) in maValues" :key="i" :style="{color:item.color}">MA{{ item.period }} <strong :style="{color:item.color}">{{ item.value }}</strong></span>
  </div>
  <div v-else class="chart-legend chart-ma-values"><span :title="mainConfig.description">{{ mainConfig.name }} ({{ mainConfig.parameters }})</span><span v-for="item in mainValues" :key="item.label">{{ item.label }} <strong>{{ item.value }}</strong></span><small class="indicator-help">{{ mainConfig.description }}</small></div>
  <div class="chart-stack">
    <div ref="el" class="stock-chart" aria-label="K线图，支持缩放、拖动、均线和技术指标" />
    <div class="pane-heading volume-heading" :style="{top:panePositions.volume+'px'}"><strong>{{ quantityMode==='volume' ? '成交量' : '成交额' }}</strong><span class="quantity-current">{{ selectedQuantity }}</span><span class="quantity-coverage">已载入 {{ quantityCoverage }}</span><span v-if="quantityMAPeriods.length && !quantityUnavailable" class="quantity-average-values"><span v-for="item in quantityMeans.filter(item=>quantityMAPeriods.includes(item.period))" :key="item.period" :style="{color:quantityMAColors[item.period]}">MA{{ item.period }} {{ quantityText(item.values[selectedQuantityIndex],quantityMode) }}</span></span><span v-if="quantityUnavailable" class="quantity-unavailable">来源未提供该周期{{ quantityMode==='volume' ? '成交量' : '成交额' }}</span></div>
    <div class="pane-heading secondary-heading" :style="{top:panePositions.secondary+'px'}"><strong>{{ secondary }}</strong><span class="pane-values"><span v-for="item in indicatorValues" :key="item.label">{{ item.label }} <b>{{ item.value }}</b></span></span><small v-if="indicatorReferenceText" class="indicator-reference">{{ indicatorReferenceText }}</small></div>
  </div>
  <div class="chart-pane-controls quantity-pane-controls"><div class="indicator-control-row"><strong>量图</strong><IndicatorTabs v-model="quantityMode" label="量图指标" :options="quantityOptions" /><span class="quantity-ma-controls" role="group" aria-label="均量线周期"><label v-for="period in quantityMAPeriodOptions" :key="period" class="quantity-ma-toggle" :style="{color:quantityMAColors[period]}"><input type="checkbox" :checked="quantityMAPeriods.includes(period)" :aria-label="`显示MA${period}均量线`" @change="toggleQuantityMA(period,($event.target as HTMLInputElement).checked)" />MA{{ period }}</label></span><span class="quantity-unit">{{ quantityMode==='volume' ? '单位：股' : '单位：元' }}</span><details class="quantity-unavailable-menu"><summary>更多量指标</summary><span title="历史换手率序列尚未接入">换手率：缺历史数据</span><span title="需逐笔主动买卖方向数据">内盘 / 外盘：缺逐笔数据</span><span title="需核对同花顺具体公式口径">立桩成交量：公式待核对</span><span title="需可验证的分时实时量及预测口径">虚拟成交量：待接入实时预测</span><span title="资金流、持仓、两融数据源未接入">资金 / 持仓 / 两融：缺数据源</span></details></div></div>
  <div class="chart-pane-controls secondary-pane-controls"><div class="indicator-control-row"><strong>副图</strong><IndicatorTabs v-model="secondary" label="副图指标选择" :options="secondaryOptions" /></div></div>
  <div class="chart-bottomline"><span>{{ data.bars[0]?.time }} — {{ data.bars.at(-1)?.time }} · {{ data.bars.length.toLocaleString() }} 根</span><span v-if="data.history_source">{{ data.history_source }}</span><span>{{ selectedRange==='all' ? '已显示全部历史' : '滚轮缩放 · 拖动查看历史' }}</span></div>
</template>
