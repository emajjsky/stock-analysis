import { describe, expect, it } from 'vitest';
import { compact, orderBookStats, priceDirection, quoteMetrics, signed } from './stockQuote';
import type { Quote } from './types';

describe('个股行情摘要', () => {
  it('紧凑显示市值和成交额，并保留缺失值', () => {
    expect(compact('16020000000', '元')).toBe('160.20亿元');
    expect(compact(null, '元')).toBe('—');
    expect(signed('-1.23', '%')).toBe('-1.23%');
    expect(priceDirection('10', '9')).toBe('up');
  });

  it('生成可读的完整行情摘要，不填造空字段', () => {
    const rows = quoteMetrics({
      price: '173.36', previous_close: '158.40', open: '159.10', high: '174.20', low: '157.80',
      change: '14.96', change_pct: '9.44', volume: 120000, amount: '98765432', as_of: null, source: 'test', mode: 'LIVE',
      turnover_rate: '2.47', amplitude: '18.94', volume_ratio: '1.37', total_market_cap: '16020000000',
    });
    expect(rows.find(x => x.label === '今开')?.value).toBe('159.10');
    expect(rows.find(x => x.label === '换手率')?.value).toBe('2.47%');
    expect(rows.find(x => x.label === '市盈率(动)')?.value).toBe('—');
    expect(rows.find(x => x.label === '今开')?.tone).toBe('up');
  });
});

describe('五档盘口统计', () => {
  const book = (): NonNullable<Quote['order_book']> => ({
    volume_unit:'LOT',
    bids:Array.from({length:5},(_,i)=>({level:i+1,price:(10-i*.01).toFixed(2),volume:100})),
    asks:Array.from({length:5},(_,i)=>({level:i+1,price:(10.01+i*.01).toFixed(2),volume:50})),
  });
  it('同一五档快照按手计算委差和委比，价差取最优档', () => {
    const data = book();
    data.asks.reverse();
    const stats = orderBookStats(data);
    expect(stats.buy).toBe(500);
    expect(stats.sell).toBe(250);
    expect(stats.difference).toBe(250);
    expect(stats.imbalance).toBeCloseTo(100/3);
    expect(stats.spread).toBeCloseTo(.01);
  });
  it('缺档不能补零计算委差，但保留另一侧有效总量', () => {
    const data = book();
    data.asks[0] = {level:1,price:null,volume:null};
    expect(orderBookStats(data)).toEqual({buy:500,sell:null,difference:null,imbalance:null,spread:null});
    data.asks.pop();
    expect(orderBookStats(data).sell).toBeNull();
  });
  it('零委托、错误单位或重复档位不产生虚假委比，交叉价差不展示', () => {
    const data = book();
    [...data.bids,...data.asks].forEach(row=>row.volume=0);
    expect(orderBookStats(data).imbalance).toBeNull();
    data.asks[0]!.price = '9.99';
    expect(orderBookStats(data).spread).toBeNull();
    data.bids[1]!.level = 1;
    expect(orderBookStats(data).buy).toBeNull();
    data.volume_unit = 'UNKNOWN' as 'LOT';
    expect(orderBookStats(data).sell).toBeNull();
    expect(orderBookStats()).toEqual({buy:null,sell:null,difference:null,imbalance:null,spread:null});
  });
});
