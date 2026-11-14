export type MaSetting = { period:number; visible:boolean };
export const defaultMas = ():MaSetting[] => [5,10,20,30,60,120,250,90].map((period,i)=>({period,visible:i<6}));
export function readMas():MaSetting[] {
  try {
    const value=JSON.parse(localStorage.getItem('stock-chart-ma-v1') ?? 'null');
    if (Array.isArray(value) && value.length===8 && value.every(x=>Number.isInteger(x.period) && x.period>=1 && x.period<=500 && typeof x.visible==='boolean')) {
      // 旧版本只显示四条均线，升级后补齐常用的六条；用户额外勾选的周期仍保留。
      if (value.filter(x=>x.visible).length < 6) {
        const upgraded = value.map((item, index) => ({...item, visible: item.visible || index < 6}));
        saveMas(upgraded);
        return upgraded;
      }
      return value;
    }
  } catch { /* 无本地存储时使用默认显示偏好。 */ }
  return defaultMas();
}
export function saveMas(value:MaSetting[]) { try { localStorage.setItem('stock-chart-ma-v1',JSON.stringify(value)); } catch { /* 展示设置无需阻断行情。 */ } }
export function movingAverage(values:number[],period:number):(number|null)[] {
  if (!Number.isInteger(period) || period<1 || period>500) return values.map(()=>null);
  let sum=0;
  return values.map((value,i)=>{ sum+=value; if(i>=period) sum-=values[i-period]!; return i>=period-1 ? sum/period : null; });
}
