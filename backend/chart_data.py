"""图表专用日线叠加与聚合；不改写完成历史，不作为策略输入。"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from backend.providers import CHINA_TZ, _decimal


def chart_bars(history, quote, timeframe, *, at=None):
    rows = [dict(row) for row in history]
    current = (at or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
    dynamic = None
    if quote:
        try:
            source = datetime.fromisoformat(str(quote.get('source_time', '')).replace('Z', '+00:00'))
            if source.tzinfo is None:
                raise ValueError('timezone required')
            source = source.astimezone(CHINA_TZ)
            values = [_decimal(str(quote.get(key, ''))) for key in ('open', 'high', 'low', 'price')]
            if None in values:
                raise ValueError('missing OHLC')
            opening, high, low, close = map(Decimal, values)
            volume = quote.get('volume')
            if volume is not None and (isinstance(volume, bool) or not isinstance(volume, int) or volume <= 0):
                raise ValueError('no valid trading volume')
            day = source.date().isoformat()
            age = (current - source).total_seconds()
            if (source.date() == current.date() and source.weekday() < 5
                    and source.hour * 60 + source.minute >= 570 and age >= -60
                    and min(opening, high, low, close) > 0
                    and low <= min(opening, close) <= max(opening, close) <= high
                    and (not rows or rows[-1]['time'] < day)):
                rows.append(dict(time=day, open=values[0], high=values[1], low=values[2], close=values[3],
                                 volume=volume, amount=_decimal(str(quote.get('amount', '')))))
                dynamic = dict(time=day, trade_date=day, source_time=quote['source_time'],
                               fetched_at=quote.get('fetched_at'), stale=age > 120)
        except (KeyError, TypeError, ValueError):
            pass  # 无有效当日源时间/OHLC时，只显示已保存历史。
    if timeframe != '1d':
        grouped = {}
        for row in rows:
            day = date.fromisoformat(row['time'])
            key = day - timedelta(days=day.weekday()) if timeframe == '1w' else day.replace(day=1)
            if key not in grouped:
                grouped[key] = dict(row)
            else:
                item = grouped[key]
                item.update(high=format(max(Decimal(item['high']), Decimal(row['high'])), 'f'),
                            low=format(min(Decimal(item['low']), Decimal(row['low'])), 'f'), close=row['close'],
                            volume=item['volume'] + row['volume'] if item['volume'] is not None and row['volume'] is not None else None,
                            amount=format(Decimal(item['amount']) + Decimal(row['amount']), 'f')
                            if item['amount'] is not None and row['amount'] is not None else None)
        rows = list(grouped.values())
        if dynamic:
            dynamic['time'] = rows[-1]['time']
    public = [{key: row.get(key) for key in ('time', 'open', 'high', 'low', 'close', 'volume', 'amount')} for row in rows]
    return public, dynamic
