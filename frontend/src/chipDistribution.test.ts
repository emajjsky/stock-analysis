import { describe, expect, it } from 'vitest';
import { buildChipSnapshots } from './chipDistribution';
import type { Bar } from './types';

const bars:Bar[]=[
  {time:'2026-01-01',open:'10',high:'11',low:'9',close:'10',volume:100,amount:'1000'},
  {time:'2026-01-02',open:'9.5',high:'10',low:'9',close:'9.5',volume:50,amount:'475'},
];

describe('estimated chip distribution',()=>{
  it('keeps the float supply stable and places turnover near the traded range',()=>{
    const snapshots=buildChipSnapshots(bars,1000,20);
    expect(snapshots[0]?.bins.reduce((sum,bin)=>sum+bin.shares,0)).toBeCloseTo(1000);
    expect(snapshots[1]?.bins.reduce((sum,bin)=>sum+bin.shares,0)).toBeCloseTo(1000);
    expect(snapshots[1]!.profitRatio).toBeGreaterThan(snapshots[0]!.profitRatio);
    expect(snapshots[1]!.cost70[0]).toBeGreaterThanOrEqual(snapshots[1]!.cost90[0]);
    expect(snapshots[1]!.cost70[1]).toBeLessThanOrEqual(snapshots[1]!.cost90[1]);
    expect(snapshots[1]!.concentration70).toBeLessThanOrEqual(snapshots[1]!.concentration90);
    expect(snapshots[1]!.estimatedShares).toBeCloseTo(1000);
    expect(snapshots[1]!.cost90[0]).toBeLessThan(snapshots[1]!.cost90[1]);
  });
  it('does not fabricate a distribution without float shares',()=>{
    expect(buildChipSnapshots(bars,0).every(row=>row===null)).toBe(true);
  });
  it('reuses prior snapshots when only the newest bar is appended',()=>{
    const initialBars=bars.map(row=>({...row}));
    const initial=buildChipSnapshots(initialBars,1000,20);
    const appended=[...initialBars,{time:'2026-01-03',open:'9.3',high:'10',low:'9',close:'9.8',volume:25,amount:'245'}];
    const incremental=buildChipSnapshots(appended,1000,20);
    expect(incremental[0]).toBe(initial[0]);
    expect(incremental[1]).toBe(initial[1]);
    const invalidate=[{...appended[0]!,high:'11.1'},...appended.slice(1)];
    buildChipSnapshots(invalidate,1000,20);
    const complete=buildChipSnapshots(appended,1000,20);
    expect(complete.map(row=>row?.bins.map(bin=>bin.shares))).toEqual(incremental.map(row=>row?.bins.map(bin=>bin.shares)));
  });
  it('ignores malformed zero-price bars and seeds the first valid bar without volume',()=>{
    const sparse:Bar[]=[
      {time:'2026-01-01',open:'0',high:'0',low:'0',close:'0',volume:0,amount:null},
      {time:'2026-01-02',open:'10',high:'10',low:'10',close:'10',volume:0,amount:null},
      {time:'2026-01-03',open:'10',high:'11',low:'9',close:'10',volume:100,amount:'1000'},
    ];
    const snapshots=buildChipSnapshots(sparse,1000,20,'sparse-test');
    expect(snapshots[0]).toBeNull();
    expect(snapshots[1]?.estimatedShares).toBeCloseTo(1000);
    expect(snapshots[2]?.estimatedShares).toBeCloseTo(1000);
  });
});
