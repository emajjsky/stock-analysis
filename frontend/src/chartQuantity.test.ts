import {describe,it,expect} from 'vitest';
import {minuteAmounts,quantityAverage} from './chartQuantity';
describe('量额指标不补造缺失数据',()=>{
  it('分时金额按同源累计额差分，缺口后不把累计额当单分钟额',()=>{
    const points=[100,250,null,500,650,600].map(cumulative_amount=>({time:'',value:'10',volume:10,cumulative_amount:cumulative_amount==null?null:String(cumulative_amount)}));
    expect(minuteAmounts(points)).toEqual([100,150,null,null,150,null]);
  });
  it('均线须有完整窗口，零成交有效，缺失不能作零',()=>{
    expect(quantityAverage([100,0,200,null,500,600,700],3)).toEqual([null,null,100,null,null,null,600]);
  });
});
