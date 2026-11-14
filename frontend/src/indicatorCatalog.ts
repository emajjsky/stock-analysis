export type IndicatorLine = { key: string; label: string; color: string };
const colors = ['#2458a6', '#bd8616', '#8755a1', '#17806d'];
function lines(...pairs: [string, string][]): IndicatorLine[] {
  return pairs.map(([key, label], i) => ({ key, label, color: colors[i % colors.length]! }));
}
export const secondaryIndicators = [
  { id: 'MACD', parameters: '12,26,9', lines: lines(['macd_dif','DIF'],['macd_dea','DEA']), histogram: 'macd' },
  { id: 'BBI', parameters: '3,6,12,24', lines: lines(['bbi','BBI']) },
  { id: 'KDJ', parameters: '9,3,3', lines: lines(['k','K'],['d','D'],['j','J']) },
  { id: 'RSI', parameters: '6,14', lines: lines(['rsi6','RSI6'],['rsi14','RSI14']) },
  { id: 'OBV', parameters: '累计量 / MA30 · 股', lines: lines(['obv','OBV'],['obvma','MA30']) },
  { id: 'W&R', parameters: '10,6 · 0–100', lines: lines(['wr10','WR10'],['wr6','WR6']) },
  { id: 'MTM', parameters: '12,6', lines: lines(['mtm','MTM'],['mtmma','MTMMA']) },
  { id: 'VR', parameters: '26', lines: lines(['vr','VR']) },
  { id: 'ARBR', parameters: '26', lines: lines(['ar','AR'],['br','BR']) },
  { id: 'DMI', parameters: '14,6 · Wilder', lines: lines(['pdi','PDI'],['mdi','MDI'],['adx','ADX'],['adxr','ADXR']) },
  { id: 'BIAS', parameters: '6,12,24', lines: lines(['bias6','BIAS6'],['bias12','BIAS12'],['bias24','BIAS24']) },
  { id: 'DMA', parameters: '10,50,10', lines: lines(['dma','DMA'],['ama','AMA']) },
  { id: 'ASI', parameters: '26,10', lines: lines(['asi','ASI'],['asit','ASIT']) },
  { id: 'TRIX', parameters: '12,9', lines: lines(['trix','TRIX'],['trma','TRMA']) },
  { id: 'DPO', parameters: '20,11,6', lines: lines(['dpo','DPO'],['dpoma','DPOMA']) },
  { id: 'CCI', parameters: '20 · ±100', lines: lines(['cci','CCI']) },
  { id: 'ROC', parameters: '12 · %', lines: lines(['roc','ROC']) },
  { id: 'ATR', parameters: '14 · Wilder', lines: lines(['atr14','ATR14']) },
  { id: 'MFI', parameters: '14 · 0–100', lines: lines(['mfi','MFI']) },
  { id: 'EMV', parameters: '14,9 · 量价简易波动', lines: lines(['emv','EMV14'],['emv_ma','MA9']) },
  { id: 'PVT', parameters: '收盘涨跌幅 × 成交量累计', lines: lines(['pvt','PVT']) },
  { id: 'ADL', parameters: '收盘区间位置 × 成交量累计', lines: lines(['adl','ADL']) },
];
export const mainIndicators = [
  { id: 'MA', name:'均线 MA', description:'按所选周期计算收盘均价，可勾选并修改周期', parameters: '可选均线', lines: [] as IndicatorLine[] },
  { id: 'BOLL', name:'布林带 BOLL', description:'中轨为20周期均价，上下轨为均价加减2倍标准差', parameters: '20,2', lines: lines(['boll_mid','中轨'],['boll_upper','上轨'],['boll_lower','下轨']) },
  { id: 'EXPMA', name:'指数均线 EXPMA', description:'12和50周期指数平均，近期价格权重更高', parameters: '12,50', lines: lines(['expma12','EXPMA12'],['expma50','EXPMA50']) },
  { id: 'SAR', name:'抛物线 SAR', description:'点状显示跟踪转向参考位置，步长0.02、上限0.2', parameters: '0.02,0.2', lines: lines(['sar','SAR']) },
  { id: 'ENE', name:'轨道线 ENE', description:'25周期均线的上下10%价格通道', parameters: '25,10,10', lines: lines(['ene_mid','中轨'],['ene_upper','上轨'],['ene_lower','下轨']) },
];
export function indicatorNumber(value: string | number | null | undefined) {
  return value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 3 });
}
