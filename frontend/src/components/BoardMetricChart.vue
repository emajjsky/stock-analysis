<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import {
  createChart,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import {
  marketTimeScale,
  nextMarketRange,
  restoreMarketRange,
  chartRangeAttributes,
} from "../marketChartRange";
const props = defineProps<{
  series: {
    name: string;
    color: string;
    type: "line" | "bar";
    scale?: string;
    values: { time: string; value: number }[];
  }[];
}>();
const root = ref<HTMLElement>();
let chart: IChartApi | undefined, observer: ResizeObserver | undefined;
let active: ReturnType<IChartApi["addSeries"]>[] = [];
let pointCount = 0,
  firstTime = "";
function sync() {
  if (!chart) return;
  const range = chart.timeScale().getVisibleLogicalRange();
  const times = [
    ...new Set(
      props.series.flatMap((s) =>
        s.values.filter((v) => Number.isFinite(v.value)).map((v) => v.time),
      ),
    ),
  ].sort();
  const nextRange = nextMarketRange(
    range,
    pointCount,
    times.length,
    firstTime !== times[0],
  );
  active.forEach((s) => chart!.removeSeries(s));
  active = [];
  for (const item of props.series) {
    const s = chart.addSeries(
      item.type === "bar" ? HistogramSeries : LineSeries,
      {
        color: item.color,
        lineWidth: 1,
        priceScaleId: item.scale || "right",
        priceLineVisible: false,
        lastValueVisible: false,
      },
    );
    s.setData(
      item.values
        .filter((v) => Number.isFinite(v.value))
        .map((v) => ({
          time: v.time as Time,
          value: v.value,
          ...(item.type === "bar" && v.value < 0 ? { color: "#4f9879" } : {}),
        })),
    );
    active.push(s);
  }
  restoreMarketRange(chart, nextRange);
  pointCount = times.length;
  firstTime = times[0] ?? "";
  chartRangeAttributes(
    root.value,
    pointCount,
    chart.timeScale().getVisibleLogicalRange(),
  );
}
onMounted(() => {
  if (!root.value) return;
  chart = createChart(root.value, {
    width: root.value.clientWidth,
    height: root.value.clientHeight,
    layout: {
      background: { color: "#fffef9" },
      textColor: "#857b65",
      fontSize: 10,
      attributionLogo: false,
    },
    grid: { vertLines: { visible: false }, horzLines: { color: "#eee8d7" } },
    leftPriceScale: { visible: true, borderVisible: false },
    rightPriceScale: { borderVisible: false },
    timeScale: { ...marketTimeScale, borderVisible: false },
    localization: { locale: "zh-CN" },
  });
  chart
    .timeScale()
    .subscribeVisibleLogicalRangeChange((range) =>
      chartRangeAttributes(root.value, pointCount, range),
    );
  observer = new ResizeObserver(([e]) => {
    if (chart && e && e.contentRect.width > 0 && e.contentRect.height > 0) {
      const range = nextMarketRange(
        chart.timeScale().getVisibleLogicalRange(),
        pointCount,
        pointCount,
      );
      chart.resize(
        Math.floor(e.contentRect.width),
        Math.floor(e.contentRect.height),
      );
      restoreMarketRange(chart, range);
    }
  });
  observer.observe(root.value);
  sync();
});
watch(() => props.series, sync);
onUnmounted(() => {
  observer?.disconnect();
  chart?.remove();
});
</script>
<template>
  <div class="metric-wrap">
    <div class="metric-legend">
      <span v-for="s in series" :key="s.name"
        ><i :style="{ background: s.color }" />{{ s.name }}</span
      >
    </div>
    <div ref="root" class="metric-canvas" />
  </div>
</template>
<style scoped>
.metric-wrap {
  height: 100%;
  min-height: 140px;
  display: flex;
  flex-direction: column;
}
.metric-legend {
  display: flex;
  gap: 12px;
  padding: 7px 10px;
  font-size: 11px;
  color: #85785d;
  flex-wrap: wrap;
}
.metric-legend span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.metric-legend i {
  width: 9px;
  height: 3px;
  display: inline-block;
}
.metric-canvas {
  flex: 1;
  min-height: 110px;
}
</style>
