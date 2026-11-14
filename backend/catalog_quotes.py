"""全目录持久报价缓存；与最近访问、研究及算法证券池隔离。"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone

from backend.providers import ProviderError


def public_quote(snapshot):
    """目录与自选使用同一快照映射，不以历史源时间冒充实时。"""
    if not snapshot:
        return None
    if snapshot.get('quote_schema_version', 0) < 2:
        snapshot = {**snapshot, 'pe_ttm': snapshot.get('pe_dynamic'), 'pe_dynamic': None}
    source_time = snapshot.get('source_time')
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(source_time.replace('Z', '+00:00'))).total_seconds()
    except (ValueError, TypeError, AttributeError):
        age = None
    return {**snapshot, 'as_of': source_time, 'mode': 'LIVE', 'is_realtime': False,
            'stale': age is None or age > 120 or age < -60,
            'dataset_id': 'tencent-unadjusted-v1', 'source': '腾讯财经公开报价 / 本地快照'}


def save_quote(store, quote):
    sid = 'LIVE.' + quote['security_id'].removeprefix('LIVE.')
    with store.lock, store.db:
        old = store.get('market_snapshot', sid, False)
        if old and (old.get('source_time') or '') > (quote.get('source_time') or ''):
            return False
        store.put('market_snapshot', {**quote, 'id': sid, 'security_id': sid, 'provider_id': 'tencent'})
    return True


class CatalogQuotes:
    def __init__(self, store, market_data, *, enabled, interval, market_open):
        self.store, self.market_data = store, market_data
        self.enabled, self.interval, self.market_open = enabled, interval, market_open
        self.thread = None
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.visible = {}
        self.retry_at = {}
        self.next_attempt = 0.0
        self.failures = 0
        self.running = False
        self.error = None

    def request(self, rows):
        if not self.enabled():
            return
        with self.lock:
            now = time.monotonic()
            self.visible = {k: v for k, v in self.visible.items() if now - v < 120}
            for row in rows:
                if row['id'].startswith('LIVE.'):
                    self.visible[row['id']] = now
            self.visible = dict(sorted(self.visible.items(), key=lambda x: x[1], reverse=True)[:300])
            if not self.failures:
                self.next_attempt = 0.0

    def status(self):
        with self.store.lock:
            row = self.store.db.execute("""SELECT count(*) AS total, count(d.id) AS covered,
                max(json_extract(d.payload,'$.source_time')) AS source_time
                FROM security_catalog c LEFT JOIN documents d ON d.kind='market_snapshot' AND d.id=c.id""").fetchone()
        return dict(enabled=self.enabled(), running=self.running, total=row['total'], covered=row['covered'],
                    source_time=row['source_time'], error=self.error)

    def _batch(self):
        now = time.monotonic()
        wall = datetime.now(timezone.utc).timestamp()
        base = max(self.interval(), 0 if self.market_open() else 300)
        with self.lock:
            visible = {k for k, t in self.visible.items() if now - t < 120}
            self.retry_at = {k: t for k, t in self.retry_at.items() if t > now}
            retries = dict(self.retry_at)
        with self.store.lock:
            rows = self.store.db.execute("""SELECT c.id, json_extract(d.payload,'$.fetched_at') AS fetched_at
                FROM security_catalog c LEFT JOIN documents d ON d.kind='market_snapshot' AND d.id=c.id""").fetchall()
        due = []
        for row in rows:
            sid = row['id']
            if sid in retries:
                continue
            try:
                fetched = datetime.fromisoformat(row['fetched_at'].replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError, AttributeError):
                fetched = 0
            ttl = base if sid in visible else max(60, base)
            if wall - fetched >= ttl or fetched > wall + 60:
                due.append((sid not in visible, fetched, sid))
        return [r[2] for r in sorted(due)[:50]]

    def refresh_once(self):
        if not self.enabled() or self.stopping.is_set() or time.monotonic() < self.next_attempt:
            return 0
        if not self.run_lock.acquire(blocking=False):
            return 0
        client = None
        batch = []
        try:
            batch = self._batch()
            if not batch:
                self.next_attempt = time.monotonic() + 3
                return 0
            if not self.enabled() or self.stopping.is_set():
                return 0
            self.running = True
            client = self.market_data.provider_factory()
            quotes = client.quotes([sid.removeprefix('LIVE.') for sid in batch])
            # 只接受请求身份，遗漏单只退避，避免坏证券卡住整批。
            returned = set()
            for quote in quotes:
                sid = 'LIVE.' + quote['security_id'].removeprefix('LIVE.')
                if sid in batch:
                    save_quote(self.store, quote)
                    returned.add(sid)
            with self.lock:
                for sid in set(batch) - returned:
                    self.retry_at[sid] = time.monotonic() + 300
            self.failures = 0
            self.error = None if len(returned) == len(batch) else '部分证券暂无有效报价，已保留缓存'
            return len(returned)
        except Exception as exc:
            # 严格解析器会指出无效证券；隔离这一只，剩余证券下批继续。
            missing = re.search(r'(SH|SZ)\.\d{6}', exc.message) if isinstance(exc, ProviderError) else None
            bad_id = 'LIVE.' + missing.group(0) if missing else None
            if isinstance(exc, ProviderError) and exc.code in {'QUOTE_MISSING', 'INVALID_RESPONSE'} and bad_id in batch:
                with self.lock:
                    self.retry_at[bad_id] = time.monotonic() + 900
                self.error = '部分证券暂无有效报价，已保留缓存'
            else:
                self.failures += 1
                self.next_attempt = time.monotonic() + min(900, 30 * 2 ** min(self.failures - 1, 5))
                self.error = '目录行情更新失败，已保留缓存，后台重试中'
            return 0
        finally:
            try:
                if client:
                    client.close()
            finally:
                self.running = False
                self.run_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name='catalog-quote-cache', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.is_set():
            self.refresh_once()
            self.stopping.wait(0.5)

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=12)
