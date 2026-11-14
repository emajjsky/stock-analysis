<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import {
  createChart,
  LineSeries,
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { Bar } from "../types";
import { normalizedPoints, chartTimestamp, type Intraday } from "../terminal";
import {
  marketTimeScale,
  nextMarketRange,
  restoreMarketRange,
  chartRangeAttributes,
} from "../marketChartRange";

const props = defineProps<{
  mode: "intraday" | "daily";
  points?: Intraday["points"];
  bars?: Bar[];
  previousClose?: string | null;
  benchmark?: Intraday["points"];
  benchmarkClose?: string | null;
  volumeUnit?: string;
}>();
const element = ref<HTMLElement>();
let chart: IChartApi | undefined;
let price: ISeriesApi<"Line"> | ISeriesApi<"Candlestick"> | undefined;
let volume: ISeriesApi<"Histogram"> | undefined;
let averages: ISeriesApi<"Line">[] = [];
let benchmark: ISeriesApi<"Line"> | undefined;
let average: ISeriesApi<"Line"> | undefined;
let resize: ResizeObserver | undefined;
let initialized = false;
let pointCount = 0,
  firstTime = "",
  tradeDate = "";
let activeMode = props.mode;
const hover = ref("");
const numeric = (v: unknown) =>
  v != null && v !== "" && Number.isFinite(Number(v));

function sync() {
  if (!chart) return;
  const range =
    initialized && activeMode === props.mode
      ? chart.timeScale().getVisibleLogicalRange()
      : null;
  if (activeMode !== props.mode) {
    if (volume) chart.removeSeries(volume);
    averages.forEach((s) => chart!.removeSeries(s));
    if (price) chart.removeSeries(price);
    price = undefined;
    volume = undefined;
    averages = [];
    initialized = false;
    activeMode = props.mode;
  }
  const data =
    props.mode === "intraday"
      ? normalizedPoints(props.points ?? []).map((p) => ({
          time: p.time as Time,
          value:
            props.benchmark && Number(props.previousClose) > 0
              ? (Number(p.value) / Number(props.previousClose) - 1) * 100
              : Number(p.value),
          volume: p.volume,
        }))
      : (props.bars ?? [])
          .filter((b) => [b.open, b.close, b.low, b.high].every(numeric))
          .map((b) => ({
            time: b.time as Time,
            open: Number(b.open),
            close: Number(b.close),
            low: Number(b.low),
            high: Number(b.high),
            volume: b.volume,
          }));
  price ??=
    props.mode === "intraday"
      ? chart.addSeries(LineSeries, {
          color: "#2458a6",
          lineWidth: 2,
          lastValueVisible: true,
          priceLineVisible: false,
        })
      : chart.addSeries(CandlestickSeries, {
          upColor: "#b42332",
          downColor: "#087f5b",
          borderUpColor: "#b42332",
          borderDownColor: "#087f5b",
          wickUpColor: "#b42332",
          wickDownColor: "#087f5b",
          priceLineVisible: false,
        });
  const ordered = [
    ...new Map(
      data
        .filter((p) => typeof p.time !== "number" || Number.isFinite(p.time))
        .map((p) => [p.time, p]),
    ).values(),
  ].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  const first = String(ordered[0]?.time ?? "");
  const date =
    props.mode === "intraday" && ordered.length
      ? new Date(Number(ordered.at(-1)!.time) * 1000 + 8 * 3600000)
          .toISOString()
          .slice(0, 10)
      : "";
  const nextRange = nextMarketRange(
    range,
    pointCount,
    ordered.length,
    firstTime !== first || (props.mode === "intraday" && date !== tradeDate),
  );
  price.setData(ordered as never);
  if (benchmark) {
    chart.removeSeries(benchmark);
    benchmark = undefined;
  }
  if (average) {
    chart.removeSeries(average);
    average = undefined;
  }
  if (
    props.mode === "intraday" &&
    props.benchmark &&
    Number(props.previousClose) > 0 &&
    Number(props.benchmarkClose) > 0
  ) {
    benchmark = chart.addSeries(LineSeries, {
      color: "#bd922e",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    benchmark.setData(
      normalizedPoints(props.benchmark)
        .filter(
          (p) =>
            numeric(p.value) &&
            p.time >= Number(ordered[0]?.time) &&
            p.time <= Number(ordered.at(-1)?.time),
        )
        .map((p) => ({
          time: p.time as Time,
          value: (Number(p.value) / Number(props.benchmarkClose) - 1) * 100,
        })),
    );
    price.applyOptions({ priceFormat: { type: "percent" } });
  } else {
    price.applyOptions({
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    if (
      props.mode === "intraday" &&
      props.points?.some((p) => numeric(p.average_price))
    ) {
      average = chart.addSeries(LineSeries, {
        color: "#bd922e",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      average.setData(
        props.points
          .filter(
            (p) =>
              numeric(p.average_price) &&
              Number(chartTimestamp(p.time)) >= Number(ordered[0]?.time) &&
              Number(chartTimestamp(p.time)) <= Number(ordered.at(-1)?.time),
          )
          .map((p) => ({
            time: chartTimestamp(p.time) as Time,
            value: Number(p.average_price),
          })),
      );
    }
  }
  if (!volume)
    volume = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    );
  volume.setData(
    ordered
      .filter((p) => numeric(p.volume))
      .map((p, index) => ({
        time: p.time,
        value: Number(p.volume),
        color:
          index &&
          ("value" in p
            ? p.value < (ordered[index - 1] as { value: number }).value
            : p.close < p.open)
            ? "#78ab94"
            : "#d6948e",
      })),
  );
  if (props.mode === "daily") {
    for (const [index, period] of [5, 10, 20].entries()) {
      const line =
        averages[index] ??
        chart.addSeries(LineSeries, {
          color: ["#b18a25", "#2458a6", "#955c93"][index],
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
      line.setData(
        (props.bars ?? []).flatMap((bar, i, all) =>
          i < period - 1
            ? []
            : [
                {
                  time: bar.time as Time,
                  value:
                    all
                      .slice(i - period + 1, i + 1)
                      .reduce((sum, item) => sum + Number(item.close), 0) /
                    period,
                },
              ],
        ),
      );
      averages[index] = line;
    }
  }
  chart.panes()[0]?.setStretchFactor(0.79);
  chart.panes()[1]?.setStretchFactor(0.21);
  restoreMarketRange(chart, nextRange);
  pointCount = ordered.length;
  firstTime = first;
  tradeDate = date;
  chartRangeAttributes(
    element.value,
    pointCount,
    chart.timeScale().getVisibleLogicalRange(),
  );
  initialized = true;
}

onMounted(() => {
  if (!element.value) return;
  chart = createChart(element.value, {
    autoSize: false,
    width: element.value.clientWidth,
    height: element.value.clientHeight,
    layout: {
      background: { color: "#fffef9" },
      textColor: "#78766c",
      fontSize: 11,
      attributionLogo: false,
    },
    grid: { vertLines: { color: "#f1ede2" }, horzLines: { color: "#ece8dc" } },
    timeScale: {
      ...marketTimeScale,
      timeVisible: true,
      secondsVisible: false,
      borderColor: "#dcd6c5",
      tickMarkFormatter: (time: Time) =>
        typeof time === "number"
          ? new Intl.DateTimeFormat("zh-CN", {
              timeZone: "Asia/Shanghai",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).format(time * 1000)
          : String(time).slice(5),
    },
    localization: {
      locale: "zh-CN",
      timeFormatter: (time: Time) =>
        typeof time === "number"
          ? new Intl.DateTimeFormat("zh-CN", {
              timeZone: "Asia/Shanghai",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).format(time * 1000)
          : String(time),
    },
    rightPriceScale: {
      borderColor: "#e1dccc",
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
  });
  chart
    .timeScale()
    .subscribeVisibleLogicalRangeChange((range) =>
      chartRangeAttributes(element.value, pointCount, range),
    );
  chart.subscribeCrosshairMove((event) => {
    if (!price || !event.time) {
      hover.value = "";
      return;
    }
    const point = event.seriesData.get(price) as
      { value?: number; close?: number } | undefined;
    hover.value = point ? ((point.value ?? point.close)?.toFixed(2) ?? "") : "";
  });
  resize = new ResizeObserver(([entry]) => {
    if (
      !chart ||
      !entry ||
      entry.contentRect.width <= 0 ||
      entry.contentRect.height <= 0
    )
      return;
    const range = nextMarketRange(
      chart.timeScale().getVisibleLogicalRange(),
      pointCount,
      pointCount,
    );
    chart.resize(
      Math.floor(entry.contentRect.width),
      Math.floor(entry.contentRect.height),
    );
    restoreMarketRange(chart, range);
  });
  resize.observe(element.value);
  sync();
});
watch(
  () => [
    props.mode,
    props.points,
    props.bars,
    props.benchmark,
    props.previousClose,
    props.benchmarkClose,
  ],
  sync,
);
onUnmounted(() => {
  resize?.disconnect();
  chart?.remove();
});
</script>
<template>
  <div class="board-mini-chart-wrap">
    <span v-if="hover" class="board-hover-value">{{ hover }}</span>
    <span class="volume-unit">{{ volumeUnit || "成交量 / 股" }}</span>
    <div ref="element" class="board-mini-chart" aria-label="行情走势与成交量" />
  </div>
</template>
<style scoped>
.board-mini-chart-wrap {
  position: relative;
  height: 100%;
  min-height: 110px;
}
.board-mini-chart {
  width: 100%;
  height: 100%;
  min-height: 110px;
}
.board-hover-value {
  position: absolute;
  z-index: 2;
  top: 2px;
  left: 8px;
  padding: 0 4px;
  font:
    12px Consolas,
    monospace;
  background: #fffef9;
  pointer-events: none;
}
.volume-unit {
  position: absolute;
  z-index: 2;
  left: 8px;
  bottom: 43px;
  font-size: 10px;
  color: #95876c;
  background: #fffef9;
  pointer-events: none;
}
</style>
