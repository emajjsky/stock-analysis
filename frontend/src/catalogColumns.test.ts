import { describe, expect, it } from 'vitest';
import { catalogColumnsFor, catalogColumnWidths, readCatalogColumnKeys } from './catalogColumns';
import { defaultColumns, watchColumns } from './watchlistColumns';
import type { Security } from './types';

describe('证券目录行情列', () => {
  it('默认复用自选股的指标列，并跟随自选列偏好', () => {
    const storage = { getItem: () => JSON.stringify({ columns: ['amount', 'volume', 'amplitude'] }) };
    const selected = readCatalogColumnKeys(storage);
    expect(selected).toEqual(['name', 'code', 'price', 'change_pct', 'amount', 'volume', 'amplitude']);
    expect(readCatalogColumnKeys({ getItem: () => null })).toEqual(defaultColumns);
    expect(catalogColumnsFor(selected).map(column => column.key)).toEqual(selected);
    expect(catalogColumnsFor(selected).map(column => column.width)).toEqual(
      watchColumns.filter(column => selected.includes(column.key)).map(column => column.width),
    );
  });

  it('使用与自选相同的金额、成交量和涨跌格式，缺失数据不填零', () => {
    const quote = {
      price: '12.34', change: '-0.18', change_pct: '-1.44', amount: '823310000',
      volume: 52840000, turnover_rate: '2.65', volume_ratio: '1.37', amplitude: '0',
      previous_close: '12.52', open: '12.40', high: '12.60', low: '12.20',
      pe_ttm: null, float_market_cap: null, as_of: '2026-11-08T02:00:00Z',
      source: 'test', mode: 'LIVE',
    } as Security['quote'];
    const security = { id: 'LIVE.SZ.002300', code: '002300', name: '测试证券', quote } as Security;
    const row = { id: security.id, security };
    const columns = catalogColumnsFor([...defaultColumns, 'pe_ttm']);
    const value = (key: string) => columns.find(column => column.key === key)!.formatValue!(row);
    expect(value('amount')).toBe('82,331.00');
    expect(value('volume')).toBe('528,400');
    expect(value('change')).toBe('-0.18');
    expect(value('change_pct')).toBe('-1.44%');
    expect(value('amplitude')).toBe('0.00%');
    expect(value('price')).toBe('12.34');
    expect(catalogColumnWidths(columns)).toMatchObject({ name: expect.stringMatching(/%$/), code: expect.stringMatching(/%$/) });
    expect(value('pe_ttm')).toBe('—');
  });
});
