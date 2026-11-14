import { describe, expect, it } from 'vitest';
import { amountWan, olderChart, quoteDay, quoteTime } from './watchlistQuote';

describe('自选行情展示口径', () => {
  it('元转换为万元且保留零与缺失的区别', () => {
    expect(amountWan('823330000')).toBe('82,333.00');
    expect(amountWan('0')).toBe('0.00');
    expect(amountWan(null)).toBe('—');
    expect(amountWan('invalid')).toBe('—');
  });
  it('统一北京时间及跨日的分时日期比较', () => {
    expect(quoteTime('2026-11-05T07:00:00Z')).toBe('15:00:00');
    expect(quoteDay('2026-11-04T17:00:00Z')).toBe('2026-11-05');
    expect(olderChart('2026-11-03', '2026-11-05T07:00:00Z')).toBe(true);
    expect(olderChart('2026-11-05', '2026-11-05T07:00:00Z')).toBe(false);
    expect(olderChart(undefined, null)).toBe(false);
  });
});
