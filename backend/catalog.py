"""独立证券目录：全量验证后原子替换，搜索不读取数千只股票历史。"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from pypinyin import Style, lazy_pinyin

from backend.providers import ProviderError, normalize_security_id

SOURCE = '东方财富公开沪深证券清单'
URL = 'https://push2.eastmoney.com/api/qt/clist/get'


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def search_keys(name):
    # 词组字典固定在锁定的 pypinyin 版本内；常见多音字品牌确定性修正。
    overrides = {'重庆': ('chongqing', 'cq'), '长安': ('changan', 'ca'),
                 '长江': ('changjiang', 'cj'), '长城': ('changcheng', 'cc')}
    full = ''.join(lazy_pinyin(name, errors='default')).lower()
    short = ''.join(lazy_pinyin(name, style=Style.FIRST_LETTER, errors='default')).lower()
    for prefix, (spelling, initials) in overrides.items():
        if name.startswith(prefix):
            full = spelling + ''.join(lazy_pinyin(name[len(prefix):])).lower()
            short = initials + ''.join(lazy_pinyin(name[len(prefix):], style=Style.FIRST_LETTER)).lower()
    return re.sub(r'[^a-z0-9]', '', full), re.sub(r'[^a-z0-9]', '', short)


class CatalogProvider:
    def __init__(self):
        self.client = httpx.Client(timeout=12, follow_redirects=False, trust_env=False)
        self.source = SOURCE
        self.metadata = {}

    def close(self):
        self.client.close()

    def _get(self, url, params):
        for attempt in range(3):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                time.sleep(0.4 * (attempt + 1))

    def download(self):
        try:
            self.source = '新浪财经公开沪深证券清单'
            return self._sina()
        except ProviderError:
            self.source = SOURCE
            return self._eastmoney()

    def _sina(self):
        base = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'
        try:
            response = self._get(base + 'getHQNodeStockCount', {'node':'hs_a'})
            total = int(response.json())
            if not 4000 <= total <= 10000:
                raise ValueError('invalid total')
            def page(number):
                response = self._get(base + 'getHQNodeData', dict(page=number,
                    num=100, sort='symbol', asc=1, node='hs_a'))
                data = response.json()
                if not isinstance(data, list) or not data:
                    raise ValueError('invalid page')
                return data
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='catalog-page') as pool:
                batches = list(pool.map(page, range(1, (total + 99)//100 + 1)))
            raw = [row for batch in batches for row in batch]
            symbols = [row['symbol'] for row in raw]
            if len(raw) != total or len(set(symbols)) != total:
                raise ValueError('incomplete catalog')
            if int(self._get(base + 'getHQNodeStockCount', {'node':'hs_a'}).json()) != total:
                raise ValueError('catalog changed during download')
            rows = [dict(code=row['code'], name=row['name'], market=1 if row['symbol'].startswith('sh') else 0)
                    for row in raw if row['symbol'].startswith(('sh', 'sz'))]
            self.metadata = dict(raw_count=total, expected_raw_count=total, excluded_before_normalize=total-len(rows))
            return rows
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError('CATALOG_UNAVAILABLE', '证券目录下载失败，已保留本地目录') from exc

    def _eastmoney(self):
        rows, total, seen = [], None, set()
        for page in range(1, 101):
            try:
                response = self._get(URL, dict(pn=page, pz=100, np=1, po=1,
                    fltt=2, invt=2, fid='f12', fs='m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
                    fields='f12,f14,f13'))
                payload = response.json()['data']
                target, batch = int(payload['total']), payload['diff']
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise ProviderError('CATALOG_UNAVAILABLE', '证券目录下载失败，已保留本地目录') from exc
            if total is None:
                total = target
            if total != target or not isinstance(batch, list) or not batch:
                raise ProviderError('CATALOG_INCOMPLETE', '证券目录分页发生变化，请稍后重试')
            for item in batch:
                identity = (str(item.get('f13')), str(item.get('f12')))
                if identity in seen:
                    raise ProviderError('CATALOG_INCOMPLETE', '证券目录分页重复，未覆盖本地数据')
                seen.add(identity)
                rows.append(item)
            if len(rows) >= total:
                break
        if not total or len(rows) != total or total < 4000:
            raise ProviderError('CATALOG_INCOMPLETE', '证券目录不完整，未覆盖本地数据')
        self.metadata = dict(raw_count=total, expected_raw_count=total, excluded_before_normalize=0)
        return rows


class Catalog:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.provider_factory = CatalogProvider
        self.running = False
        with store.lock, store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS security_catalog(id TEXT PRIMARY KEY,code TEXT NOT NULL,name TEXT NOT NULL,pinyin TEXT NOT NULL,initials TEXT NOT NULL,payload TEXT NOT NULL)')
            store.db.execute('CREATE INDEX IF NOT EXISTS catalog_code ON security_catalog(code)')

    def status(self):
        state = self.store.get('terminal', 'catalog', False) or {}
        with self.store.lock:
            count = self.store.db.execute('SELECT count(*) FROM security_catalog').fetchone()[0]
        return dict(count=count, source=state.get('source'), updated_at=state.get('updated_at'),
                    status='RUNNING' if self.running else 'ERROR' if state.get('error') else 'READY' if count else 'EMPTY',
                    error=state.get('error'))

    def import_rows(self, rows, source=SOURCE, *, minimum=4000, metadata=None):
        records, seen, excluded = [], set(), 0
        metadata = metadata or {}
        updated = metadata.get('fetched_at') or stamp()
        for row in rows:
            code, name = str(row.get('f12', row.get('code', ''))), row.get('f14', row.get('name', ''))
            market = row.get('f13', row.get('market'))
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ProviderError('CATALOG_INVALID', '证券目录名称无效')
            try:
                canonical, _ = normalize_security_id(('SH.' if str(market) == '1' else 'SZ.') + code)
            except ProviderError:
                excluded += 1
                continue
            sid = 'LIVE.' + canonical
            if sid in seen:
                raise ProviderError('CATALOG_INVALID', '证券目录身份重复')
            seen.add(sid)
            pinyin, initials = search_keys(name)
            obj = dict(id=sid, code=code, name=name.strip(), exchange='SSE' if canonical.startswith('SH.') else 'SZSE',
                       sector='未接入行业资料', status='CATALOG', dataset_id='tencent-unadjusted-v1',
                       pinyin=pinyin, initials=initials, source=source, updated_at=updated, quote=None)
            records.append((sid, code, obj['name'], pinyin, initials, json.dumps(obj, ensure_ascii=False)))
        if len(records) < minimum:
            raise ProviderError('CATALOG_INCOMPLETE', '证券目录有效记录不足，保留已有目录')
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM security_catalog')
            self.store.db.executemany('INSERT INTO security_catalog VALUES(?,?,?,?,?,?)', records)
            # 只更新已物化的资料，避免全目录进入算法证券池。
            materialized = {x['id']: x for x in self.store.all('security') if x['id'].startswith('LIVE.')}
            for sid, _, _, _, _, payload in records:
                if sid in materialized:
                    incoming = json.loads(payload)
                    saved = materialized[sid]
                    saved.update({key:incoming[key] for key in ('name','pinyin','initials','source','updated_at')})
                    self.store.put('security', saved)
            self.store.put('terminal', dict(id='catalog', source=source, updated_at=updated, error=None,
                excluded_count=excluded + metadata.get('excluded_before_normalize', metadata.get('excluded_count', 0)),
                downloaded_count=metadata.get('raw_count', len(rows)),
                expected_raw_count=metadata.get('expected_raw_count', len(rows))))
        return self.status()

    def sync(self):
        if not self.lock.acquire(blocking=False):
            return self.status()
        self.running = True
        provider = None
        try:
            provider = self.provider_factory()
            rows = provider.download()
            self.import_rows(rows, getattr(provider, 'source', SOURCE), metadata=getattr(provider, 'metadata', {}))
        except Exception as exc:
            state = self.store.get('terminal', 'catalog', False) or dict(id='catalog')
            state['error'] = exc.message if isinstance(exc, ProviderError) else '证券目录更新失败，已保留缓存'
            with self.store.lock, self.store.db:
                self.store.put('terminal', state)
        finally:
            if provider:
                provider.close()
            self.running = False
            self.lock.release()
        return self.status()

    def find(self, key):
        with self.store.lock:
            row = self.store.db.execute('SELECT payload FROM security_catalog WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def search(self, q='', limit=50, offset=0):
        with self.store.lock:
            if not q:
                rows = self.store.db.execute('SELECT payload FROM security_catalog ORDER BY code,id LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            else:
                term = re.sub(r'\s+', '', q.strip().lower())
                # Escape LIKE wildcards supplied by users; search remains a literal match.
                pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                rows = self.store.db.execute("SELECT payload FROM security_catalog WHERE lower(name) LIKE ? ESCAPE '\\' OR code LIKE ? ESCAPE '\\' OR pinyin LIKE ? ESCAPE '\\' OR initials LIKE ? ESCAPE '\\' ORDER BY CASE WHEN code=? OR lower(name)=? OR pinyin=? OR initials=? THEN 0 ELSE 1 END,code,id LIMIT ? OFFSET ?", (pattern, pattern, pattern, pattern, term, term, term, term, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]
