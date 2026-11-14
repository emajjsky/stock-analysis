import { money } from './format';

// 成交额接口单位为元，列表和摘要统一以万元为单位，零与未知分开。
export function amountWan(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  const amount = Number(value);
  return Number.isFinite(amount) ? money(amount / 10000) : '—';
}
export function quoteTime(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value));
}
export function quoteDay(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '';
  return new Date(Date.parse(value) + 8 * 3600000).toISOString().slice(0, 10);
}
export function olderChart(chartDay?: string, quoteAt?: string | null) {
  const day = quoteDay(quoteAt);
  return Boolean(chartDay && day && chartDay < day);
}
