import type { Security } from "./types";
export interface CatalogStatus {
  count: number;
  source: string | null;
  updated_at: string | null;
  status: string;
  error: string | null;
}
export interface RefreshStatus {
  enabled: boolean;
  interval_seconds: number;
  running: boolean;
  phase: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  error: string | null;
  market_open: boolean;
}
export interface IndexQuote {
  id: string;
  symbol: string;
  name: string;
  price: string | null;
  previous_close?: string | null;
  change_pct: string | null;
  volume: number | null;
  amount: string | null;
  source: string;
  source_time: string | null;
  fetched_at: string | null;
}
export interface MarketOverview {
  indices: IndexQuote[];
  breadth: {
    advancing: number | null;
    declining: number | null;
    unchanged: number | null;
    as_of: string | null;
  } | null;
  rankings: { gainers: Security[]; losers: Security[]; amount: Security[] };
  updated_at: string | null;
  status: string;
  error: string | null;
}
export interface Intraday {
  fallback?: boolean;
  primary_error?: string | null;
  previous_close?: string | null;
  average_supported?: boolean;
  trade_date?: string;
  fetched_at?: string;
  symbol: string;
  points: { time: string; value: string; volume: number | null; average_price?:string | null;
    cumulative_volume?: number | null; cumulative_amount?:string | null }[];
  indicators?: Record<string, (string | null)[]>;
  source: string;
  source_time: string | null;
  error: string | null;
}
export interface TradePrint {
  time: string;
  price: string;
  volume_lots: number;
  side: 'BUY' | 'SELL' | 'UNKNOWN';
}
export interface TradeTape {
  security_id: string;
  trades: TradePrint[];
  source: string;
  fetched_at: string;
}
export function chartTimestamp(value: string): number | null {
  const n = /^\d+(?:\.\d+)?$/.test(value)
    ? Number(value)
    : Date.parse(value) / 1000;
  return Number.isFinite(n) && n > 0 ? n : null;
}
export function normalizedPoints(points: Intraday["points"]) {
  const map = new Map<
    number,
    { time: number; value: number; volume: number | null }
  >();
  for (const p of points) {
    const time = chartTimestamp(p.time);
    const value = Number(p.value);
    if (time !== null && p.value !== "" && Number.isFinite(value))
      map.set(time, { time, value, volume: p.volume });
  }
  const sorted = [...map.values()].sort((a, b) => a.time - b.time);
  const day = sorted.at(-1)
    ? new Date(sorted.at(-1)!.time * 1000 + 8 * 3600000)
        .toISOString()
        .slice(0, 10)
    : "";
  return sorted.filter(
    (p) =>
      new Date(p.time * 1000 + 8 * 3600000).toISOString().slice(0, 10) === day,
  );
}
export function compact(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return Math.abs(n) >= 1e8
    ? `${(n / 1e8).toFixed(2)}亿`
    : Math.abs(n) >= 1e4
      ? `${(n / 1e4).toFixed(2)}万`
      : n.toLocaleString("zh-CN");
}
export function percent(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n > 0 ? "+" : ""}${n.toFixed(2)}%` : "—";
}
