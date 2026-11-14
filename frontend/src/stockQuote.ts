import type { Quote } from './types';
import { money } from './format';

export function compact(value: unknown, unit = '') {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—';
  const n = Number(value);
  const magnitude = Math.abs(n);
  if (magnitude >= 1e8) return money(n / 1e8) + '亿' + unit;
  if (magnitude >= 1e4) return money(n / 1e4) + '万' + unit;
  return money(n, unit === '股' ? 0 : 2) + unit;
}
export function signed(value: unknown, suffix = '') {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—';
  return (Number(value) > 0 ? '+' : '') + money(value) + suffix;
}
export function priceDirection(value: unknown, previous: unknown) {
  if (value === null || value === undefined || previous === null || previous === undefined || Number(previous) <= 0) return '';
  return Number(value) > Number(previous) ? 'up' : Number(value) < Number(previous) ? 'down' : '';
}
export function orderBookStats(book?: Quote['order_book']) {
  const total = (rows: NonNullable<Quote['order_book']>['bids'] | undefined) => {
    if (book?.volume_unit !== 'LOT' || rows?.length !== 5 ||
        new Set(rows.map(row => row.level)).size !== 5 ||
        rows.some(row => row.level < 1 || row.level > 5 || !Number.isInteger(row.volume) || row.volume! < 0)) return null;
    return rows.reduce((sum,row) => sum + row.volume!,0);
  };
  const buy = total(book?.bids), sell = total(book?.asks);
  const difference = buy == null || sell == null ? null : buy - sell;
  const imbalance = difference == null || buy! + sell! === 0 ? null : difference / (buy! + sell!) * 100;
  const ask = Number(book?.asks.find(row => row.level === 1)?.price);
  const bid = Number(book?.bids.find(row => row.level === 1)?.price);
  const spread = Number.isFinite(ask) && Number.isFinite(bid) && ask > 0 && bid > 0 && ask >= bid ? ask - bid : null;
  return {buy,sell,difference,imbalance,spread};
}
export function quoteMetrics(q?: Quote | null) {
  const percent = (v: unknown) => money(v) + (v === null || v === undefined ? '' : '%');
  return [
    { label: '今开', value: money(q?.open), tone: priceDirection(q?.open, q?.previous_close) },
    { label: '最高', value: money(q?.high), tone: priceDirection(q?.high, q?.previous_close) },
    { label: '昨收', value: money(q?.previous_close) },
    { label: '最低', value: money(q?.low), tone: priceDirection(q?.low, q?.previous_close) },
    { label: '成交量', value: compact(q?.volume, '股') },
    { label: '总市值', value: compact(q?.total_market_cap, '元') },
    { label: '换手率', value: percent(q?.turnover_rate) },
    { label: '市盈率(动)', value: money(q?.pe_dynamic) },
    { label: '成交额', value: compact(q?.amount, '元') },
    { label: '量比', value: money(q?.volume_ratio) },
    { label: '振幅', value: percent(q?.amplitude) },
  ];
}
