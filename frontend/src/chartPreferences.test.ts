import {describe,it,expect} from 'vitest';
import {movingAverage,defaultMas} from './chartPreferences';
describe('自定义均线',()=>{
  it('按当前K线周期计算，预热留空且不使用未来数据',()=>{
    expect(movingAverage([2,4,9,5,10],3)).toEqual([null,null,5,6,8]);
    expect(movingAverage([2,4,9],3)).toEqual(movingAverage([2,4,9,5,10],3).slice(0,3));
    expect(movingAverage([2,4,9],1)).toEqual([2,4,9]);
    expect(movingAverage([2,4],0)).toEqual([null,null]);
    expect(movingAverage([2,4],1.5)).toEqual([null,null]);
  });
	it('默认实际显示5/10/20/30/60/120，独立设置不互相污染',()=>{
		expect(defaultMas().filter(s=>s.visible).map(s=>s.period)).toEqual([5,10,20,30,60,120]);
    const a=defaultMas();a[0]!.period=7;
    expect(defaultMas()[0]!.period).toBe(5);
  });
});
