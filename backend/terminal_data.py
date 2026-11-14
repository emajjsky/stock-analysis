"""股票终端缓存与有限后台刷新。无交易接口，不调用 Agent。"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from backend.catalog import Catalog, stamp
from backend.catalog_quotes import CatalogQuotes
from backend.providers import (CHINA_TZ, KLINE_URL, QUOTE_URL, ProviderError, _decimal,
                               normalize_security_id, parse_tencent_daily, parse_tencent_quotes, download_tencent_history)

INDEXES = [('sh000001', '上证指数'), ('sz399001', '深证成指'), ('sz399006', '创业板指'),
           ('sh000300', '沪深300'), ('sh000016', '上证50'), ('sh000905', '中证500'),
           ('sh000852', '中证1000'), ('sh000688', '科创50')]
INDEX_MAP = dict(INDEXES)


def index_id(symbol):
    if symbol not in INDEX_MAP:
        raise ProviderError('INVALID_INDEX', '不支持的指数代码')
    return symbol[:2].upper() + '.' + symbol[2:]


def market_open(at=None):
    current = (at or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
    minute = current.hour * 60 + current.minute
    # 未接法定假日/临时休市日历，只是刷新时段提示，不能用作交易许可。
    return current.weekday() < 5 and (555 <= minute <= 690 or 780 <= minute <= 905)


class TerminalProvider:
    def __init__(self):
        self.client = httpx.Client(timeout=8, follow_redirects=False,
                                   headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'},
                                   trust_env=False)
        self.history_diagnostics = []
        self.minute_primary_error = None

    def close(self):
        self.client.close()

    def get(self, url, params=None):
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            if '/minute/' in url:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                message = f'腾讯分时来源返回 HTTP {status}' if status else '腾讯分时来源连接超时或中断'
                raise ProviderError('INTRADAY_UNAVAILABLE', message) from exc
            raise ProviderError('INDEX_UNAVAILABLE', '行情来源暂不可用，已保留缓存') from exc

    def quotes(self):
        symbols = [x[0] for x in INDEXES]
        result = parse_tencent_quotes(self.get(QUOTE_URL + ','.join(symbols)),
                                      [index_id(x) for x in symbols], allow_index=True)
        # 八指数实测原始成交量为手，与股票科创板的特殊单位区分。
        return result

    def daily(self, symbol):
        current = datetime.now(CHINA_TZ)
        cutoff = current.date() + timedelta(days=1) if current.hour >= 16 else current.date()
        rows = parse_tencent_daily(self.get(KLINE_URL, {'param': f'{symbol},day,,,2000,'}),
                                  index_id(symbol), allow_index=True, today=cutoff)
        return rows

    def full_history(self, symbol):
        self.history_diagnostics = []
        return download_tencent_history(self.get, index_id(symbol), allow_index=True, diagnostics=self.history_diagnostics)

    def stock_intraday(self, security_id):
        canonical, symbol = normalize_security_id(security_id.removeprefix('LIVE.'))
        return self.intraday(symbol, volume_multiplier=1 if canonical.startswith('SH.688') else 100)

    def stock_trades(self, security_id):
        canonical, symbol = normalize_security_id(security_id.removeprefix('LIVE.'))
        url = 'https://push2.eastmoney.com/api/qt/stock/details/get'
        try:
            response = self.client.get(url, params=dict(
                secid=('1.' if canonical.startswith('SH.') else '0.') + symbol[2:],
                fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f54,f55', pos=-1000),
                headers={'Referer':'https://quote.eastmoney.com/'})
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data')
            if payload.get('rc') != 0 or not isinstance(data, dict) or str(data.get('code')) != symbol[2:] or data.get('market') != (1 if canonical.startswith('SH.') else 0):
                raise ValueError('身份或响应状态不匹配')
            trades = []
            for row in data.get('details', []):
                fields = row.split(',') if isinstance(row, str) else []
                if len(fields) != 5 or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', fields[0]):
                    raise ValueError('逐笔字段无效')
                price, lots = _decimal(fields[1]), _decimal(fields[2])
                if price is None or Decimal(price) <= 0 or lots is None or Decimal(lots) < 0 or Decimal(lots) != Decimal(lots).to_integral_value():
                    raise ValueError('逐笔价格或手数无效')
                trades.append(dict(time=fields[0], price=price, volume_lots=int(lots),
                    side={'1':'BUY','2':'SELL'}.get(fields[4], 'UNKNOWN')))
            return dict(security_id=canonical, trades=trades, source='东方财富公开逐笔成交',
                        fetched_at=stamp())
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError('TRADES_UNAVAILABLE', '逐笔成交暂不可用，报价与五档盘口仍可查看') from exc

    def intraday(self, symbol, *, volume_multiplier=100):
        # 同一后台批次只尝试一次已失败的主源；切换完整序列，不逐点拼接。
        if not self.minute_primary_error:
            try:
                return self._tencent_intraday(symbol, volume_multiplier=volume_multiplier)
            except ProviderError as exc:
                self.minute_primary_error = exc.message
        try:
            return self._eastmoney_intraday(symbol)
        except ProviderError as exc:
            raise ProviderError('INTRADAY_UNAVAILABLE', self.minute_primary_error + '；' + exc.message) from exc

    def _eastmoney_intraday(self, symbol):
        if symbol not in INDEX_MAP:
            normalize_security_id(symbol[:2].upper()+'.'+symbol[2:])
        url = 'https://push2his.eastmoney.com/api/qt/stock/trends2/get'
        try:
            response = self.client.get(url, params=dict(secid=('1.' if symbol.startswith('sh') else '0.')+symbol[2:],
                fields1='f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',
                fields2='f51,f52,f53,f54,f55,f56,f57,f58', iscr=0, ndays=1),
                headers={'Referer':'https://quote.eastmoney.com/'})
            response.raise_for_status()
            payload = response.json()
            data = payload['data']
            if payload.get('rc') != 0 or str(data['code']) != symbol[2:] or data['market'] != (1 if symbol.startswith('sh') else 0):
                raise ValueError('identity mismatch')
            points, cumulative, amount, day, previous = [], 0, Decimal(0), None, None
            for row in data['trends']:
                fields = row.split(',')
                if len(fields) != 8:
                    raise ValueError('invalid columns')
                moment = datetime.strptime(fields[0], '%Y-%m-%d %H:%M').replace(tzinfo=CHINA_TZ)
                close, lots, turnover = _decimal(fields[2]), _decimal(fields[5]), _decimal(fields[6])
                if close is None or Decimal(close)<=0 or lots is None or turnover is None or Decimal(lots)!=Decimal(lots).to_integral_value():
                    raise ValueError('invalid price or volume')
                if previous is not None and (moment<=previous or moment.date()!=day):
                    raise ValueError('mixed or unsorted dates')
                day, previous = moment.date(), moment
                volume = int(lots)*100  # 东方财富分钟f56为手，包括科创板；不同于腾讯科创板单位。
                cumulative += volume
                amount += Decimal(turnover)
                points.append(dict(time=moment.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
                    value=close,volume=volume,cumulative_volume=cumulative,cumulative_amount=format(amount,'f'),
                    average_price=format(amount/cumulative,'.4f') if cumulative and symbol not in INDEX_MAP else None))
            if not points:
                raise ValueError('empty trends')
            return dict(symbol=symbol,points=points,source='东方财富公开分时',source_url=url,
                source_time=points[-1]['time'],fetched_at=stamp(),trade_date=day.isoformat(),
                previous_close=_decimal(str(data.get('preClose',''))),average_supported=symbol not in INDEX_MAP,
                fallback=True,primary_error=self.minute_primary_error,error=None)
        except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError) as exc:
            raise ProviderError('INTRADAY_UNAVAILABLE','东方财富分时来源暂不可用') from exc

    def _tencent_intraday(self, symbol, *, volume_multiplier=100):
        try:
            payload = json.loads(self.get('https://web.ifzq.gtimg.cn/appstock/app/minute/query', {'code': symbol}))
            content = payload['data'][symbol]['data']
            day = datetime.strptime(content['date'], '%Y%m%d').date()
            points, previous_volume, previous_amount = [], 0, None
            for row in content['data']:
                fields = row.split()
                if len(fields) < 2 or len(fields[0]) != 4 or _decimal(fields[1]) is None:
                    raise ValueError('invalid point')
                moment = datetime.combine(day, datetime.strptime(fields[0], '%H%M').time(), CHINA_TZ)
                cumulative = int(fields[2]) * volume_multiplier if len(fields) >= 3 and fields[2].isdigit() else None
                volume = cumulative - previous_volume if cumulative is not None and previous_volume is not None else None
                if volume is not None and volume < 0:
                    raise ValueError('non-monotonic cumulative volume')
                previous_volume = cumulative
                amount_raw = _decimal(fields[3]) if len(fields) >= 4 else None
                amount = Decimal(amount_raw) if amount_raw is not None else None
                if amount is not None and previous_amount is not None and amount < previous_amount:
                    raise ValueError('non-monotonic cumulative amount')
                previous_amount = amount if amount is not None else previous_amount
                # 指数成交额/成分股股数是股票均价，不是指数点位的均价线。
                average = format(amount / cumulative, '.4f') if symbol not in INDEX_MAP and amount is not None and cumulative else None
                points.append(dict(time=moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                                   value=fields[1], volume=volume, average_price=average,
                                   cumulative_volume=cumulative, cumulative_amount=amount_raw))
            if not points:
                raise ValueError('empty series')
            return dict(symbol=symbol, points=points, source='腾讯财经公开分时',
                        average_supported=symbol not in INDEX_MAP,
                        source_time=points[-1]['time'], fetched_at=stamp(), trade_date=day.isoformat(), error=None)
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError('INTRADAY_UNAVAILABLE', '来源暂未返回有效分时数据') from exc


class TerminalData:
    def __init__(self, store, market_data, *, network_enabled=False):
        self.store, self.market_data = store, market_data
        self.catalog = Catalog(store)
        self.provider_factory = TerminalProvider
        self.ranking_provider_factory = None
        self.ranking_next = 0.0
        self.ranking_error = None
        self.network_enabled = network_enabled
        self.thread = None
        self.catalog_thread = None
        self.stopping = threading.Event()
        self.wakeup = threading.Event()
        self.run_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.running, self.phase, self.error = False, 'IDLE', None
        self.manual = False
        self.pending_symbols = {'sh000001'}
        self.chart_queued_at = {}
        self.stock_queued_at = {}
        self.last_attempt_at = self.last_success_at = None
        self.next_poll = self.next_catalog = 0.0
        self.failures = 0
        self.catalog_quotes = CatalogQuotes(store, market_data,
            enabled=lambda: self.network_enabled and self.config()['enabled'],
            interval=lambda: self.config()['interval_seconds'], market_open=market_open)

    def config(self):
        return self.store.get('terminal', 'refresh', False) or dict(id='refresh', enabled=True, interval_seconds=60)

    def effective_interval(self):
        interval = self.config()['interval_seconds']
        if not market_open():
            interval = max(300, interval)
        return max(interval, min(900, 30 * 2 ** min(self.failures, 5)))

    def _implicit_request_due(self, last_request, *, cached):
        """普通 GET 服从轮询/失败退避；首次缺缓存允许按需初始化。"""
        if not self.config()['enabled'] or self.running:
            return False
        current = time.monotonic()
        if self.failures and current < self.next_poll:
            return False
        if not cached and last_request == float('-inf'):
            return True
        return current >= self.next_poll and current - last_request >= self.effective_interval()

    def status(self):
        config = self.config()
        return dict(enabled=config['enabled'], interval_seconds=config['interval_seconds'],
                    running=self.running, phase=self.phase, last_attempt_at=self.last_attempt_at,
                    last_success_at=self.last_success_at, error=self.error, market_open=market_open())

    def configure(self, changes):
        with self.store.lock, self.store.db:
            config = self.config()
            config.update(changes)
            self.store.put('terminal', config)
        self.next_poll = 0.0
        self.wakeup.set()
        return self.status()

    def queue_catalog(self):
        with self.state_lock:
            if self.network_enabled and not (self.catalog_thread and self.catalog_thread.is_alive()):
                self.catalog.running = True
                self.catalog_thread = threading.Thread(target=self.catalog.sync, name='security-catalog', daemon=True)
                self.catalog_thread.start()
        return self.catalog.status()

    def queue_refresh(self):
        with self.state_lock:
            self.manual = True
        self.wakeup.set()
        return self.status()

    def touch(self, key):
        with self.store.lock, self.store.db:
            self.store.put('terminal_recent', dict(id=key, visited_at=stamp()))
            rows = sorted(self.store.all('terminal_recent'), key=lambda x: x['visited_at'], reverse=True)
            for row in rows[20:]:
                self.store.db.execute("DELETE FROM documents WHERE kind='terminal_recent' AND id=?", (row['id'],))
        self.queue_refresh()

    def activate(self, key):
        existing = self.store.get('security', key, False)
        if not existing:
            row = self.catalog.find(key)
            if not row:
                return None
            row = {k: v for k, v in row.items() if k != 'quote'}
            with self.store.lock, self.store.db:
                self.store.put('security', row)
        if key.startswith('LIVE.'):
            self.touch(key)
        return self.store.security(key)

    def overview(self):
        saved = {row['id']: row for row in self.store.all('index_quote')}
        indices = []
        for symbol, name in INDEXES:
            row = saved.get(symbol, {})
            indices.append(dict(id=symbol, symbol=symbol, name=name, price=row.get('price'), previous_close=row.get('previous_close'),
                change_pct=row.get('change_pct'), volume=row.get('volume'), amount=row.get('amount'),
                source='腾讯财经公开行情', source_time=row.get('source_time'), fetched_at=row.get('fetched_at')))
        rankings = self.store.get('terminal', 'rankings', False)
        error = '；'.join(x for x in (self.error, self.ranking_error) if x) or None
        return dict(indices=indices, breadth=None, rankings=rankings['rows'] if rankings else dict(gainers=[], losers=[], amount=[]),
                    updated_at=max((x['fetched_at'] for x in indices if x['fetched_at']), default=None),
                    status='PARTIAL' if error and saved else 'ERROR' if error else 'READY' if saved else 'EMPTY', error=error)

    def refresh_rankings(self):
        if time.monotonic() < self.ranking_next or not (self.network_enabled or self.ranking_provider_factory):
            return
        provider = None
        try:
            factory = self.ranking_provider_factory
            if factory is None:
                from backend.market_rankings import SinaRankingProvider
                factory = SinaRankingProvider
            provider = factory()
            rows = provider.rankings()
            if set(rows) != {'gainers', 'losers', 'amount'} or any(not isinstance(x,list) for x in rows.values()):
                raise ProviderError('RANKINGS_INVALID', '市场榜单暂不可用')
            with self.store.lock, self.store.db:
                self.store.put('terminal', dict(id='rankings', rows=rows, updated_at=stamp()))
            self.ranking_error = None
            self.ranking_next = time.monotonic() + 300
        except Exception:
            self.ranking_error = '市场榜单更新失败，已保留缓存'
            self.ranking_next = time.monotonic() + 900
        finally:
            if provider:
                provider.close()

    def request_chart(self, symbol, kind='index_intraday'):
        index_id(symbol)
        with self.state_lock:
            self.pending_symbols.add(symbol)
            last = self.chart_queued_at.get(symbol, float('-inf'))
            should_queue = self._implicit_request_due(last, cached=bool(self.store.get(kind, symbol, False)))
            if should_queue:
                self.chart_queued_at[symbol] = time.monotonic()
        if should_queue and self.config()['enabled']:
            self.queue_refresh()

    def index_bars(self, symbol):
        self.request_chart(symbol, 'index_daily')
        row = self.store.get('index_daily', symbol, False)
        return row['bars'] if row else []

    def index_history_diagnostics(self, symbol):
        row = self.store.get('index_daily', symbol, False)
        return row.get('history_diagnostics', []) if row else []

    def intraday(self, symbol):
        self.request_chart(symbol)
        row = self.store.get('index_intraday', symbol, False)
        if row:
            return {**{k:v for k,v in row.items() if k not in {'id','points'}}, 'average_supported':False,
                    'points':[{**p, 'average_price':None} for p in row['points']]}
        return dict(symbol=symbol, points=[], source='腾讯财经公开分时', source_time=None, error=None)

    def request_stock(self, key, kind='stock_intraday'):
        canonical, symbol = normalize_security_id(key.removeprefix('LIVE.'))
        if key != 'LIVE.' + canonical or not self.store.get('security', key, False):
            raise ProviderError('INVALID_SECURITY', '请先从证券目录打开真实行情证券')
        with self.state_lock:
            previous = self.stock_queued_at.get(key, float('-inf'))
            due = self._implicit_request_due(previous, cached=bool(self.store.get(kind, key, False)))
            if due:
                self.stock_queued_at[key] = time.monotonic()
        if due and self.config()['enabled']:
            self.touch(key)
        return symbol

    def stock_intraday(self, key):
        symbol = self.request_stock(key)
        row = self.store.get('stock_intraday', key, False)
        if row:
            return {k:v for k,v in row.items() if k != 'id'}
        return dict(symbol=symbol, points=[], source='腾讯财经公开分时', source_time=None, error=None)

    def _new_stock_waiting(self, current_ids):
        """首次打开的新证券优先于当前批次的长历史分页。"""
        return any(r['id'] not in current_ids and (not self.store.get('market_snapshot',r['id'],False)
            or not self.store.get('stock_intraday',r['id'],False)) for r in self.store.all('terminal_recent'))

    def refresh_once(self):
        if not self.run_lock.acquire(blocking=False):
            return self.status()
        self.running, self.phase, self.last_attempt_at = True, 'QUOTES', stamp()
        errors, successes, provider = [], 0, None
        realtime_failed = False
        try:
            provider = self.provider_factory()
            # 当前个股报价/分时优先，避免等待指数与个股历史分页补数。
            self.phase = 'WATCHLIST'
            ids = list(dict.fromkeys([x['id'] for x in sorted(self.store.all('terminal_recent'), key=lambda x:x['visited_at'], reverse=True)] +
                    [x['security_id'] for x in self.store.all('watch') if x['security_id'].startswith('LIVE.')]))[:50]
            if ids and not self.stopping.is_set():
                result = self.market_data.sync(ids)
                successes += bool(result['quotes_updated'])
                errors.extend(result['errors'])
                realtime_failed = bool(result['errors'])
                # 当前/最近访问分时最多三只；自选批量报价不等于全量分钟订阅。
                if hasattr(provider, 'stock_intraday'):
                    recent = sorted(self.store.all('terminal_recent'), key=lambda x:x['visited_at'], reverse=True)[:3]
                    for item in recent:
                        if self.stopping.is_set():
                            break
                        try:
                            series = provider.stock_intraday(item['id'])
                            with self.store.lock, self.store.db:
                                self.store.put('stock_intraday', {**series, 'id':item['id']})
                        except ProviderError as exc:
                            errors.append(exc.message)
                            realtime_failed = True
                            with self.store.lock, self.store.db:
                                old = self.store.get('stock_intraday',item['id'],False) or dict(
                                    id=item['id'],symbol=item['id'].removeprefix('LIVE.').replace('.','').lower(),
                                    points=[],source='腾讯财经公开分时',source_time=None)
                                self.store.put('stock_intraday',{**old,'error':exc.message})
            self.phase = 'QUOTES'
            try:
                quotes = provider.quotes()
                with self.store.lock, self.store.db:
                    for quote in quotes:
                        symbol = quote['security_id'].replace('.', '').lower()
                        self.store.put('index_quote', {**quote, 'id': symbol})
                successes += bool(quotes)
            except ProviderError as exc:
                errors.append(exc.message)
                realtime_failed = True
            self.phase = 'CHARTS'
            with self.state_lock:
                symbols = list(self.pending_symbols)
            for symbol in symbols[:8]:
                if self.stopping.is_set() or self._new_stock_waiting(ids):
                    break
                old = self.store.get('index_daily', symbol, False)
                try:
                    # 完成日线每天补齐一次，盘中不重复请求历史。
                    current = datetime.now(CHINA_TZ)
                    today = current.date().isoformat() + ('-CLOSE' if current.hour >= 16 else '-OPEN')
                    if not old or not old.get('history_complete') or old.get('checked_date') != today:
                        backfill = not old or not old.get('history_complete')
                        bars = provider.full_history(symbol) if backfill and hasattr(provider, 'full_history') else provider.daily(symbol)
                        if bars:
                            merged = {r['time']: r for r in (old or {}).get('bars', [])}
                            for row in bars:
                                saved = merged.get(row['time'])
                                fields = ('open', 'high', 'low', 'close', 'volume', 'amount')
                                if saved and any((saved.get(k) is None) != (row.get(k) is None) or
                                    (saved.get(k) is not None and Decimal(str(saved[k])) != Decimal(str(row[k]))) for k in fields):
                                    raise ProviderError('HISTORY_CONFLICT',
                                        'HISTORY_CONFLICT：指数历史存在数值修订，保留原数据：' + symbol + ' / ' + row['time'])
                                if row['time'] not in merged:
                                    merged[row['time']] = row
                            with self.store.lock, self.store.db:
                                self.store.put('index_daily', dict(id=symbol, bars=sorted(merged.values(), key=lambda x:x['time']), checked_date=today, history_limit=2000, history_complete=True, history_diagnostics=getattr(provider, 'history_diagnostics', [])))
                except ProviderError as exc:
                    errors.append(exc.message)
                # 历史冲突只阻止当前指数日线事务，不阻止独立分时缓存更新。
                try:
                    intraday = provider.intraday(symbol)
                    with self.store.lock, self.store.db:
                        self.store.put('index_intraday', {**intraday, 'id':symbol})
                    successes += 1
                except ProviderError as exc:
                    errors.append(exc.message)
                    realtime_failed = True
            if ids and not self.stopping.is_set():
                # 每只证券每天最多成功补齐一次，失败下轮重试；每轮最多5只。
                current = datetime.now(CHINA_TZ)
                today = current.date().isoformat() + ('-CLOSE' if current.hour >= 16 else '-OPEN')
                due = [key for key in ids if not self.store.get('terminal_history', key, False) or
                       self.store.get('terminal_history', key).get('history_version') != 2 or
                       self.store.get('terminal_history', key)['checked_date'] != today][:5]
                for key in due:
                    if self.stopping.is_set() or self._new_stock_waiting(ids):
                        break
                    result = self.market_data.sync([key], True)
                    if not result['errors']:
                        with self.store.lock, self.store.db:
                            self.store.put('terminal_history', dict(id=key, checked_date=today, history_version=2))
                    errors.extend(result['errors'])
            self.error = '；'.join(dict.fromkeys(errors))[:500] if errors else None
            if successes:
                self.last_success_at = stamp()
            # 历史修订/补数错误保留诊断，但不能让健康报价与分时进入全局失败退避。
            self.failures = self.failures + 1 if realtime_failed else 0
            if not self.stopping.is_set() and not self._new_stock_waiting(ids):
                self.phase = 'RANKINGS'
                self.refresh_rankings()
        except Exception:
            self.error = '行情更新失败，已保留缓存'
            self.failures += 1
        finally:
            if provider:
                provider.close()
            self.running, self.phase = False, 'ERROR' if self.error else 'IDLE'
            self.next_poll = time.monotonic() + self.effective_interval()
            self.run_lock.release()
        return self.status()

    def start(self):
        if not self.network_enabled or self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        # Home indices are a bounded eight-symbol cache; backfill them on first upgrade.
        self.pending_symbols.update(INDEX_MAP)
        self.thread = threading.Thread(target=self._loop, name='terminal-market-cache', daemon=True)
        self.thread.start()

        self.catalog_quotes.start()

    def _loop(self):
        while not self.stopping.is_set():
            config = self.config()
            with self.state_lock:
                manual, self.manual = self.manual, False
            if config['enabled'] or manual:
                catalog = self.catalog.status()
                if config['enabled'] and time.monotonic() >= self.next_catalog:
                    today = datetime.now(CHINA_TZ).date().isoformat()
                    updated = catalog.get('updated_at')
                    if not updated or datetime.fromisoformat(updated.replace('Z','+00:00')).astimezone(CHINA_TZ).date().isoformat() != today:
                        self.queue_catalog()
                    self.next_catalog = time.monotonic() + (900 if catalog['status'] != 'READY' else 3600)
                if manual or time.monotonic() >= self.next_poll:
                    self.refresh_once()
            self.wakeup.wait(1)
            self.wakeup.clear()

    def stop(self):
        self.stopping.set()
        self.catalog_quotes.stop()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=2)
