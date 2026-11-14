import type { Bar } from './types';

export interface ChipSnapshot {
  bins: { price: number; shares: number }[];
  averageCost: number;
  profitRatio: number;
  cost70: [number, number];
  concentration70: number;
  cost90: [number, number];
  concentration90: number;
  intervalWidthRatio: number;
  peakCost: number;
  estimatedShares: number;
}

let previous: { cacheKey: string; bars: Bar[]; floatShares: number; binCount: number; min: number; max: number; step: number; snapshots: (ChipSnapshot | null)[] } | undefined;

export function buildChipSnapshots(bars: Bar[], floatShares: number, binCount = 60, cacheKey = ''): (ChipSnapshot | null)[] {
  if (!Number.isFinite(floatShares) || floatShares <= 0 || !bars.length || binCount < 8) return bars.map(() => null);
  const lows = bars.map(bar => Number(bar.low)).filter(value => Number.isFinite(value) && value > 0);
  const highs = bars.map(bar => Number(bar.high)).filter(value => Number.isFinite(value) && value > 0);
  const min = Math.min(...lows), max = Math.max(...highs);
  if (!Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max < min) {
    previous = undefined;
    return bars.map(() => null);
  }
  const step = Math.max((max - min) / (binCount - 1), min * 0.0001);
  const prices = Array.from({length:binCount},(_,i)=>min+i*step);
  let common = 0;
  if (previous && previous.cacheKey === cacheKey && previous.floatShares === floatShares && previous.binCount === binCount && previous.min === min && previous.max === max) {
    const limit = Math.min(previous.bars.length,bars.length);
    while (common < limit) {
      const oldBar=previous.bars[common]!,bar=bars[common]!;
      if (oldBar.time!==bar.time || oldBar.low!==bar.low || oldBar.high!==bar.high || oldBar.close!==bar.close || oldBar.volume!==bar.volume) break;
      common+=1;
    }
    if (common === bars.length && common === previous.bars.length) return previous.snapshots;
  }
  const snapshots: (ChipSnapshot | null)[] = previous && common
    ? previous.snapshots.slice(0,common)
    : [];
  let lastSnapshot = common > 0 ? snapshots[common-1] : null;
  if (!lastSnapshot && common > 0) {
    for (let i=common-2;i>=0;i-=1) {
      if (snapshots[i]) { lastSnapshot=snapshots[i]!; break; }
    }
  }
  let mass = lastSnapshot ? lastSnapshot.bins.map(row=>row.shares) : Array(binCount).fill(0) as number[];

  for (let i=common;i<bars.length;i+=1) {
    const bar=bars[i]!;
    const low=Number(bar.low), high=Number(bar.high), close=Number(bar.close);
    const volume=bar.volume == null ? 0 : Number(bar.volume);
    if (![low,high,close,volume].every(Number.isFinite) || low<=0 || high<low || volume<0) {
      snapshots.push(null);
      continue;
    }
    if (!mass.some(value=>value>0)) {
      const seed=Math.max(0,Math.min(binCount-1,Math.round((close-min)/step)));
      mass[seed]=floatShares;
    } else {
      const turnover=Math.max(0,Math.min(1,volume/floatShares));
      for(let j=0;j<binCount;j+=1) mass[j]! *= 1-turnover;
      if (turnover>0) {
        const typical=(low+high+close)/3;
        const radius=Math.max((high-low)/2,step/2);
        const weights=prices.map(price=>price<low-step/2 || price>high+step/2 ? 0 : Math.max(0,1-Math.abs(price-typical)/radius));
        let total=weights.reduce((sum,value)=>sum+value,0);
        if (!total) {
          const slot=Math.max(0,Math.min(binCount-1,Math.round((close-min)/step)));
          weights[slot]=1; total=1;
        }
        for(let j=0;j<binCount;j+=1) mass[j]! += floatShares*turnover*weights[j]!/total;
      }
    }
    const shares=mass.reduce((sum,value)=>sum+value,0);
    if (!shares) { snapshots.push(null); continue; }
    let averageCost=0, profit=0;
    for(let j=0;j<binCount;j+=1) { averageCost+=prices[j]!*mass[j]!; if(prices[j]!<=close) profit+=mass[j]!; }
    averageCost/=shares;
    const percentile=(target:number) => {
      let cumulative=0;
      for(let j=0;j<binCount;j+=1) { cumulative+=mass[j]!; if(cumulative>=shares*target) return prices[j]!; }
      return prices.at(-1)!;
    };
    const low70=percentile(0.15), high70=percentile(0.85);
    const low90=percentile(0.05), high90=percentile(0.95);
    const peakCost=prices[mass.indexOf(Math.max(...mass))]!;
    const concentration=(low:number,high:number)=>(high-low)/(high+low||1);
    const concentration70=concentration(low70,high70), concentration90=concentration(low90,high90);
    snapshots.push({bins:prices.map((price,j)=>({price,shares:mass[j]!})),averageCost,
      profitRatio:profit/shares,cost70:[low70,high70],concentration70,
      cost90:[low90,high90],concentration90,
      intervalWidthRatio:(high90>low90?(high70-low70)/(high90-low90):0),
      peakCost,estimatedShares:shares});
  }
  previous = {cacheKey,bars,floatShares,binCount,min,max,step,snapshots};
  return snapshots;
}
