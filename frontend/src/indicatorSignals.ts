export type IndicatorSignal = { index: number; kind: 'BUY' | 'SELL' };
export type IndicatorSeries = Record<string, (number | string | null | undefined)[]>;

function value(series: IndicatorSeries, key: string, index: number): number | null {
  const raw = series[key]?.[index];
  if (raw == null || raw === '') return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function crossed(a0: number | null, a1: number | null, b0: number | null, b1: number | null): 'BUY' | 'SELL' | null {
  if (a0 == null || a1 == null || b0 == null || b1 == null) return null;
  if (a0 <= b0 && a1 > b1) return 'BUY';
  if (a0 >= b0 && a1 < b1) return 'SELL';
  return null;
}

function zeroCross(previous: number | null, current: number | null): 'BUY' | 'SELL' | null {
  if (previous == null || current == null) return null;
  if (previous <= 0 && current > 0) return 'BUY';
  if (previous >= 0 && current < 0) return 'SELL';
  return null;
}

function thresholdRecovery(previous: number | null, current: number | null, lower: number, upper: number): 'BUY' | 'SELL' | null {
  if (previous == null || current == null) return null;
  if (previous <= lower && current > lower) return 'BUY';
  if (previous >= upper && current < upper) return 'SELL';
  return null;
}

function wrRecovery(previous: number | null, current: number | null): 'BUY' | 'SELL' | null {
  if (previous == null || current == null) return null;
  if (previous >= 80 && current < 80) return 'BUY';
  if (previous <= 20 && current > 20) return 'SELL';
  return null;
}

export function indicatorSignalAnchor(indicator: string): string | null {
  const anchors: Record<string, string> = {
    MACD: 'macd_dif', BBI: 'bbi', KDJ: 'k', RSI: 'rsi6', OBV: 'obv', 'W&R': 'wr10',
    MTM: 'mtm', DMI: 'pdi', DMA: 'dma', ASI: 'asi', TRIX: 'trix', DPO: 'dpo',
    CCI: 'cci', ROC: 'roc', MFI: 'mfi', EMV: 'emv',
  };
  return anchors[indicator] ?? null;
}

export function calculateIndicatorSignals(indicator: string, series: IndicatorSeries, closes: number[]): IndicatorSignal[] {
  const count = closes.length;
  const result: IndicatorSignal[] = [];
  for (let index = 1; index < count; index++) {
    const prev = (key: string) => value(series, key, index - 1);
    const curr = (key: string) => value(series, key, index);
    let kind: 'BUY' | 'SELL' | null = null;
    switch (indicator) {
      case 'W&R': kind = wrRecovery(prev('wr10'), curr('wr10')); break;
      case 'RSI': kind = thresholdRecovery(prev('rsi6'), curr('rsi6'), 30, 70); break;
      case 'MFI': kind = thresholdRecovery(prev('mfi'), curr('mfi'), 20, 80); break;
      case 'CCI': {
        const before = prev('cci'), now = curr('cci');
        if (before != null && now != null) {
          if (before <= -100 && now > -100) kind = 'BUY';
          else if (before >= 100 && now < 100) kind = 'SELL';
        }
        break;
      }
      case 'MACD': kind = crossed(prev('macd_dif'), curr('macd_dif'), prev('macd_dea'), curr('macd_dea')); break;
      case 'KDJ': kind = crossed(prev('k'), curr('k'), prev('d'), curr('d')); break;
      case 'OBV': kind = crossed(prev('obv'), curr('obv'), prev('obvma'), curr('obvma')); break;
      case 'DMI': kind = crossed(prev('pdi'), curr('pdi'), prev('mdi'), curr('mdi')); break;
      case 'DMA': kind = crossed(prev('dma'), curr('dma'), prev('ama'), curr('ama')); break;
      case 'ASI': kind = crossed(prev('asi'), curr('asi'), prev('asit'), curr('asit')); break;
      case 'TRIX': kind = crossed(prev('trix'), curr('trix'), prev('trma'), curr('trma')); break;
      case 'EMV': kind = crossed(prev('emv'), curr('emv'), prev('emv_ma'), curr('emv_ma')); break;
      case 'BBI': {
        const before = value(series, 'bbi', index - 1), now = value(series, 'bbi', index);
        if (before != null && now != null && Number.isFinite(closes[index - 1]!) && Number.isFinite(closes[index]!)) {
          if (closes[index - 1]! <= before && closes[index]! > now) kind = 'BUY';
          else if (closes[index - 1]! >= before && closes[index]! < now) kind = 'SELL';
        }
        break;
      }
      case 'MTM': kind = zeroCross(prev('mtm'), curr('mtm')); break;
      case 'DPO': kind = zeroCross(prev('dpo'), curr('dpo')); break;
      case 'ROC': kind = zeroCross(prev('roc'), curr('roc')); break;
      default: break;
    }
    if (kind) result.push({ index, kind });
  }
  return result;
}
