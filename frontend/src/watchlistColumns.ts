import type { Quote, WatchItem } from './types';
import { direction, money } from './format';
import { priceDirection } from './stockQuote';
import { quoteTime } from './watchlistQuote';

type QuoteKey = 'price' | 'change_pct' | 'change' | 'amount' | 'volume' | 'turnover_rate' | 'volume_ratio' | 'amplitude' | 'open' | 'high' | 'low' | 'previous_close' | 'pe_ttm' | 'float_market_cap';
export type ColumnKey = QuoteKey | 'name' | 'code' | 'bid' | 'ask' | 'time';
export type WatchColumn = { key: ColumnKey; label: string; width: number; unit?: string; required?: boolean; default?: boolean };
export const watchColumns: WatchColumn[] = [
  { key:'name', label:'股票名称', width:116, required:true },
  { key:'code', label:'股票代码', width:78, required:true },
  { key:'price', label:'最新价', width:72, required:true },
  { key:'change_pct', label:'涨跌幅', width:82, required:true },
  { key:'change', label:'涨跌额', width:72, default:true },
  { key:'amount', label:'成交额', unit:'万元', width:120, default:true },
  { key:'volume', label:'成交量', unit:'手', width:108, default:true },
  { key:'turnover_rate', label:'换手率', width:78, default:true },
  { key:'volume_ratio', label:'量比', width:58, default:true },
  { key:'amplitude', label:'振幅', width:78, default:true },
  { key:'bid', label:'买一价', width:100 },
  { key:'ask', label:'卖一价', width:100 },
  { key:'open', label:'今开', width:100 },
  { key:'high', label:'最高', width:100 },
  { key:'low', label:'最低', width:100 },
  { key:'previous_close', label:'昨收', width:100 },
  { key:'pe_ttm', label:'市盈率', unit:'TTM', width:120 },
  { key:'float_market_cap', label:'流通市值', unit:'亿元', width:152 },
  { key:'time', label:'报价时间', width:132 },
];
export const defaultColumns = watchColumns.filter(c=>c.required || c.default).map(c=>c.key);
export function normalizeColumns(value: unknown): ColumnKey[] {
  if (!Array.isArray(value)) return [...defaultColumns];
  return watchColumns.filter(c=>c.required || value.includes(c.key)).map(c=>c.key);
}
export function securityColumnValue(security: WatchItem['security'], key: ColumnKey): string | number | null {
  if (key==='name' || key==='code') return security[key];
  const quote=security.quote;
  if (key==='time') {
    const value=quote?.as_of ? Date.parse(quote.as_of) : NaN;
    return Number.isFinite(value) ? value : null;
  }
  const raw = key==='bid' || key==='ask'
    ? quote?.order_book?.[key==='bid' ? 'bids' : 'asks'].find(level=>level.level===1)?.price
    : quote?.[key];
  if (raw==null || raw==='') return null;
  const value=Number(raw);
  return Number.isFinite(value) ? value : null;
}
export function columnValue(item: WatchItem, key: ColumnKey): string | number | null {
  return securityColumnValue(item.security,key);
}
export function columnText(item: WatchItem, key: ColumnKey) {
  return securityColumnText(item.security,key);
}
export function securityColumnText(security: WatchItem['security'], key: ColumnKey) {
  const value=securityColumnValue(security,key);
  if (value==null) return '—';
  if (key==='name' || key==='code') return String(value);
  if (key==='time') return quoteTime(security.quote?.as_of);
  const n=Number(value);
  if (key==='amount') return money(n/10000);
  if (key==='float_market_cap') return money(n/1e8);
  // 接口统一为股，包含科创板；不能再次沿用上游手数。
  if (key==='volume') return money(n/100, n%100===0 ? 0 : 2);
  const text=money(n);
  if (key==='change' || key==='change_pct') return `${n>0 ? '+' : ''}${text}${key==='change_pct' ? '%' : ''}`;
  if (key==='turnover_rate' || key==='amplitude') return text+'%';
  return text;
}
const collator=new Intl.Collator('zh-CN',{numeric:true});
export function sortWatches(items: WatchItem[], key: ColumnKey | null, direction: 'asc' | 'desc') {
  if (!key) return items;
  return [...items].sort((a,b)=>{
    const left=columnValue(a,key), right=columnValue(b,key);
    // 双向排序均将未知值置后，保留真实的0和负数。
    if (left==null || right==null) return left==null ? right==null ? 0 : 1 : -1;
    const order=typeof left==='string' && typeof right==='string' ? collator.compare(left,right) : Number(left)-Number(right);
    return direction==='asc' ? order : -order;
  });
}
export function columnDirection(quote: Quote | null, key: ColumnKey) {
  if (!quote) return '';
  if (['price','change_pct','change'].includes(key)) return direction(quote.change_pct);
  if (['bid','ask','open','high','low'].includes(key)) {
    const raw=key==='bid' || key==='ask' ? quote.order_book?.[key==='bid' ? 'bids' : 'asks'].find(x=>x.level===1)?.price : quote[key as 'open'|'high'|'low'];
    return priceDirection(raw,quote.previous_close);
  }
  return '';
}
