import { describe, expect, it } from 'vitest';
import { calculateIndicatorSignals, indicatorSignalAnchor } from './indicatorSignals';

describe('副图指标提示', () => {
  it('WR 离开超卖/超买区时在对应柱产生买卖提示', () => {
    const signals = calculateIndicatorSignals('W&R', { wr10: [88, 78, 12, 24] }, [10, 11, 10, 9]);
    expect(signals).toEqual([{ index: 1, kind: 'BUY' }, { index: 3, kind: 'SELL' }]);
    expect(indicatorSignalAnchor('W&R')).toBe('wr10');
  });

  it('MACD 和 KDJ 根据快慢线交叉判断方向', () => {
    expect(calculateIndicatorSignals('MACD', {
      macd_dif: [-1, 1, 2, -1], macd_dea: [0, 0, 1, 0],
    }, [1, 1, 1, 1])).toEqual([{ index: 1, kind: 'BUY' }, { index: 3, kind: 'SELL' }]);
    expect(calculateIndicatorSignals('KDJ', { k: [10, 30], d: [20, 20] }, [1, 1]))
      .toEqual([{ index: 1, kind: 'BUY' }]);
  });

  it('使用阈值反转和零轴穿越规则', () => {
    expect(calculateIndicatorSignals('RSI', { rsi6: [25, 31, 72, 68] }, [1, 1, 1, 1]))
      .toEqual([{ index: 1, kind: 'BUY' }, { index: 3, kind: 'SELL' }]);
    expect(calculateIndicatorSignals('ROC', { roc: [-1, 0.2] }, [1, 1]))
      .toEqual([{ index: 1, kind: 'BUY' }]);
  });

  it('预热缺值不出信号，未定义规则的指标保持无提示', () => {
    expect(calculateIndicatorSignals('W&R', { wr10: [null, 15] }, [1, 1])).toEqual([]);
    expect(calculateIndicatorSignals('ATR', { atr14: [1, 2] }, [1, 1])).toEqual([]);
    expect(calculateIndicatorSignals('VR', { vr: [60, 80] }, [1, 1])).toEqual([]);
    expect(indicatorSignalAnchor('ATR')).toBeNull();
  });
});
