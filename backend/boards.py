"""东方财富板块只读适配与独立缓存；不改变证券行业、不调用算法或交易。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from backend.providers import CHINA_TZ, ProviderError, normalize_security_id
from backend.terminal_data import market_open
from backend.board_features import ProviderFeatures, DataFeatures
from backend.board_positions import PositionFeatures

SOURCE = '东方财富公开板块行情'
LIST_URL = 'https://push2delay.eastmoney.com/api/qt/clist/get'
HISTORY_ROOT = 'https://push2his.eastmoney.com/api/qt/stock/'
FIELDS = 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f23,f62,f66,f69,f72,f75,f78,f81,f84,f87,f104,f105,f106,f109,f124,f127,f128,f136,f140,f141,f160,f164,f165,f172,f173,f184,f267,f268'
BOARD = re.compile(r'BK\d{4,6}')


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def number(value, signed=False):
    if value is None or value in ('', '-', '--'):
        return None
    if isinstance(value, bool):
        raise ValueError('invalid numeric field')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid numeric field') from exc
    if not result.is_finite() or abs(result) > Decimal('1e20') or not signed and result < 0:
        raise ValueError('invalid numeric field')
    return format(result, 'f')


def source_time(value):
    text = number(value)
    if text is None or Decimal(text) == 0:
        return None
    result = datetime.fromtimestamp(int(Decimal(text)), timezone.utc)
    if result.year < 2000 or result > datetime.now(timezone.utc):
        raise ValueError('invalid source time')
    return result.isoformat().replace('+00:00', 'Z')


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid name')
    return value.strip()


class BoardProvider(ProviderFeatures):
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=10, follow_redirects=False,
            trust_env=False,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'})
        self.owned = client is None
        self.hashes = []
        self.started = time.monotonic()

    def close(self):
        if self.owned:
            self.client.close()

    def get(self, url, params):
        if time.monotonic() - self.started > 90:
            raise ValueError('upstream task deadline exceeded')
        for attempt in range(2):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt:
                    raise
        if len(response.content) > 5_000_000:
            raise ValueError('oversized response')
        payload = response.json()
        if not isinstance(payload, dict) or payload.get('rc') != 0 or not isinstance(payload.get('data'), dict):
            raise ValueError('invalid upstream response')
        self.hashes.append(hashlib.sha256(response.content).hexdigest())
        return payload['data']

    def pages(self, scope):
        rows, seen, total = [], set(), None
        for page in range(1, 61):
            data = self.get(LIST_URL, dict(pn=page, pz=100, fs=scope, fields=FIELDS,
                fid='f12', po=0, fltt=2, np=1))
            count = data.get('total')
            if type(count) is not int or not 0 < count <= 6000 or total is not None and total != count:
                raise ValueError('unstable total')
            total = count
            batch = data.get('diff')
            if isinstance(batch, dict):
                batch = list(batch.values())
            if not isinstance(batch, list) or not batch or len(batch) > 100:
                raise ValueError('incomplete page')
            for row in batch:
                if not isinstance(row, dict):
                    raise ValueError('invalid row')
                identity = (row.get('f13'), row.get('f12'))
                if identity in seen:
                    raise ValueError('overlapping pages')
                seen.add(identity)
                rows.append(row)
            if len(rows) >= total:
                if len(rows) != total:
                    raise ValueError('incorrect total')
                return rows, total
        raise ValueError('pagination limit')

    def boards(self, kind):
        raw, total = self.pages('m:90+t:' + ('2' if kind == 'industry' else '3'))
        rows = []
        for item in raw:
            code = item.get('f12')
            if not isinstance(code, str) or not BOARD.fullmatch(code):
                raise ValueError('invalid board identity')
            leader_code = item.get('f140')
            leader = None
            if isinstance(leader_code, str) and re.fullmatch(r'\d{6}', leader_code) and item.get('f141') in (0, 1):
                try:
                    canonical, _ = normalize_security_id(('SH.' if item['f141'] == 1 else 'SZ.') + leader_code)
                    leader = dict(id='LIVE.' + canonical, code=leader_code, name=text(item.get('f128')), change_pct=number(item.get('f136'), True))
                except ProviderError:
                    pass  # 领涨证券超出现有普通A股范围时，不丢弃有效板块。
            counts = {}
            for field, target in [('f104', 'advancing'), ('f105', 'declining'), ('f106', 'unchanged')]:
                n = number(item.get(field))
                if n is not None and Decimal(n) != Decimal(n).to_integral_value():
                    raise ValueError('invalid count')
                counts[target] = int(n) if n is not None else None
            rows.append(dict(id=code, code=code, kind=kind, name=text(item.get('f14')),
                price=number(item.get('f2')), change_pct=number(item.get('f3'), True),
                amount=number(item.get('f6')), turnover_rate=number(item.get('f8')),
                net_inflow=number(item.get('f62'), True), net_ratio=number(item.get('f184'), True),
                source_time=source_time(item.get('f124')), leader=leader, **counts, **self.extra_fields(item)))
        return dict(rows=rows, total=total, source=SOURCE, raw_hashes=self.hashes)

    def members(self, code):
        raw, total = self.pages('b:' + code)
        rows = []
        for item in raw:
            if item.get('f13') not in (0, 1):
                continue  # 维持现有沪深普通A股范围，不创建北交所证券。
            try:
                canonical, _ = normalize_security_id(('SH.' if item['f13'] == 1 else 'SZ.') + str(item.get('f12')))
            except ProviderError:
                continue
            price = number(item.get('f2'))
            volume = number(item.get('f5'))
            quote = dict(price=price if price and Decimal(price) > 0 else None,
                previous_close=number(item.get('f18')), change_pct=number(item.get('f3'), True),
                change=number(item.get('f4'), True), amount=number(item.get('f6')),
                volume=int(Decimal(volume) * 100) if volume is not None else None,
                volume_unit='SHARES', amount_unit='CNY', turnover_rate=number(item.get('f8')),
                volume_ratio=number(item.get('f10')), float_market_cap=number(item.get('f21')),
                amplitude=number(item.get('f7')), open=number(item.get('f17')), high=number(item.get('f15')), low=number(item.get('f16')),
                total_market_cap=number(item.get('f20')), pe_dynamic=number(item.get('f9'), True),
                as_of=source_time(item.get('f124')), source=SOURCE, mode='LIVE', is_realtime=False,
                net_inflow=number(item.get('f62'), True), net_ratio=number(item.get('f184'), True), **self.extra_fields(item))
            rows.append(dict(id='LIVE.' + canonical, code=item['f12'], name=text(item.get('f14')),
                exchange='SSE' if canonical.startswith('SH.') else 'SZSE', sector='板块成分',
                status='LIVE_UNVERIFIED', quote=quote))
        return dict(code=code, rows=rows, total=total, loaded=len(rows), source=SOURCE, raw_hashes=self.hashes)

    def extra_fields(self, item):
        mapping = {'speed': 'f22', 'pb': 'f23', 'super_net': 'f66', 'large_net': 'f72', 'medium_net': 'f78',
            'small_net': 'f84', 'net_3d': 'f267', 'ratio_3d': 'f268',
            'net_5d': 'f164', 'ratio_5d': 'f165', 'change_5d': 'f109',
            'net_10d': 'f172', 'ratio_10d': 'f173', 'change_10d': 'f160'}
        return {key: number(item.get(field), True) for key, field in mapping.items()}

    def chart(self, code, period, market=90, limit=160):
        url = HISTORY_ROOT + {'intraday': 'trends2/get', 'daily': 'kline/get', 'funds': 'fflow/daykline/get'}[period]
        params = dict(secid=str(market) + '.' + code)
        if period == 'intraday':
            params.update(fields1='f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',
                fields2='f51,f52,f53,f54,f55,f56,f57,f58', ndays=1, iscr=0)
        elif period == 'daily':
            params.update(fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                klt=101, fqt=0, lmt=limit, end='20500101')
        else:
            params.update(fields1='f1,f2,f3,f7', fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63', klt=101, lmt=20)
        data = self.get(url, params)
        if data.get('code') != code or data.get('market') != market:
            raise ValueError('chart identity mismatch')
        raw = data.get('trends' if period == 'intraday' else 'klines')
        if not isinstance(raw, list) or not 0 < len(raw) <= 1000:
            raise ValueError('empty chart')
        points, bars, flows, previous = [], [], [], ''
        for row in raw:
            if not isinstance(row, str):
                raise ValueError('invalid chart row')
            cells = row.split(',')
            if len(cells) < (8 if period == 'intraday' else 11 if period == 'daily' else 13):
                raise ValueError('short chart row')
            dt = datetime.strptime(cells[0], '%Y-%m-%d %H:%M' if period == 'intraday' else '%Y-%m-%d')
            # 国内期货夜盘归下一交易日；周五夜盘日K可标为下周一。
            latest_day = datetime.now(CHINA_TZ).date() + timedelta(days=4 if market in {113, 114, 115, 8, 142, 225} else 0)
            if cells[0] <= previous or dt.date() > latest_day:
                raise ValueError('invalid chart dates')
            previous = cells[0]
            if period == 'intraday':
                volume = number(cells[5])
                value = number(cells[2])
                if value is None or Decimal(value) <= 0:
                    raise ValueError('invalid point')
                points.append(dict(time=dt.replace(tzinfo=CHINA_TZ).astimezone(timezone.utc).isoformat(),
                    value=value, volume=int(Decimal(volume) * (100 if market == 90 else 1)) if volume is not None else None))
            elif period == 'daily':
                values = dict(zip(('open', 'close', 'high', 'low'), [number(x) for x in cells[1:5]]))
                if any(v is None or Decimal(v) <= 0 for v in values.values()) or not (
                    Decimal(values['low']) <= min(Decimal(values['open']), Decimal(values['close'])) <=
                    max(Decimal(values['open']), Decimal(values['close'])) <= Decimal(values['high'])):
                    raise ValueError('invalid OHLC')
                volume = number(cells[5])
                bars.append(dict(time=cells[0], volume=int(Decimal(volume) * (100 if market == 90 else 1)) if volume else None,
                    amount=number(cells[6]), change_pct=number(cells[8], True), turnover_rate=number(cells[10]), **values))
            else:
                flows.append(dict(time=cells[0], net_inflow=number(cells[1], True),
                    net_ratio=number(cells[6], True), close=number(cells[11]), change_pct=number(cells[12], True)))
        return dict(code=code, name=text(data.get('name')), symbol=code, period=period,
            points=points, bars=bars, flows=flows, previous_close=number(data.get('preClose')),
            average_supported=False, source=SOURCE, trade_date=raw[-1][:10],
            source_time=source_time(data.get('time')) if period == 'intraday' else None,
            raw_hashes=self.hashes, source_url=url)


class BoardsData(DataFeatures, PositionFeatures):
    def __init__(self, store, terminal):
        self.store, self.terminal = store, terminal
        self.factory = BoardProvider
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='board-cache')
        self.lock = threading.RLock()
        self.pending, self.due, self.errors = set(), {}, {}
        self.manual_due = {}
        self.history_slots = threading.BoundedSemaphore(4)
        self.closed = False

    def read(self, key, task, ttl=None, force=False):
        ttl = ttl or (30 if market_open() else 300)
        saved = self.store.get('board_cache', key, False)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(saved['fetched_at'].replace('Z', '+00:00'))).total_seconds() if saved else None
        with self.lock:
            enabled = self.terminal.network_enabled and self.terminal.config()['enabled']
            manual = force and self.terminal.network_enabled and time.monotonic() >= self.manual_due.get(key, 0)
            if not self.closed and (enabled or manual) and len(self.pending) < 12 and (manual or age is None or age >= ttl) and key not in self.pending and (manual or time.monotonic() >= self.due.get(key, 0)):
                self.pending.add(key)
                if manual:
                    self.manual_due[key] = time.monotonic() + 5
                self.pool.submit(self.refresh, key, task, ttl)
            updating = key in self.pending
            error = self.errors.get(key)
        return {**(saved or {}), 'status': 'READY' if saved else 'LOADING' if updating else 'EMPTY',
            'refreshing': updating, 'stale': saved is not None and age >= ttl,
            'error': error, 'enabled': enabled, 'fetched_at': saved.get('fetched_at') if saved else None}

    def refresh(self, key, task, ttl):
        provider = None
        try:
            provider = self.factory()
            result = task(provider)
            saved = dict(id=key, fetched_at=stamp(), **result)
            with self.store.lock, self.store.db:
                self.store.put('board_cache', saved)
                if key.startswith('list:'):
                    # 按源交易日归档，抓取日期不能作为源交易日。
                    dates = {datetime.fromisoformat(r['source_time'].replace('Z', '+00:00')).astimezone(CHINA_TZ).date().isoformat() for r in result['rows'] if r.get('source_time')}
                    if len(dates) == 1 and all(r.get('source_time') for r in result['rows']):
                        day = next(iter(dates))
                        ordered = sorted(result['rows'], key=lambda r: Decimal(r['change_pct']) if r['change_pct'] is not None else Decimal('-Infinity'), reverse=True)
                        self.store.put('board_rotation', dict(id=key + ':' + day, kind=key.split(':')[1], date=day,
                            fetched_at=saved['fetched_at'], source=SOURCE, rows=ordered[:10]))
            with self.lock:
                self.errors.pop(key, None)
                self.due[key] = time.monotonic() + ttl
        except Exception as exc:
            logging.getLogger(__name__).warning('Board cache %s failed (%s)', key, type(exc).__name__)
            with self.lock:
                self.errors[key] = '上游暂时不可用，稍后自动重试'
                self.due[key] = time.monotonic() + 300
        finally:
            if provider is not None:
                provider.close()
            with self.lock:
                self.pending.discard(key)

    def boards(self, kind, force=False):
        if kind not in ('industry', 'concept'):
            raise ProviderError('INVALID_BOARD_KIND', '请选择行业或概念板块')
        return self.read('list:' + kind, lambda p: p.boards(kind), force=force)

    def validate(self, code):
        if not BOARD.fullmatch(code):
            raise ProviderError('INVALID_BOARD', '板块代码格式无效')
        if not any(any(row['code'] == code for row in (self.store.get('board_cache', 'list:' + kind, False) or {}).get('rows', [])) for kind in ('industry', 'concept')):
            raise ProviderError('UNKNOWN_BOARD', '板块不在当前来源目录中，请先加载板块列表')

    def members(self, code, force=False):
        self.validate(code)
        return self.read('members:' + code, lambda p: p.members(code), force=force)

    def chart(self, code, period, force=False):
        self.validate(code)
        if period not in ('intraday', 'daily', 'funds'):
            raise ProviderError('INVALID_PERIOD', '请选择分时、日线或资金历史')
        return self.read(period + ':' + code, lambda p: p.chart(code, period), ttl=3600 if period != 'intraday' else None, force=force)

    def request(self, kind, code=None, period='intraday'):
        if kind not in ('industry', 'concept') or period not in ('intraday', 'daily', 'funds'):
            raise ProviderError('INVALID_BOARD_REQUEST', '请选择有效的板块分类与周期')
        if code is not None:
            self.validate(code)
        results = [self.boards(kind, force=True)]
        if code is not None:
            results.extend([self.members(code, force=True), self.chart(code, period, force=True)])
        return dict(queued=any(r['refreshing'] for r in results), enabled=self.terminal.config()['enabled'])

    def rotation(self, kind):
        if kind not in ('industry', 'concept'):
            raise ProviderError('INVALID_BOARD_KIND', '请选择行业或概念板块')
        rows = sorted((r for r in self.store.all('board_rotation') if r['kind'] == kind), key=lambda r: r['date'], reverse=True)[:10]
        return dict(days=rows, source=SOURCE)

    def stop(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
