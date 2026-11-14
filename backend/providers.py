"""腾讯财经只读行情适配。HTTP endpoints are fixed; no fallback or mock data."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

QUOTE_URL = "https://qt.gtimg.cn/q="
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SOURCE = "Tencent Finance public quote endpoint"
CHINA_TZ = timezone(timedelta(hours=8))
INDEX_CODES = {'SH.000001', 'SH.000016', 'SH.000300', 'SH.000905', 'SH.000852',
               'SZ.399001', 'SZ.399006', 'SH.000688'}
# Field mapping checked against Tencent's fixed endpoints on 2026-10-27.
# AKShare 1.20.0 upstream reference: akshare/stock/quote/stock_hist_tx.py.
# That adapter targets another proxy endpoint; its sz000 exception is not used
# here: this endpoint's sz000001 daily volume matches quote volume in lots.
_CODE_RE = re.compile(r"^(SH|SZ)\.(\d{6})$", re.I)
_TX_RE = re.compile(r"^v_(sh|sz)(\d{6})=\"(.*)\";?$", re.I)


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_security_id(value: str, *, allow_index: bool = False) -> tuple[str, str]:
    """Return (canonical SH./SZ. id, Tencent code), restricted to SSE/SZSE A shares."""
    match = _CODE_RE.fullmatch(str(value).strip())
    if allow_index and match and str(value).upper() in INDEX_CODES:
        sid = str(value).upper()
        return sid, sid.replace('.', '').lower()
    if match:
        exchange, code = match.group(1).upper(), match.group(2)
    else:
        code = str(value).strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ProviderError("INVALID_SECURITY", "仅支持SH./SZ.格式或六位代码的沪深A股")
        if code.startswith(("600", "601", "603", "605", "688")):
            exchange = "SH"
        elif code.startswith(("000", "001", "002", "003", "300", "301", "302")):
            exchange = "SZ"
        else:
            raise ProviderError("INVALID_SECURITY", "代码无法安全映射到沪深A股市场")
    if exchange == "SH" and not code.startswith(("600", "601", "603", "605", "688")):
        raise ProviderError("INVALID_SECURITY", "证券代码与上海市场前缀不匹配")
    if exchange == "SZ" and not code.startswith(("000", "001", "002", "003", "300", "301", "302")):
        raise ProviderError("INVALID_SECURITY", "证券代码与深圳市场前缀不匹配")
    return f"{exchange}.{code}", f"{exchange.lower()}{code}"


def _decimal(value: str, *, signed: bool = False) -> str | None:
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) > Decimal("1000000000000000000") or number.as_tuple().exponent < -8 or (number < 0 and not signed):
        return None
    return format(number, "f")


def _fetched_at(value: datetime | None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(raw: str) -> str | None:
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            value = datetime.strptime(raw, fmt).replace(tzinfo=CHINA_TZ)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    return None


def parse_tencent_quotes(raw: bytes, security_ids: list[str], fetched_at: datetime | None = None, *, allow_index: bool = False) -> list[dict[str, Any]]:
    try:
        text = raw.decode("gbk")
    except UnicodeDecodeError as exc:
        raise ProviderError("INVALID_ENCODING", "腾讯快照响应不是有效GBK文本") from exc
    expected = {normalize_security_id(item, allow_index=allow_index)[1]: normalize_security_id(item, allow_index=allow_index)[0] for item in security_ids}
    stamp = _fetched_at(fetched_at)
    digest = hashlib.sha256(raw).hexdigest()
    parsed: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _TX_RE.match(line.strip())
        if not match:
            continue
        tx_code = (match.group(1) + match.group(2)).lower()
        if tx_code in expected:
            parsed[tx_code] = match.group(3).split("~")
    result = []
    for tx_code, sid in expected.items():
        fields = parsed.get(tx_code)
        if not fields or len(fields) < 39:
            raise ProviderError("QUOTE_MISSING", f"腾讯未返回有效快照: {sid}")
        if fields[2] != tx_code[2:] or not fields[1] or _timestamp(fields[30]) is None:
            raise ProviderError("INVALID_RESPONSE", f"腾讯快照身份或时间字段无效: {sid}")
        for index in (3, 4, 5, 33, 34, 36, 37):
            if _decimal(fields[index]) is None:
                raise ProviderError("INVALID_RESPONSE", f"腾讯快照数值字段无效: {sid}")
        volume_raw = _decimal(fields[36])
        amount_raw = _decimal(fields[37])
        is_star = sid.startswith("SH.688")
        volume = (Decimal(volume_raw) * (1 if is_star else 100)) if volume_raw is not None else None
        amount = (Decimal(amount_raw) * 10000) if amount_raw is not None else None
        def optional(index: int, *, signed: bool = False, scale: int = 1):
            value = _decimal(fields[index], signed=signed) if index < len(fields) else None
            return format(Decimal(value) * scale, 'f') if value is not None else None

        def levels(start: int):
            result = []
            for level in range(5):
                price, size = optional(start + 2 * level), optional(start + 2 * level + 1)
                price = price if price is not None and Decimal(price) > 0 else None
                volume = int(Decimal(size)) if size is not None and Decimal(size) > 0 and Decimal(size) == Decimal(size).to_integral_value() else None
                result.append(dict(level=level + 1, price=price, volume=volume))
            return result

        is_index = sid in INDEX_CODES
        result.append({
            "security_id": sid, "code": tx_code[2:], "name": fields[1] or None,
            "price": _decimal(fields[3]), "previous_close": _decimal(fields[4]),
            "open": _decimal(fields[5]), "volume": int(volume) if volume is not None and volume == volume.to_integral_value() else None,
            "volume_raw": fields[36] or None, "volume_unit": "SHARES" if volume is not None else "UNKNOWN",
            "amount": format(amount, "f") if amount is not None else None, "amount_raw": fields[37] or None,
            "amount_unit": "CNY" if amount is not None else "UNKNOWN", "change": _decimal(fields[31], signed=True), "change_pct": _decimal(fields[32], signed=True),
            "high": _decimal(fields[33]), "low": _decimal(fields[34]),
            "turnover_rate": optional(38) if not is_index else None,
            "pe_ttm": optional(39, signed=True) if not is_index else None,
            "pe_dynamic": optional(52, signed=True) if not is_index else None,
            "pe_static": optional(53, signed=True) if not is_index else None,
            "float_shares": optional(72) if not is_index else None,
            "total_shares": optional(73) if not is_index else None,
            "buy_volume": optional(7, scale=1 if is_star else 100) if not is_index else None,
            "sell_volume": optional(8, scale=1 if is_star else 100) if not is_index else None,
            "quote_schema_version": 2,
            "amplitude": optional(43),
            "float_market_cap": optional(44, scale=100000000) if not is_index else None,
            "total_market_cap": optional(45, scale=100000000) if not is_index else None,
            "pb": optional(46, signed=True) if not is_index else None,
            "limit_up": optional(47) if not is_index else None,
            "limit_down": optional(48) if not is_index else None,
            "volume_ratio": optional(49) if not is_index else None,
            "order_book": dict(bids=levels(9), asks=levels(19), volume_unit='LOT') if not is_index else None,
            "source": SOURCE, "source_time": _timestamp(fields[30]) if fields[30] else None,
            "source_time_raw": fields[30] or None,
            "fetched_at": stamp, "raw_hash": digest,
        })
    return result


def _adjustment_fields(data: dict, adjustment: str) -> list:
    if not isinstance(data, dict):
        raise ProviderError("INVALID_RESPONSE", "腾讯日线数据结构无效")
    choices = {"none": ("day",), "qfq": ("qfqday",), "hfq": ("hfqday",)}
    if adjustment not in choices:
        raise ProviderError("INVALID_ADJUSTMENT", "adjustment仅支持none、qfq或hfq")
    for key in choices[adjustment]:
        if isinstance(data.get(key), list):
            return data[key]
    raise ProviderError("KLINE_MISSING", "腾讯未返回请求复权类型的日线")


def parse_tencent_daily(raw: bytes, security_id: str, fetched_at: datetime | None = None, today: date | None = None,
                        adjustment: str = "none", *, allow_index: bool = False,
                        diagnostics: list[dict[str, Any]] | None = None, tolerate_source_errors: bool = False) -> list[dict[str, Any]]:
    sid, tx_code = normalize_security_id(security_id, allow_index=allow_index)
    if adjustment not in {"none", "qfq", "hfq"}:
        raise ProviderError("INVALID_ADJUSTMENT", "adjustment仅支持none、qfq或hfq")
    try:
        text = raw.decode("utf-8-sig")
        # Tencent may wrap JSONP in a variable assignment.
        text = text[text.find("=") + 1:] if not text.lstrip().startswith("{") else text
        payload = json.loads(text.strip().rstrip(";"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProviderError("INVALID_RESPONSE", "腾讯日线响应不是有效JSON/JSONP") from exc
    if not isinstance(payload, dict) or payload.get("code", 0) != 0:
        raise ProviderError("UPSTREAM_ERROR", "腾讯日线返回失败状态")
    try:
        rows = _adjustment_fields(payload["data"][tx_code], adjustment)
    except (KeyError, TypeError) as exc:
        raise ProviderError("KLINE_MISSING", f"腾讯未返回日线: {sid}") from exc
    stamp = _fetched_at(fetched_at)
    digest = hashlib.sha256(raw).hexdigest()
    fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(CHINA_TZ)
    cutoff = today or fetched.date()
    result = []
    # Main-board/ChiNext Tencent volume is lots, STAR is already shares.
    # Confirmed against quote[35]: price / raw-volume / CNY-amount compound field.
    multiplier = 1 if sid.startswith("SH.688") else 100
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise ProviderError("INVALID_RESPONSE", "腾讯日线字段数不足")
        try:
            day = date.fromisoformat(str(row[0]))
        except ValueError as exc:
            raise ProviderError("INVALID_RESPONSE", "腾讯日线日期无效") from exc
        if day >= cutoff:
            continue
        # Tencent order: date, open, close, high, low, volume, ... turnover, amount.
        # 长期分红后前复权价格可为负；它是展示价格，不是可交易原价。
        opening, close, high, low = (_decimal(str(row[i]), signed=adjustment == 'qfq') for i in (1, 2, 3, 4))
        raw_volume = _decimal(str(row[5]))
        if None in (opening, close, high, low, raw_volume):
            raise ProviderError("INVALID_RESPONSE", "腾讯日线数值无效")
        o, c, h, l = map(Decimal, (opening, close, high, low))
        if (adjustment != 'qfq' and min(o, c, h, l) <= 0) or l > min(o, c) or h < max(o, c) or l > h:
            if not allow_index and not tolerate_source_errors:
                raise ProviderError("INVALID_RESPONSE", "腾讯日线OHLC不一致")
            if h < max(o, c) and max(o, c) - h <= Decimal('0.01'):
                h = max(o, c)
                high = format(h, 'f')
                if diagnostics is not None:
                    diagnostics.append({'date': day.isoformat(), 'action': 'ROUNDING_CLAMP_HIGH'})
            if l > min(o, c) and l - min(o, c) <= Decimal('0.01'):
                l = min(o, c)
                low = format(l, 'f')
                if diagnostics is not None:
                    diagnostics.append({'date': day.isoformat(), 'action': 'ROUNDING_CLAMP_LOW'})
            if min(o, c, h, l) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
                if diagnostics is not None:
                    diagnostics.append({'date': day.isoformat(), 'action': 'INVALID_SOURCE_ROW_SKIPPED'})
                continue
        volume = Decimal(raw_volume) * multiplier
        if volume != volume.to_integral_value():
            raise ProviderError("INVALID_RESPONSE", "腾讯日线成交量不能规范为整数股")
        amount = None
        # The configured fqkline endpoint returns six columns in its daily series;
        # amount is not returned there and remains unknown rather than inferred.
        source_time = day.isoformat()
        result.append({"security_id": sid, "time": day.isoformat(), "open": opening, "high": high,
                       "low": low, "close": close, "volume": int(volume), "volume_unit": "SHARES",
                       "amount": amount, "amount_unit": "CNY" if amount is not None else "UNKNOWN",
                       "source": SOURCE, "source_time": source_time, "source_time_raw": day.isoformat(),
                       "fetched_at": stamp, "raw_hash": digest, "adjustment": adjustment.upper(), "complete": True})
    dedup = {}
    for item in result:
        if item["time"] in dedup and dedup[item["time"]] != item:
            raise ProviderError("DATA_CONFLICT", "腾讯日线同日数值冲突")
        dedup[item["time"]] = item
    if diagnostics is not None:
        diagnostics.append({'action': 'SOURCE_PAGE_COUNT', 'count': len(rows)})
    return [dedup[key] for key in sorted(dedup)]


def parse_eastmoney_daily(raw: bytes, security_id: str, fetched_at: datetime | None = None,
                          today: date | None = None, adjustment: str = "none") -> list[dict[str, Any]]:
    """Parse Eastmoney daily bars, whose seventh field is the actual turnover amount."""
    sid, _ = normalize_security_id(security_id)
    if adjustment not in {"none", "qfq", "hfq"}:
        raise ProviderError("INVALID_ADJUSTMENT", "adjustment仅支持none、qfq或hfq")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        data = payload["data"]
        rows = data["klines"]
        if not isinstance(rows, list) or str(data["code"]) != sid.split(".", 1)[1]:
            raise ValueError("identity mismatch")
        if 'market' in data and data['market'] != (1 if sid.startswith('SH.') else 0):
            raise ValueError('market mismatch')
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("INVALID_RESPONSE", "东方财富日线响应无效") from exc
    stamp = _fetched_at(fetched_at)
    cutoff = today or datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(CHINA_TZ).date()
    multiplier = 1 if sid.startswith("SH.688") else 100
    digest = hashlib.sha256(raw).hexdigest()
    result = []
    for row in rows:
        fields = str(row).split(",")
        if len(fields) < 7:
            raise ProviderError("INVALID_RESPONSE", "东方财富日线字段数不足")
        try:
            day = date.fromisoformat(fields[0])
            opening, close, high, low = (_decimal(fields[i], signed=adjustment == 'qfq') for i in (1, 2, 3, 4))
            raw_volume = _decimal(fields[5])
            amount = _decimal(fields[6])
        except (ValueError, TypeError):
            raise ProviderError("INVALID_RESPONSE", "东方财富日线数值无效")
        if day >= cutoff:
            continue
        if None in (opening, close, high, low, raw_volume, amount):
            raise ProviderError('INVALID_RESPONSE', '东方财富日线存在无效数值')
        o, c, h, l, turnover = map(Decimal, (opening, close, high, low, amount))
        if (adjustment != 'qfq' and min(o, c, h, l) <= 0) or l > min(o, c) or h < max(o, c) or l > h or turnover < 0:
            raise ProviderError("INVALID_RESPONSE", "东方财富日线OHLC或成交额无效")
        volume = Decimal(raw_volume) * multiplier
        if volume != volume.to_integral_value():
            raise ProviderError("INVALID_RESPONSE", "东方财富日线成交量不能规范为整数股")
        result.append({"security_id": sid, "time": day.isoformat(), "open": opening, "high": high,
                       "low": low, "close": close, "volume": int(volume), "volume_unit": "SHARES",
                       "amount": amount, "amount_unit": "CNY", "source": "东方财富公开日线",
                       "source_time": day.isoformat(), "source_time_raw": day.isoformat(),
                       "fetched_at": stamp, "raw_hash": digest, "adjustment": adjustment.upper(), "complete": True})
    return result


def download_tencent_history(get, security_id: str, *, allow_index: bool = False,
                             adjustment: str = 'none',
                             diagnostics: list[dict[str, Any]] | None = None, tolerate_source_errors: bool = False) -> list[dict[str, Any]]:
    """Backward pages of one explicit adjustment series."""
    sid, symbol = normalize_security_id(security_id, allow_index=allow_index)
    if adjustment not in {'none', 'qfq', 'hfq'}:
        raise ProviderError('INVALID_ADJUSTMENT', 'adjustment仅支持none、qfq或hfq')
    fetched = datetime.now(CHINA_TZ)
    cutoff = fetched.date() + timedelta(days=1) if fetched.hour >= 16 else fetched.date()
    merged = {}
    end = ''
    previous_start = None
    # 复权接口实际按约640条截页；不能按请求2000条提前判定已到上市日。
    page_size = 640 if adjustment != 'none' else 2000
    # 8×640 仅约21年，无法覆盖黑牡丹等老股票；32页仍保留有界保护。
    for _ in range(32):
        source_adjustment = '' if adjustment == 'none' else adjustment
        raw = get(KLINE_URL, {'param': f'{symbol},day,,{end},{page_size},{source_adjustment}'})
        page_diagnostics = []
        rows = parse_tencent_daily(raw, sid, allow_index=allow_index, today=cutoff, tolerate_source_errors=tolerate_source_errors,
                                   adjustment=adjustment, diagnostics=page_diagnostics)
        source_count = page_diagnostics[-1]['count'] if page_diagnostics else len(rows)
        if diagnostics is not None:
            diagnostics.extend(item for item in page_diagnostics if item['action'] != 'SOURCE_PAGE_COUNT')
        if not rows:
            if not merged:
                raise ProviderError('NO_COMPLETE_BARS', '上游未提供有效历史日线')
            return [merged[key] for key in sorted(merged)]
        oldest = rows[0]['time']
        if previous_start is not None and oldest >= previous_start:
            raise ProviderError('HISTORY_PAGINATION', '历史接口未继续向前分页，已保留原缓存')
        for row in rows:
            merged[row['time']] = row
        if source_count < page_size:
            return [merged[key] for key in sorted(merged)]
        previous_start = oldest
        end = (date.fromisoformat(oldest) - timedelta(days=1)).isoformat()
    raise ProviderError('HISTORY_LIMIT', '历史分页达到保护上限，已保留原缓存')


class TencentProvider:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 10.0):
        self._owns_client = client is None
        if not 0 < timeout <= 30:
            raise ProviderError("INVALID_REQUEST", "请求超时须在0到30秒之间")
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}, trust_env=False)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def full_history(self, security_id: str, adjustment: str = 'none') -> list[dict[str, Any]]:
        def get(url, params):
            try:
                response = self.client.get(url, params=params, timeout=self.timeout, follow_redirects=False)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                raise ProviderError('UPSTREAM_UNAVAILABLE', '历史分页请求失败，已保留原缓存') from exc
        try:
            rows = download_tencent_history(get, security_id, adjustment=adjustment)
        except ProviderError as primary:
            if adjustment == 'none' or primary.code in {'INVALID_ADJUSTMENT', 'INVALID_SECURITY'}:
                raise
            # 整段使用同一备用复权序列，不能把两种来源的复权价格逐日拼接。
            try:
                return self._eastmoney_history(security_id, adjustment)
            except ProviderError as fallback:
                raise ProviderError('HISTORY_UNAVAILABLE',
                    f'复权历史获取失败：腾讯（{primary.message}）；东方财富（{fallback.message}）') from fallback
        # 腾讯 fqkline 不返回成交额；用同日东方财富金额补齐，失败时保留腾讯 OHLCV。
        try:
            rows = self._merge_eastmoney_amount(rows, security_id, adjustment)
        except (ProviderError, httpx.HTTPError):
            pass
        return rows

    def _eastmoney_response(self, security_id: str, adjustment: str):
        sid, code = normalize_security_id(security_id)
        market = '1' if sid.startswith('SH.') else '0'
        try:
            response = self.client.get(EASTMONEY_KLINE_URL, params={
                'secid': f'{market}.{code[2:]}',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
                'klt': '101', 'fqt': {'none':'0', 'qfq':'1', 'hfq':'2'}[adjustment],
                'beg': '0', 'end': '20500101',
            }, timeout=self.timeout, follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError('UPSTREAM_UNAVAILABLE', '东方财富日线请求失败') from exc
        return response

    def _eastmoney_history(self, security_id: str, adjustment: str):
        response = self._eastmoney_response(security_id, adjustment)
        fetched = datetime.now(CHINA_TZ)
        cutoff = fetched.date() + timedelta(days=1) if fetched.hour >= 16 else fetched.date()
        rows = parse_eastmoney_daily(response.content, security_id, fetched_at=fetched,
                                    today=cutoff, adjustment=adjustment)
        data = response.json()['data']
        total = data.get('dktotal')
        if not rows or not isinstance(total, int) or len(data['klines']) != total:
            raise ProviderError('INCOMPLETE_HISTORY', '东方财富未返回完整历史，保留已有数据')
        times = [row['time'] for row in rows]
        if times != sorted(set(times)):
            raise ProviderError('INVALID_RESPONSE', '东方财富历史日期重复或乱序')
        return [{**row, 'source': f'东方财富公开日线 / {"前复权" if adjustment == "qfq" else "后复权"}（备用源）'} for row in rows]

    def _merge_eastmoney_amount(self, rows: list[dict[str, Any]], security_id: str, adjustment: str) -> list[dict[str, Any]]:
        sid, _ = normalize_security_id(security_id)
        response = self._eastmoney_response(sid, adjustment)
        amount_rows = parse_eastmoney_daily(response.content, sid, adjustment=adjustment,
                                            today=date.max)
        by_date = {row["time"]: row["amount"] for row in amount_rows}
        return [{**row, "amount": by_date.get(row["time"], row.get("amount")),
                 "amount_unit": "CNY" if by_date.get(row["time"]) is not None else row.get("amount_unit", "UNKNOWN"),
                 "source": "腾讯财经公开日线 / 东方财富成交额补齐" if by_date.get(row["time"]) is not None else row.get("source")}
                for row in rows]

    def quotes(self, security_ids: list[str]) -> list[dict[str, Any]]:
        if not security_ids or len(security_ids) > 50:
            raise ProviderError("INVALID_REQUEST", "快照代码数量须为1到50")
        codes = [normalize_security_id(s)[1] for s in security_ids]
        try:
            response = self.client.get(QUOTE_URL + ",".join(codes), timeout=self.timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ProviderError("UPSTREAM_UNAVAILABLE", "腾讯快照请求失败") from exc
        if response.status_code != 200:
            raise ProviderError("UPSTREAM_ERROR", f"腾讯快照HTTP状态异常: {response.status_code}")
        return parse_tencent_quotes(response.content, security_ids)

    def daily(self, security_id: str, adjustment: str = "none", count: int = 2000) -> list[dict[str, Any]]:
        sid, tx_code = normalize_security_id(security_id)
        if adjustment not in {"none", "qfq", "hfq"} or type(count) is not int or not 1 <= count <= 2000:
            raise ProviderError("INVALID_REQUEST", "日线调整类型或数量无效")
        source_adjustment = "" if adjustment == "none" else adjustment
        try:
            response = self.client.get(KLINE_URL, params={"param": f"{tx_code},day,,,{count},{source_adjustment}"}, timeout=self.timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ProviderError("UPSTREAM_UNAVAILABLE", "腾讯日线请求失败") from exc
        if response.status_code != 200:
            raise ProviderError("UPSTREAM_ERROR", f"腾讯日线HTTP状态异常: {response.status_code}")
        fetched = datetime.now(CHINA_TZ)
        cutoff = fetched.date() + timedelta(days=1) if fetched.hour >= 16 else fetched.date()
        rows = parse_tencent_daily(response.content, sid, adjustment=adjustment, today=cutoff)
        try:
            rows = self._merge_eastmoney_amount(rows, sid, adjustment)
        except (ProviderError, httpx.HTTPError):
            pass
        return rows
