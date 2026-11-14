"""展示用常规OHLCV指标；不修改策略输入、成交或信号。预热和无效分母留空。"""
from __future__ import annotations

import math


def average(values, size):
    return [sum(values[i-size+1:i+1]) / size
            if i >= size-1 and all(x is not None for x in values[i-size+1:i+1]) else None
            for i in range(len(values))]


def ema(values, size):
    result, previous = [], None
    for value in values:
        if value is None:
            result.append(None)
            continue
        previous = value if previous is None else previous + 2 / (size+1) * (value-previous)
        result.append(previous)
    return result


def intraday_indicators(points):
    """只用真实分时成交价计算MACD/RSI，不推造分钟高低开收；EMA从首个真实点起算。"""
    values=[float(p['value']) for p in points]
    fast,slow=ema(values,12),ema(values,26)
    dif=[a-b for a,b in zip(fast,slow)]
    dea=ema(dif,9)
    result={'macd_dif':dif,
            'macd_dea':dea,
            'macd':[2*(a-b) for a,b in zip(dif,dea)]}
    for size in (6,14):
        gains,losses,series=[],[],[]
        gain=loss=None
        for i,value in enumerate(values):
            if i:
                change=value-values[i-1]
                gains.append(max(change,0)); losses.append(max(-change,0))
            if i>=size:
                gain=sum(gains[:size])/size if i==size else (gain*(size-1)+gains[-1])/size
                loss=sum(losses[:size])/size if i==size else (loss*(size-1)+losses[-1])/size
                series.append(50 if gain==loss==0 else 100 if loss==0 else 100-100/(1+gain/loss))
            else:
                series.append(None)
        result[f'rsi{size}']=series
    return {key:[f'{x:.6f}' if x is not None else None for x in values] for key,values in result.items()}


