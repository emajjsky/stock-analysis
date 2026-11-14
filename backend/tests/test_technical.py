"""展示指标的独立数值、预热、缺量和不使用未来数据验证。"""
from math import sqrt

import pytest

from backend.technical import extended_indicators, intraday_indicators


def bars(count=80, flat=False):
    return [dict(open=str(20 if flat else 10+i), close=str(20 if flat else 10+i),
                 high=str(21 if flat else 11+i), low=str(19 if flat else 9+i), volume=100)
            for i in range(count)]


def test_boll_population_variance_warmup_and_price_indicators():
    result=extended_indicators(bars())
    assert result['boll_mid'][:19] == [None]*19
    assert float(result['boll_mid'][19]) == 19.5
    assert float(result['boll_upper'][19]) == pytest.approx(19.5+2*sqrt(33.25),abs=1e-6)
    assert float(result['boll_lower'][19]) == pytest.approx(19.5-2*sqrt(33.25),abs=1e-6)
    assert float(result['bbi'][-1]) == pytest.approx((88+86.5+83.5+77.5)/4,abs=1e-6)
    assert float(result['dma'][-1]) == 20
    assert float(result['ama'][-1]) == 20
    assert float(result['mtm'][-1]) == 12
    assert float(result['dpo'][-1]) == 20.5
    assert float(result['cci'][-1]) == pytest.approx(126.666667, abs=1e-5)
    assert float(result['roc'][-1]) == pytest.approx((89/77-1)*100, abs=1e-5)


def test_direction_volume_and_asi_on_monotonic_prices():
    result=extended_indicators(bars())
    assert float(result['obv'][-1]) == 7900
    assert result['vr'][-1] is None, '全上涨且无下跌量时分母为0，不能冒充有限比率'
    assert float(result['pdi'][-1]) == 50
    assert float(result['mdi'][-1]) == 0
    assert float(result['adx'][-1]) == 100
    assert float(result['adxr'][-1]) == 100
    assert float(result['asi'][-1]) == pytest.approx(26*100/3,abs=1e-6)
    assert all(float(result['sar'][i]) <= 8+i for i in range(2,80))


def test_flat_prices_and_unknown_volume_do_not_create_infinity_or_fake_volume():
    result=extended_indicators(bars(flat=True))
    assert float(result['vr'][-1]) == 100
    assert float(result['ar'][-1]) == 100
    assert float(result['br'][-1]) == 100
    assert float(result['obv'][-1]) == 0
    damaged=bars()
    damaged[30]['volume']=None
    result=extended_indicators(damaged)
    assert result['obv'][30:] == [None]*50
    assert result['vr'][30:56] == [None]*26


def test_new_volume_oscillators_use_only_complete_ohlcv_windows():
    source=bars()
    result=extended_indicators(source)
    assert result['mfi'][:14] == [None]*14
    assert float(result['mfi'][14]) == 100
    assert result['emv'][:14] == [None]*14
    assert float(result['emv'][14]) == pytest.approx(200)
    assert float(result['emv_ma'][22]) == pytest.approx(200)
    assert float(result['pvt'][0]) == 0
    assert float(result['pvt'][-1]) > 0
    assert set(result['adl']) == {'0.000000'}
    damaged=bars()
    damaged[20]['volume']=None
    result=extended_indicators(damaged)
    assert result['mfi'][20:34] == [None]*14
    assert result['emv'][20:34] == [None]*14
    assert result['pvt'][20:] == [None]*60
    assert result['adl'][20:] == [None]*60


def test_all_indicators_have_no_lookahead_and_support_empty_input():
    source=bars()
    full=extended_indicators(source)
    assert all(len(v)==80 for v in full.values())
    for length in (0,1,2,25,60):
        prefix=extended_indicators(source[:length])
        assert all(prefix[key] == full[key][:length] for key in full)


def test_intraday_macd_and_rsi_use_only_real_price_series():
    points=[dict(value='100') for _ in range(60)]
    values=intraday_indicators(points)
    assert values['macd'][0] == '0.000000'
    assert values['macd_dif'][0] == values['macd_dea'][0] == '0.000000'
    assert all(value is not None for value in values['macd'][:25])
    assert float(values['macd'][-1]) == 0
    assert float(values['rsi6'][-1]) == 50
    assert all('kdj' not in key and key not in ('k','d','j') for key in values)
