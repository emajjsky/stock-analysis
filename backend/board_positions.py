"""板块增仓：东方财富主力资金口径，历史净额和成交额按交易日对齐。"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import threading
import time

import httpx

from backend.providers import CHINA_TZ, ProviderError


def decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def ratio(net, amount):
    net, amount = decimal(net), decimal(amount)
    return format(net / amount * 100, '.6f') if net is not None and amount is not None and amount > 0 else None


def position_rows(listing, histories, calendar):
    """今日使用同一快照；2/3日必须覆盖连续交易日，不平均百分比或跳过缺失日。"""
    result = []
    for board in listing:
        row = {**board, 'position_today': ratio(board.get('net_inflow'), board.get('amount')),
               'position_2d': None, 'position_3d': board.get('ratio_3d')}
        source = board.get('source_time')
        day = datetime.fromisoformat(source.replace('Z', '+00:00')).astimezone(CHINA_TZ).date().isoformat() if source else None
        days = {d['time']: d for d in histories.get(board['code'], [])}
        if day:
            days[day] = dict(time=day, net_inflow=board.get('net_inflow'), amount=board.get('amount'))
            dates = sorted({d for d in calendar if d <= day} | {day})
            for count in (2, 3):
                window = dates[-count:]
                values = [days.get(d, {}) for d in window]
                nets = [decimal(d.get('net_inflow')) for d in values]
                amounts = [decimal(d.get('amount')) for d in values]
                if len(window) == count and all(n is not None for n in nets) and all(a is not None and a > 0 for a in amounts):
                    row['position_' + str(count) + 'd'] = ratio(sum(nets), sum(amounts))
        result.append(row)
    for period in ('today', '2d', '3d'):
        eligible = sorted((r for r in result if decimal(r.get('position_' + period)) is not None),
                          key=lambda r: decimal(r['position_' + period]), reverse=True)
        previous, rank = None, None
        for index, row in enumerate(eligible, 1):
            value = decimal(row['position_' + period])
            if value != previous:
                rank = index
            row['rank_' + period] = rank
            previous = value
    return result


class PositionFeatures:
    def positions(self, kind, force=False):
        listing = self.boards(kind, force=force)
        if not listing.get('rows'):
            return {**listing, 'rows': [], 'covered': 0, 'total': 0}
        fill = self.read('position-fill:' + kind, lambda p: self.fill_position_history(kind, manual=force), ttl=3600, force=force)
        snapshot = self.store.get('board_cache', 'position-snapshot:' + kind, False) or {}
        rows = position_rows(listing['rows'], {r['code']: r['days'] for r in snapshot.get('rows', [])}, snapshot.get('calendar', []))
        return {**fill, 'status': 'READY', 'rows': rows, 'total': len(rows),
                'covered': sum(r['position_2d'] is not None for r in rows),
                'failed': snapshot.get('failed', 0),
                'progress': getattr(self, 'position_progress', {}).get(kind),
                'source': '东方财富主力资金估算',
                'formula': '增仓占比=主力净额÷成交额×100%；主力为超大单与大单合计。多日为各日净额之和÷成交额之和，不是真实机构持仓。',
                'list_fetched_at': listing.get('fetched_at'),
                'stale': bool(listing.get('stale') or fill.get('stale'))}

    def fill_position_history(self, kind, manual=False):
        from backend.boards import stamp
        listing = self.store.get('board_cache', 'list:' + kind, False) or {}
        boards = listing.get('rows', [])
        old = self.store.get('board_cache', 'position-snapshot:' + kind, False) or {}
        saved = {r['code']: r for r in old.get('rows', [])}
        calendar = set(old.get('calendar', []))
        progress = dict(completed=0, total=len(boards), failed=0)
        self.position_progress = getattr(self, 'position_progress', {})
        self.position_progress[kind] = progress
        deadline, capped = time.monotonic() + 600, threading.Event()

        def load(board):
            if self.closed or capped.is_set() or time.monotonic() >= deadline or not self.terminal.network_enabled or not (manual or self.terminal.config()['enabled']):
                raise ValueError('history filling stopped')
            with self.history_slots:
                provider = self.factory()
                try:
                    key = 'funds:' + board['code']
                    flows = self.store.get('board_cache', key, False)
                    if not flows or (datetime.now(timezone.utc) - datetime.fromisoformat(flows['fetched_at'].replace('Z', '+00:00'))).total_seconds() >= 3600:
                        flows = dict(id=key, fetched_at=stamp(), **provider.chart(board['code'], 'funds'))
                        with self.store.lock, self.store.db:
                            self.store.put('board_cache', flows)
                        time.sleep(0.12)
                    bars = self.store.get('board_cache', 'rotation-history:' + board['code'], False) or {}
                    current = self.store.get('board_cache', 'daily:' + board['code'], False) or {}
                    if current.get('fetched_at', '') > bars.get('fetched_at', ''):
                        bars = current
                    flow_days = [f['time'] for f in flows.get('flows', [])]
                    bar_days = {b['time'] for b in bars.get('bars', [])}
                    if len(set(flow_days[-3:]) & bar_days) < min(3, len(flow_days)):
                        bars = dict(id='rotation-history:' + board['code'], fetched_at=stamp(), **provider.chart(board['code'], 'daily', limit=30))
                        with self.store.lock, self.store.db:
                            self.store.put('board_cache', bars)
                    by_day = {f['time']: f for f in flows.get('flows', [])}
                    days = [dict(time=b['time'], amount=b.get('amount'), net_inflow=by_day.get(b['time'], {}).get('net_inflow')) for b in bars.get('bars', [])[-6:]]
                    if not days:
                        raise ValueError('empty position history')
                    return dict(code=board['code'], days=days, fetched_at=stamp()), [b['time'] for b in bars.get('bars', [])]
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (429, 514):
                        capped.set()
                    raise
                finally:
                    provider.close()

        def persist():
            value = dict(id='position-snapshot:' + kind, fetched_at=stamp(), rows=list(saved.values()), calendar=sorted(calendar)[-30:], **progress)
            with self.store.lock, self.store.db:
                self.store.put('board_cache', value)

        # 每次最多四个已提交任务；不向线程池一次排入上千次上游请求。
        iterator = iter(boards)
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='position-history') as pool:
            pending = {pool.submit(load, b) for b in list(next(iterator, None) for _ in range(min(4, len(boards)))) if b}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for job in done:
                    try:
                        row, dates = job.result()
                        saved[row['code']] = row
                        calendar.update(dates)
                    except Exception:
                        progress['failed'] += 1
                    progress['completed'] += 1
                    if not self.closed and not capped.is_set() and time.monotonic() < deadline and self.terminal.network_enabled and (manual or self.terminal.config()['enabled']):
                        board = next(iterator, None)
                        if board:
                            pending.add(pool.submit(load, board))
                if progress['completed'] % 8 == 0 or not pending:
                    persist()
        if not saved:
            raise ValueError('position history unavailable')
        return dict(total=len(boards), completed=progress['completed'], failed=progress['failed'], capped=capped.is_set(), source='东方财富资金历史与未复权日K')
