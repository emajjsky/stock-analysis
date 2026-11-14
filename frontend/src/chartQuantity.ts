import type { Intraday } from './terminal';
export type QuantityMode = 'volume'|'amount';
export function quantityAverage(values:(number|null)[],period:number):(number|null)[] {
  let sum=0,missing=0;
  return values.map((value,i)=>{
    if(value==null) missing++; else sum+=value;
    if(i>=period) { const old=values[i-period]; if(old==null) missing--; else sum-=old; }
    return i>=period-1 && missing===0 ? sum/period : null;
  });
}
// 缺口后首点也未知，不能把多分钟累计额归到单个分钟柱。
export function minuteAmounts(points:Intraday['points']):(number|null)[] {
  let previous:number|null=null;
  return points.map((point,i)=>{
    const raw=point.cumulative_amount;
    const current=raw==null || raw==='' ? null : Number(raw);
    const valid=current!=null && Number.isFinite(current) && current>=0 ? current : null;
    const amount=valid!=null && (i===0 || previous!=null) ? valid-(previous ?? 0) : null;
    previous=valid;
    return amount!=null && amount>=0 ? amount : null;
  });
}
export function quantityText(value:number|null|undefined,mode:QuantityMode) {
  if(value==null || !Number.isFinite(value)) return '—';
  const unit=mode==='amount' ? '元' : '股';
  if(Math.abs(value)>=1e8) return (value/1e8).toLocaleString('zh-CN',{maximumFractionDigits:2})+'亿'+unit;
  if(Math.abs(value)>=1e4) return (value/1e4).toLocaleString('zh-CN',{maximumFractionDigits:2})+'万'+unit;
  return value.toLocaleString('zh-CN',{maximumFractionDigits:2})+' '+unit;
}
