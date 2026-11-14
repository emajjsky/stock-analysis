"""外部行情入库边界：保存快照和完整日线，绝不连接交易服务。"""
from __future__ import annotations

import threading
import uuid
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from backend.providers import ProviderError, TencentProvider, normalize_security_id
from backend.catalog_quotes import save_quote


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def canonical(value):
    return normalize_security_id(str(value).removeprefix('LIVE.'))[0]


class MarketData:
    limitations = [
        '公开行情接口可能延迟或变更；无实时性或可用性保证，不是交易所授权行情服务',
        '支持手动同步；终端后台按刷新设置更新自选和最近访问，行情刷新与算法监测独立',
        '日线盘中排除当日，16点后补齐收盘数据；未复权历史不包含企业行为处理',
        '历史接口缺少成交额时保留未知；不会用收盘价乘成交量伪造成交额',
        '不自动加入自选、不自动运行选股、不进行模拟或真实交易',
        '本行情源不含公司资料；公司/财务摘要及公告目录另行手动同步，综合新闻全文未接',
    ]

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.provider_factory = TencentProvider

    def runs(self):
        return list(reversed(self.store.all('market_sync_run')))[0:30]

    def provider(self):
        runs = self.runs()
        latest = runs[0] if runs else None
        saved = [x for x in self.store.all('market_snapshot') if x.get('provider_id') == 'tencent']
        return dict(id='tencent', name='腾讯财经公开行情', status=(
            'SYNCED' if latest and latest['status'] == 'SUCCEEDED' else
            'PARTIAL' if latest and latest['status'] == 'PARTIAL' else
            'ERROR' if latest else 'AVAILABLE'),
            data_mode='LIVE', connected=bool(saved),
            source='腾讯财经 HTTPS 公开接口 / 本地缓存',
            last_updated_at=latest['finished_at'] if latest else None,
            latest_data_at=max((x['source_time'] for x in saved if x.get('source_time')), default=None),
            error='；'.join(latest['errors']) if latest and latest['errors'] else None,
            warning='快照延迟未知；休市和缓存不能标为实时推送',
            capabilities=['沪深A股报价快照与有限后台轮询', '分页补齐来源可提供的历史日线', '独立缓存与来源追踪'],
            limitations=self.limitations)

    def sync(self, security_ids, sync_daily=False):
        canonical_ids = list(dict.fromkeys(canonical(x) for x in security_ids))
        if sync_daily and len(canonical_ids) > 5:
            raise ProviderError('TOO_MANY_HISTORY_SYMBOLS', '一次日线同步最多5只证券，请分批执行')
        if not self.lock.acquire(blocking=False):
            raise ProviderError('SYNC_BUSY', '已有行情同步任务运行中，请等待结束再重试')
        client = None
        run = dict(id=uuid.uuid4().hex, provider_id='tencent', status='RUNNING',
            started_at=stamp(), finished_at=None, quotes_updated=0, daily_rows_saved=0,
            securities_processed=0, errors=[], limitations=self.limitations,
            requested_security_ids=canonical_ids, sync_daily=sync_daily)
        try:
            client = self.provider_factory()
            try:
                quotes = client.quotes(canonical_ids)
            except ProviderError as exc:
                quotes = []
                run['errors'].append(exc.message)
            for quote in quotes:
                sid = 'LIVE.' + quote['security_id']
                with self.store.lock, self.store.db:
                    self.store.put('security', dict(id=sid, code=quote['code'], name=quote['name'] or quote['code'],
                        exchange='SSE' if quote['security_id'].startswith('SH.') else 'SZSE',
                        sector='未接入行业资料', status='LIVE_UNVERIFIED', dataset_id='tencent-unadjusted-v1'))
                    save_quote(self.store, quote)
                run['quotes_updated'] += 1
                run['securities_processed'] += 1
            if sync_daily:
                # 每证券事务；一个证券的历史冲突不清除其他证券已保存的快照。
                for canonical_id in canonical_ids:
                    sid = 'LIVE.' + canonical_id
                    if not self.store.get('security', sid, False):
                        run['errors'].append(canonical_id + '：未取得有效证券快照，未保存日线')
                        continue
                    try:
                        complete = self.store.get('market_history', sid, False)
                        rows = (client.full_history(canonical_id) if not complete and hasattr(client, 'full_history')
                                else client.daily(canonical_id, count=2000))
                        if not rows:
                            raise ProviderError('NO_COMPLETE_BARS', '上游未提供有效完整日线')
                        added = 0
                        enriched = 0
                        with self.store.lock, self.store.db:
                            for row in rows:
                                old = self.store.db.execute(
                                    'SELECT * FROM provider_bars WHERE provider_id=? AND security_id=? AND time=?',
                                    ('tencent', sid, row['time'])).fetchone()
                                if old:
                                    fields = ('open', 'high', 'low', 'close', 'volume')
                                    if any((old[k] is None) != (row[k] is None) or (old[k] is not None and Decimal(str(old[k])) != Decimal(str(row[k]))) for k in fields):
                                        raise ProviderError('HISTORY_CONFLICT', '已保存历史存在数值修订，保留原数据，需版本化处理：' + row['time'])
                                    if old['amount'] is not None and row.get('amount') is not None and Decimal(str(old['amount'])) != Decimal(str(row['amount'])):
                                        raise ProviderError('HISTORY_CONFLICT', '已保存历史成交额存在数值修订，保留原数据，需版本化处理：' + row['time'])
                                    if old['amount'] is None and row.get('amount') is not None:
                                        self.store.db.execute(
                                            'UPDATE provider_bars SET amount=?,source=? WHERE provider_id=? AND security_id=? AND time=?',
                                            (row['amount'], row.get('source', '东方财富公开日线'), 'tencent', sid, row['time']))
                                        enriched += 1
                                    continue
                                self.store.db.execute('INSERT INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                                    'tencent', sid, row['time'], row['open'], row['high'], row['low'], row['close'],
                                    row['volume'], row['amount'], row.get('source', '腾讯财经公开日线 / 未复权'), row['source_time'],
                                    row['fetched_at'], row['raw_hash'], row['adjustment']))
                                added += 1
                            self.store.put('market_history', dict(id=sid, history_complete=True, checked_at=stamp()))
                        run['daily_rows_saved'] += added + enriched
                    except ProviderError as exc:
                        run['errors'].append(canonical_id + '：' + exc.message)
            run['status'] = ('PARTIAL' if run['quotes_updated'] else 'FAILED') if run['errors'] else 'SUCCEEDED'
        except Exception:
            run['status'] = 'PARTIAL' if run['quotes_updated'] else 'FAILED'
            run['errors'].append('外部行情处理失败，保留已有数据；请检查来源状态后重试')
        finally:
            try:
                if client:
                    client.close()
                run['finished_at'] = stamp()
                with self.store.lock, self.store.db:
                    self.store.put('market_sync_run', run)
                    for old in self.store.all('market_sync_run')[:-30]:
                        self.store.db.execute("DELETE FROM documents WHERE kind='market_sync_run' AND id=?", (old['id'],))
            finally:
                self.lock.release()
        return run

    def sync_adjusted_history(self, security_id, adjustment):
        if adjustment not in {'qfq', 'hfq'}:
            raise ProviderError('INVALID_ADJUSTMENT', '复权类型仅支持前复权或后复权')
        sid = 'LIVE.' + canonical(security_id)
        if not self.store.get('security', sid, False):
            raise ProviderError('INVALID_SECURITY', '请先从证券目录打开真实行情证券')
        if not self.lock.acquire(blocking=False):
            raise ProviderError('SYNC_BUSY', '已有行情同步任务运行中，请稍后重试')
        client = None
        try:
            client = self.provider_factory()
            rows = client.full_history(sid.removeprefix('LIVE.'), adjustment=adjustment)
            if not rows:
                raise ProviderError('NO_COMPLETE_BARS', '来源没有返回该复权口径的历史日线')
            received = stamp()
            with self.store.lock, self.store.db:
                existing = [dict(row) for row in self.store.db.execute(
                    'SELECT * FROM provider_adjusted_bars WHERE provider_id=? AND security_id=? AND adjustment=? ORDER BY time',
                    ('tencent', sid, adjustment.upper())).fetchall()]
                previous = {row['time']:row for row in existing}
                fields = ('open', 'high', 'low', 'close', 'volume', 'amount')
                def equivalent(a, b):
                    return all((a[k] is None and b[k] is None) or a[k] is not None and b[k] is not None and Decimal(str(a[k]))==Decimal(str(b[k])) for k in fields)
                revised = any(row['time'] in previous and not equivalent(previous[row['time']], row) for row in rows)
                if revised:
                    if not set(previous).issubset({r['time'] for r in rows}):
                        raise ProviderError('INCOMPLETE_REVISION', '来源修订但未覆盖已有复权日期，保留旧版本')
                    revision_id = hashlib.sha256(json.dumps(existing, sort_keys=True).encode()).hexdigest()
                    self.store.put('adjusted_history_revision', dict(id=revision_id, security_id=sid,
                        adjustment=adjustment.upper(), archived_at=received,
                        metadata=self.store.get('adjusted_history', f'{sid}:{adjustment.upper()}', False), bars=existing))
                    self.store.db.execute('DELETE FROM provider_adjusted_bars WHERE provider_id=? AND security_id=? AND adjustment=?',
                        ('tencent', sid, adjustment.upper()))
                for row in rows:
                    old = self.store.db.execute(
                        'SELECT * FROM provider_adjusted_bars WHERE provider_id=? AND security_id=? AND adjustment=? AND time=?',
                        ('tencent', sid, adjustment.upper(), row['time'])).fetchone()
                    if old:
                        continue
                    self.store.db.execute('INSERT INTO provider_adjusted_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                        'tencent', sid, adjustment.upper(), row['time'], row['open'], row['high'], row['low'], row['close'],
                        row['volume'], row['amount'], row.get('source') or f"腾讯财经公开日线 / {'前复权' if adjustment == 'qfq' else '后复权'}",
                        row['source_time'], received, row['raw_hash']))
                all_rows = self.store.db.execute('SELECT MIN(time),MAX(time),COUNT(*) FROM provider_adjusted_bars WHERE provider_id=? AND security_id=? AND adjustment=?',
                    ('tencent',sid,adjustment.upper())).fetchone()
                metadata = dict(id=f'{sid}:{adjustment.upper()}', security_id=sid,
                    adjustment=adjustment.upper(), from_date=all_rows[0], to_date=all_rows[1],
                    count=all_rows[2], source=rows[-1].get('source') or '腾讯财经公开日线', received_at=received,
                    raw_hash=rows[-1]['raw_hash'])
                self.store.put('adjusted_history', metadata)
            return metadata
        finally:
            if client:
                client.close()
            self.lock.release()
