import { describe, expect, it } from 'vitest';
import type { Quote, WatchItem } from './types';
import { columnText, columnValue, columnDirection, normalizeColumns, defaultColumns, sortWatches } from './watchlistColumns';

function stock(code: string, quote: Partial<Quote>) {
  return { id:code, security_id:code, security:{ code,name:'股票'+code,quote:quote as Quote } } as WatchItem;
}
describe('自选指标与横向比较',()=>{
  it('按接口股数转手，金额元转万元，市值元转亿元；0与缺失分开',()=>{
    const item=stock('002300',{volume:52840000,amount:'823310000',float_market_cap:'12340000000',change:'-0.18',change_pct:'-3.23',turnover_rate:'2.65',amplitude:'0'});
    expect(columnText(item,'volume')).toBe('528,400');
    expect(columnText(stock('688001',{volume:125}), 'volume')).toBe('1.25');
    expect(columnText(item,'amount')).toBe('82,331.00');
    expect(columnText(item,'float_market_cap')).toBe('123.40');
    expect(columnText(item,'change')).toBe('-0.18');
    expect(columnText(item,'change_pct')).toBe('-3.23%');
    expect(columnText(item,'turnover_rate')).toBe('2.65%');
    expect(columnText(item,'amplitude')).toBe('0.00%');
    expect(columnText(item,'pe_ttm')).toBe('—');
    expect(columnText(stock('0',{amount:'NaN'}),'amount')).toBe('—');
    expect(columnText(stock('0',{volume:0}),'volume')).toBe('0');
  });
  it('买卖价按档位取一档，不将不存在的挂单当零报价',()=>{
    const item=stock('1',{previous_close:'10', order_book:{volume_unit:'LOT',bids:[{level:2,price:'9.90',volume:100},{level:1,price:'10.10',volume:20}],asks:[{level:1,price:null,volume:null}]}});
    expect(columnValue(item,'bid')).toBe(10.1);
    expect(columnText(item,'ask')).toBe('—');
    expect(columnDirection(item.security.quote,'bid')).toBe('up');
    expect(columnDirection(item.security.quote,'ask')).toBe('');
  });
  it('数值而非文字排序，双向缺失置后，平值稳定且不改原数组',()=>{
    const items=[stock('000001',{amount:'9'}),stock('000002',{amount:null}),stock('000003',{amount:'100'}),stock('000004',{amount:'0'}),stock('000005',{amount:'9'}),stock('000006',{amount:'-2'})];
    const codes=(rows:WatchItem[])=>rows.map(w=>w.security.code);
    expect(codes(sortWatches(items,'amount','desc'))).toEqual(['000003','000001','000005','000004','000006','000002']);
    expect(codes(sortWatches(items,'amount','asc'))).toEqual(['000006','000004','000001','000005','000003','000002']);
    expect(sortWatches(items,null,'desc')).toBe(items);
    expect(codes(items)).toEqual(['000001','000002','000003','000004','000005','000006']);
    expect(codes(sortWatches(items,'code','desc'))[0]).toBe('000006');
  });
  it('损坏偏好回退默认，忽略未知列并保留必要列',()=>{
    expect(normalizeColumns(null)).toEqual(defaultColumns);
    expect(normalizeColumns({amount:true})).toEqual(defaultColumns);
    expect(normalizeColumns(['bid','bid','nonexistent'])).toEqual(['name','code','price','change_pct','bid']);
  });
});
