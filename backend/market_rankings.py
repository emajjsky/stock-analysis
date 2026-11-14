"""新浪公开榜单适配：固定端点、有界分页，不推断来源日期。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.providers import ProviderError, normalize_security_id

RANKING_URL = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
SOURCE = '新浪财经公开榜单'
RANKINGS = {'gainers': ('changepercent', 0), 'losers': ('changepercent', 1), 'amount': ('amount', 0)}
_SYMBOL = re.compile(r'^(sh|sz|bj)(\d{6})$')
_TICK = re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$')
_MISSING = (None, '', '-', '--')


def _number(value: Any, *, signed: bool = False) -> Decimal | None:
    if value in _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid number')
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid number') from exc
    if not number.is_finite() or abs(number) > Decimal('1e18') or number.as_tuple().exponent < -8:
        raise ValueError('invalid number')
    if not signed and number < 0:
        raise ValueError('negative amount or price')
    return number


def _text(number: Decimal | None) -> str | None:
    return format(number, 'f') if number is not None else None


class SinaRankingProvider:
    """每榜最多五页；任一榜不完整时不返回部分榜单供覆盖缓存。"""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10):
        if not 0 < timeout <= 30:
            raise ProviderError('INVALID_REQUEST', '榜单请求超时须在 0 到 30 秒之间')
        self._owns_client = client is None
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})

    def close(self):
        if self._owns_client:
            self.client.close()

    def _page(self, name: str, page: int) -> list[dict]:
        sort, asc = RANKINGS[name]
        try:
            response = self.client.get(RANKING_URL, params=dict(page=page, num=100,
                sort=sort, asc=asc, node='hs_a'), timeout=self.timeout, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError('oversized response')
            payload = response.json()
            if not isinstance(payload, list) or not payload or len(payload) > 100:
                raise ValueError('invalid page')
            return payload
        except httpx.HTTPError as exc:
            raise ProviderError('RANKING_UNAVAILABLE', '行情榜单暂不可用，保留已有缓存') from exc
        except (ValueError, TypeError) as exc:
            raise ProviderError('RANKING_INVALID', '行情榜单数据无效，保留已有缓存') from exc

    def _security(self, row: dict, fetched_at: str) -> tuple[dict | None, dict]:
        if not isinstance(row, dict):
            raise ValueError('invalid security')
        symbol, code, name = row.get('symbol'), row.get('code'), row.get('name')
        match = _SYMBOL.fullmatch(symbol) if isinstance(symbol, str) else None
        if not match or not isinstance(code, str) or match.group(2) != code:
            raise ValueError('security identity mismatch')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('invalid security name')
        values = dict(price=_number(row.get('trade')), change_pct=_number(row.get('changepercent'), signed=True),
                      volume=_number(row.get('volume')), amount=_number(row.get('amount')))
        if values['volume'] is not None and values['volume'] != values['volume'].to_integral_value():
            raise ValueError('fractional share volume')
        tick = row.get('ticktime')
        if tick not in _MISSING and (not isinstance(tick, str) or not _TICK.fullmatch(tick)):
            raise ValueError('invalid source tick time')
        if match.group(1) == 'bj':
            return None, values
        try:
            canonical, _ = normalize_security_id(match.group(1).upper() + '.' + code)
        except ProviderError:
            # 排除 B 股/CDR 等现有普通 A 股目录范围外证券。
            return None, values
        # 上游停牌/未成交可能 trade=0；报价保持未知，不显示零价格。
        price = values['price'] if values['price'] else None
        quote = dict(price=_text(price), change_pct=_text(values['change_pct']),
            volume=int(values['volume']) if values['volume'] is not None else None,
            amount=_text(values['amount']), volume_unit='SHARES' if values['volume'] is not None else 'UNKNOWN',
            amount_unit='CNY' if values['amount'] is not None else 'UNKNOWN', source=SOURCE, mode='LIVE',
            as_of=None, source_time=None, source_time_raw=tick or None, fetched_at=fetched_at,
            is_realtime=False)
        # 单位实测：2026-10-29 sz301079 新浪 volume=15125599 股、amount=472972366 元，
        # 腾讯 compound=34.00/151256/472972366（volume 为四舍五入手数，金额一致）。
        return dict(id='LIVE.' + canonical, code=code, name=name.strip(),
            exchange='SSE' if canonical.startswith('SH.') else 'SZSE', sector='未接入行业资料',
            status='LIVE_UNVERIFIED', dataset_id='tencent-unadjusted-v1', quote=quote), values

    def ranking(self, name: str) -> list[dict]:
        """独立读取一个榜；调用方可按榜缓存并在失败时保留旧榜。"""
        if name not in RANKINGS:
            raise ProviderError('INVALID_REQUEST', '不支持的行情榜单')
        fetched_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        result, seen, previous = [], set(), None
        sort, asc = RANKINGS[name]
        metric = 'amount' if sort == 'amount' else 'change_pct'
        try:
            for page in range(1, 6):
                batch = self._page(name, page)
                for row in batch:
                    security, values = self._security(row, fetched_at)
                    current = values[metric]
                    if current is None:
                        raise ValueError('missing ranking metric')
                    if previous is not None and (current < previous if asc else current > previous):
                        raise ValueError('ranking order changed')
                    previous = current
                    if security is None:
                        continue
                    if security['id'] in seen:
                        continue
                    seen.add(security['id'])
                    security['rank'] = len(result) + 1
                    result.append(security)
                    if len(result) == 100:
                        return result
                if len(batch) < 100:
                    break
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError('RANKING_INVALID', '行情榜单数据无效，保留已有缓存') from exc
        raise ProviderError('RANKING_INCOMPLETE', '行情榜单记录不足，保留已有缓存')

    def rankings(self) -> dict[str, list[dict]]:
        return {name: self.ranking(name) for name in RANKINGS}