def extended_indicators(bars):
    close = [float(b['close']) for b in bars]
    high = [float(b['high']) for b in bars]
    low = [float(b['low']) for b in bars]
    opening = [float(b['open']) for b in bars]
    volumes = [float(b['volume']) if b.get('volume') is not None else None for b in bars]
    n = len(bars)
    result = {}

    middle = average(close, 20)
    deviations = [math.sqrt(sum((x-middle[i])**2 for x in close[i-19:i+1]) / 20)
                  if middle[i] is not None else None for i in range(n)]
    result.update(boll_mid=middle,
        boll_upper=[m+2*d if m is not None else None for m,d in zip(middle,deviations)],
        boll_lower=[m-2*d if m is not None else None for m,d in zip(middle,deviations)],
        expma12=ema(close,12), expma50=ema(close,50))
    ene_mid = average(close, 25)
    result.update(ene_mid=ene_mid,
        ene_upper=[m * 1.10 if m is not None else None for m in ene_mid],
        ene_lower=[m * 0.90 if m is not None else None for m in ene_mid])
    mas = {k: average(close,k) for k in (3,6,10,12,24,50)}
    result['bbi'] = [sum(mas[k][i] for k in (3,6,12,24))/4 if i>=23 else None for i in range(n)]
    for size in (6,12,24):
        result[f'bias{size}'] = [(c/m-1)*100 if m else None for c,m in zip(close,mas[size])]
    result['dma'] = [a-b if b is not None else None for a,b in zip(mas[10],mas[50])]
    result['ama'] = average(result['dma'],10)
    result['mtm'] = [close[i]-close[i-12] if i>=12 else None for i in range(n)]
    result['mtmma'] = average(result['mtm'],6)
    for size in (6,10):
        values = []
        for i in range(n):
            top, bottom = max(high[max(0,i-size+1):i+1]), min(low[max(0,i-size+1):i+1])
            values.append((top-close[i])/(top-bottom)*100 if i>=size-1 and top>bottom else None)
        result[f'wr{size}'] = values

    # CCI(20)：典型价格偏离其均值的程度，保留标准的 ±100 参考区间。
    typical = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    cci = []
    for i, value in enumerate(typical):
        window = typical[i-19:i+1]
        if i < 19:
            cci.append(None)
            continue
        mean = sum(window) / 20
        deviation = sum(abs(item - mean) for item in window) / 20
        cci.append((value - mean) / (0.015 * deviation) if deviation else 0)
    result['cci'] = cci
    result['roc'] = [(close[i] / close[i-12] - 1) * 100 if i >= 12 and close[i-12] else None
                     for i in range(n)]

    typical = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    money_flow = [typical[i] * volumes[i] if volumes[i] is not None else None for i in range(n)]
    mfi = [None] * n
    for i in range(14, n):
        window = range(i-13, i+1)
        if any(money_flow[j] is None for j in window):
            continue
        positive = sum(money_flow[j] for j in window if typical[j] > typical[j-1])
        negative = sum(money_flow[j] for j in window if typical[j] < typical[j-1])
        mfi[i] = 50 if positive == negative == 0 else 100 if negative == 0 else 100 - 100 / (1 + positive / negative)
    result['mfi'] = mfi

    emv_raw = [None] if n else []
    for i in range(1, n):
        volume = volumes[i]
        spread = high[i] - low[i]
        if volume is None or volume <= 0 or spread <= 0:
            emv_raw.append(None)
            continue
        midpoint_move = (high[i] + low[i] - high[i-1] - low[i-1]) / 2
        emv_raw.append(midpoint_move * spread / (volume / 10000))
    result['emv'] = average(emv_raw, 14)
    result['emv_ma'] = average(result['emv'], 9)

    pvt, adl = [], []
    pvt_value = adl_value = 0
    pvt_valid = adl_valid = True
    for i in range(n):
        volume = volumes[i]
        if volume is None:
            pvt_valid = adl_valid = False
        if pvt_valid:
            if i:
                pvt_value += volume * (close[i] / close[i-1] - 1) if close[i-1] else 0
            pvt.append(pvt_value)
        else:
            pvt.append(None)
        if adl_valid:
            spread = high[i] - low[i]
            multiplier = ((2*close[i]-high[i]-low[i]) / spread) if spread else 0
            adl_value += multiplier * volume
            adl.append(adl_value)
        else:
            adl.append(None)
    result.update(pvt=pvt, adl=adl)

    obv, current = [], 0
    for i, amount in enumerate(volumes):
        if amount is None:
            current = None
        elif i and current is not None:
            current += amount if close[i]>close[i-1] else -amount if close[i]<close[i-1] else 0
        obv.append(current)
    result['obv'], result['obvma'] = obv, average(obv,30)
    up, down, flat, ar_top, ar_bottom, br_top, br_bottom = ([] for _ in range(7))
    for i in range(n):
        ar_top.append(high[i]-opening[i]); ar_bottom.append(opening[i]-low[i])
        br_top.append(max(high[i]-close[i-1],0) if i else None)
        br_bottom.append(max(close[i-1]-low[i],0) if i else None)
        v = volumes[i]
        up.append(v if i and close[i]>close[i-1] else 0 if v is not None and i else None)
        down.append(v if i and close[i]<close[i-1] else 0 if v is not None and i else None)
        flat.append(v if i and close[i]==close[i-1] else 0 if v is not None and i else None)
    def ratio(a,b,size):
        aa,bb=average(a,size),average(b,size)
        return [x/y*100 if x is not None and y else None for x,y in zip(aa,bb)]
    result['ar'],result['br']=ratio(ar_top,ar_bottom,26),ratio(br_top,br_bottom,26)
    result['vr']=ratio([u+f/2 if u is not None and f is not None else None for u,f in zip(up,flat)],
                       [d+f/2 if d is not None and f is not None else None for d,f in zip(down,flat)],26)
    triple = ema(ema(ema(close,12),12),12)
    result['trix']=[(triple[i]/triple[i-1]-1)*100 if i>=34 and triple[i-1] else None for i in range(n)]
    result['trma']=average(result['trix'],9)
    result['dpo']=[close[i]-middle[i-11] if i>=30 else None for i in range(n)]
    result['dpoma']=average(result['dpo'],6)

    # DMI(14,6)：TR、方向运动使用Wilder平滑，ADX为DX的6期均值。
    trs, plus, minus, pdi, mdi, dx = ([] for _ in range(6))
    tr_sum=plus_sum=minus_sum=None
    for i in range(n):
        if not i:
            trs.append(0); plus.append(0); minus.append(0)
        else:
            a,b=high[i]-high[i-1], low[i-1]-low[i]
            trs.append(max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1])))
            plus.append(a if a>0 and a>b else 0); minus.append(b if b>0 and b>a else 0)
        if i>=14:
            tr_sum=sum(trs[1:15]) if i==14 else tr_sum-tr_sum/14+trs[i]
            plus_sum=sum(plus[1:15]) if i==14 else plus_sum-plus_sum/14+plus[i]
            minus_sum=sum(minus[1:15]) if i==14 else minus_sum-minus_sum/14+minus[i]
        p=plus_sum/tr_sum*100 if tr_sum else None
        m=minus_sum/tr_sum*100 if tr_sum else None
        pdi.append(p); mdi.append(m)
        dx.append(abs(p-m)/(p+m)*100 if p is not None and m is not None and p+m else None)
    result.update(pdi=pdi,mdi=mdi,adx=average(dx,6))
    result['adxr']=[(result['adx'][i]+result['adx'][i-6])/2
        if i>=6 and result['adx'][i] is not None and result['adx'][i-6] is not None else None for i in range(n)]

    sar=[None]*n
    if n>=2:
        rising=close[1]>=close[0]
        value=min(low[:2]) if rising else max(high[:2])
        extreme=max(high[:2]) if rising else min(low[:2])
        acceleration=0.02
        sar[1]=value
        for i in range(2,n):
            value=value+acceleration*(extreme-value)
            value=min(value,low[i-1],low[i-2]) if rising else max(value,high[i-1],high[i-2])
            if rising and low[i]<value or not rising and high[i]>value:
                value=extreme; rising=not rising; acceleration=0.02
                extreme=high[i] if rising else low[i]
            elif rising and high[i]>extreme or not rising and low[i]<extreme:
                extreme=high[i] if rising else low[i]; acceleration=min(0.2,acceleration+0.02)
            sar[i]=value
    result['sar']=sar
    si=[None]*n
    for i in range(1,n):
        a,b,c,d=abs(high[i]-close[i-1]),abs(low[i]-close[i-1]),abs(high[i]-low[i-1]),abs(close[i-1]-opening[i-1])
        r=a+b/2+d/4 if a>b and a>c else b+a/2+d/4 if b>c and b>a else c+d/4
        x=close[i]-close[i-1]+(close[i]-opening[i])/2+close[i-1]-opening[i-1]
        si[i]=50*x/r*max(a,b) if r else 0
    result['asi']=[x*26 if x is not None else None for x in average(si,26)]
    result['asit']=average(result['asi'],10)
    return {key:[f'{x:.6f}' if x is not None and math.isfinite(x) else None for x in values]
            for key,values in result.items()}
