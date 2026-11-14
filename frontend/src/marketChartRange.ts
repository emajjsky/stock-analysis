import type { IChartApi, LogicalRange } from "lightweight-charts";

// 与自选分时一致：数据贴合左右边界，缩放可展开全量，尺寸变化不丢失视野。
export const marketTimeScale = {
  rightOffset: 0,
  fixLeftEdge: true,
  fixRightEdge: true,
  rightBarStaysOnScroll: true,
  lockVisibleTimeRangeOnResize: true,
  minBarSpacing: 0.05,
  barSpacing: 8,
};
export function nextMarketRange(
  range: { from: number; to: number } | null,
  oldCount: number,
  count: number,
  reset = false,
) {
  if (
    count < 2 ||
    reset ||
    !oldCount ||
    !range ||
    !Number.isFinite(range.from + range.to) ||
    range.to <= range.from
  )
    return null;
  const following = range.to >= oldCount - 1.5;
  const full = following && range.from <= 0.5;
  if (full || range.to - range.from >= count - 1) return null;
  const width = Math.min(Math.max(1, range.to - range.from), count - 1);
  const to = Math.min(
    count - 1,
    Math.max(width, following ? count - 1 : range.to),
  );
  return { from: to - width, to };
}
export function restoreMarketRange(
  chart: IChartApi,
  range: { from: number; to: number } | null,
) {
  if (range) chart.timeScale().setVisibleLogicalRange(range as LogicalRange);
  else chart.timeScale().fitContent();
}
export function chartRangeAttributes(
  element: HTMLElement | undefined,
  count: number,
  range: { from: number; to: number } | null,
) {
  if (!element) return;
  element.dataset.pointCount = String(count);
  element.dataset.rangeFrom = String(range?.from ?? "");
  element.dataset.rangeTo = String(range?.to ?? "");
}
