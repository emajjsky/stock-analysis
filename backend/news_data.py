"""首页资讯只读缓存，与研究证据、Agent及交易隔离。"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from backend.providers import CHINA_TZ, ProviderError, normalize_security_id
from backend.research_provider import ANNOUNCEMENT_URL, _text, _publication

FLASH_URL = 'https://zhibo.sina.com.cn/api/zhibo/feed'


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def security(code, name, exchange=None):
    try:
        sid, _ = normalize_security_id((exchange + '.' if exchange else '') + str(code))
        return dict(id='LIVE.' + sid, code=sid[3:], name=_text(name, 60) or sid[3:])
    except ProviderError:
        return None


def safe_article_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
        if parsed.scheme == 'https' and parsed.hostname in {'finance.sina.com.cn', 'data.eastmoney.com'} and not parsed.username and not parsed.password and parsed.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


class NewsProvider:
    def __init__(self, client=None):
        self.owns_client = client is None
        self.client = client or httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})

    def close(self):
        if self.owns_client:
            self.client.close()

    def get(self, url, params):
        try:
            response = self.client.get(url, params=params, headers={'Referer':
                'https://data.eastmoney.com/' if url == ANNOUNCEMENT_URL else 'https://finance.sina.com.cn/'})
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ValueError('oversized response')
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('invalid response')
            return payload, stamp(), hashlib.sha256(response.content).hexdigest()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError('NEWS_UNAVAILABLE', '资讯来源暂不可用，已保留上次内容') from exc

    def market(self):
        data, fetched, digest = self.get(FLASH_URL, dict(zhibo_id=152, tag_id=0, page=1, page_size=100))
        result = data.get('result', {})
        if result.get('status', {}).get('code') != 0:
            raise ProviderError('NEWS_INVALID', '快讯来源返回异常状态')
        rows = result.get('data', {}).get('feed', {}).get('list')
        if not isinstance(rows, list):
            raise ProviderError('NEWS_INVALID', '快讯来源格式发生变化')
        items = {}
        for row in rows[:100]:
            if not isinstance(row, dict) or not str(row.get('id', '')).isdigit():
                raise ProviderError('NEWS_INVALID', '快讯编号无效')
            body = _text(row.get('rich_text'), 8000)
            try:
                published = datetime.strptime(row['create_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CHINA_TZ).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                ext = json.loads(row.get('ext') or '{}')
            except (ValueError, TypeError, KeyError) as exc:
                raise ProviderError('NEWS_INVALID', '快讯时间或关联字段无效') from exc
            if not body or not isinstance(ext, dict):
                raise ProviderError('NEWS_INVALID', '快讯内容无效')
            stocks = []
            for item in ext.get('stocks', []) or []:
                symbol = str(item.get('symbol', '')) if isinstance(item, dict) else ''
                if re.fullmatch(r'(sh|sz)\d{6}', symbol):
                    stock = security(symbol[2:], item.get('key'), symbol[:2].upper())
                    if stock and stock['id'] not in {s['id'] for s in stocks}:
                        stocks.append(stock)
            title_match = re.match(r'^【([^】]+)】', body)
            title = title_match[1] if title_match else re.split(r'[。！？]', body, maxsplit=1)[0][:120]
            key = 'sina:' + str(row['id'])
            items[key] = dict(id=key, kind='news', title=title, summary=body, published_at=published,
                publication_precision='TIME', source='新浪财经', url=safe_article_url(ext.get('docurl')),
                securities=stocks, fetched_at=fetched, raw_hash=digest)
        if not items:
            raise ProviderError('NEWS_EMPTY', '快讯来源暂未返回内容')
        return sorted(items.values(), key=lambda x: (x['published_at'], x['id']), reverse=True)

    def announcements(self, ids=None):
        params = dict(sr=-1, page_size=50, page_index=1, ann_type='A', client_source='web')
        allowed = set(ids or [])
        if allowed:
            params['stock_list'] = ','.join(sorted(sid[-6:] for sid in allowed))
        data, fetched, digest = self.get(ANNOUNCEMENT_URL, params)
        rows = data.get('data', {}).get('list')
        if not isinstance(rows, list) or data.get('success') in (False, 0):
            raise ProviderError('NEWS_INVALID', '公告来源格式发生变化')
        items = {}
        for row in rows[:50]:
            if not isinstance(row, dict):
                raise ProviderError('NEWS_INVALID', '公告记录无效')
            art = str(row.get('art_code', ''))
            title = _text(row.get('title_ch') or row.get('title'), 600)
            if not re.fullmatch(r'AN\d{1,32}', art) or not title:
                raise ProviderError('NEWS_INVALID', '公告标题或编号无效')
            stocks = []
            for item in row.get('codes', []):
                exchange = {'1': 'SH', '0': 'SZ'}.get(str(item.get('market_code')))
                stock = security(item.get('stock_code'), item.get('short_name'), exchange) if exchange else None
                if stock and (not allowed or stock['id'] in allowed):
                    stocks.append(stock)
            if not stocks:
                continue
            published, precision = _publication(row.get('notice_date'))
            if not published:
                raise ProviderError('NEWS_INVALID', '公告缺少披露日期')
            key = 'eastmoney:' + art
            items[key] = dict(id=key, kind='announcement', title=title,
                summary='公告目录标题，点击原文查看完整披露内容。', published_at=published,
                publication_precision=precision, source='东方财富公告目录',
                url=f'https://data.eastmoney.com/notices/detail/{stocks[0]["code"]}/{art}.html',
                securities=stocks, fetched_at=fetched, raw_hash=digest)
        return sorted(items.values(), key=lambda x: (x['published_at'], x['id']), reverse=True)


class NewsData:
    def __init__(self, store, terminal):
        self.store, self.terminal = store, terminal
        self.provider_factory = NewsProvider
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.wakeup = threading.Event()
        self.thread = None
        self.active = False
        self.selected = None
        self.forced = set()
        self.next_poll = {}
        self.errors = {}
        self.running = set()

    def watched_ids(self):
        return sorted({row['security_id'] for row in self.store.all('watch')
                       if row['security_id'].startswith('LIVE.')})[:20]

    def provider(self):
        saved = self.store.get('news_feed', 'market', False)
        with self.lock:
            error = self.errors.get('market')
        return dict(id='news', name='市场快讯与公告目录', status='ERROR' if error else 'SYNCED' if saved else 'AVAILABLE',
            capabilities=['新浪财经公开快讯', '东方财富公告目录', '自选与个股关联筛选'],
            source='新浪财经 / 东方财富公开接口与本地缓存', connected=bool(saved),
            last_updated_at=saved['updated_at'] if saved else None, error=error,
            limitations=['公开源有限轮询，非持续推送', '关联范围以来源标注和最近目录为限，不代表完整历史',
                          '未抓取公告正文；首页资讯独立于Agent研究证据，不自动执行交易'])

    def keys(self):
        ids = self.watched_ids()
        watch_key = 'watch:' + hashlib.sha256(','.join(ids).encode()).hexdigest()[:16]
        return ids, watch_key

    def request(self, security_id=None, force=False):
        if security_id:
            canonical, _ = normalize_security_id(security_id.removeprefix('LIVE.'))
            if security_id != 'LIVE.' + canonical:
                raise ProviderError('INVALID_SECURITY', '请选择真实沪深A股')
        with self.lock:
            self.active = True
            self.selected = security_id
            if force:
                # 显式重试也有30秒节流；后台普通刷新不绕过暂停。
                _, watch_key = self.keys()
                for key in ('market', 'announcements', watch_key, *([security_id] if security_id else [])):
                    if time.monotonic() >= self.next_poll.get('retry:' + key, 0):
                        self.forced.add(key)
                        self.next_poll['retry:' + key] = time.monotonic() + 30
        self.wakeup.set()

    def feed(self, tab, security_id=None):
        self.request(security_id)
        ids, watch_key = self.keys()
        keys = [security_id or 'announcements'] if tab == 'announcements' else ['market', security_id or watch_key] if tab == 'watch' else ['market']
        selected = {security_id} if security_id else set(ids) if tab == 'watch' else None
        items, updated = {}, []
        for key in keys:
            cached = self.store.get('news_feed', key, False)
            if cached:
                updated.append(cached['updated_at'])
                for item in cached['items']:
                    if selected is None or selected.intersection(s['id'] for s in item['securities']):
                        items[item['id']] = item
        with self.lock:
            errors = [self.errors[key] for key in keys if key in self.errors]
            refreshing = any(key in self.running for key in keys)
        stamp_value = min(updated) if updated else None
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp_value.replace('Z', '+00:00'))).total_seconds() if stamp_value else None
        waiting = not updated and self.terminal.config()['enabled'] and bool(self.thread and self.thread.is_alive())
        return dict(items=sorted(items.values(), key=lambda x: (x['published_at'], x['id']), reverse=True)[:150],
                    updated_at=stamp_value, refreshing=refreshing, enabled=self.terminal.config()['enabled'],
                    error='；'.join(dict.fromkeys(errors)) or None, stale=age is None or age > 600,
                    watch_count=len(ids), watch_limit=20, scope=security_id,
                    status='ERROR' if errors else 'READY' if updated else 'LOADING' if refreshing or waiting else 'EMPTY')

    def refresh_once(self):
        with self.lock:
            if not self.active:
                return
            ids, watch_key = self.keys()
            jobs = [('market', None), ('announcements', None)]
            if ids:
                jobs.append((watch_key, ids))
            if self.selected and self.selected not in ids:
                jobs.append((self.selected, [self.selected]))
            elif self.selected:
                # 个股公告需要独立完整目录，不能用自选批量页冒充。
                jobs.append((self.selected, [self.selected]))
        provider = None
        try:
            for key, symbols in jobs:
                if self.stopping.is_set():
                    break
                with self.lock:
                    forced = key in self.forced
                    if key in self.running or (not forced and (not self.terminal.config()['enabled'] or time.monotonic() < self.next_poll.get(key, 0))):
                        continue
                    self.forced.discard(key)
                    self.running.add(key)
                try:
                    provider = provider or self.provider_factory()
                    rows = provider.market() if key == 'market' else provider.announcements(symbols)
                    with self.store.lock, self.store.db:
                        self.store.put('news_feed', dict(id=key, items=rows, updated_at=stamp()))
                        saved = sorted(self.store.all('news_feed'), key=lambda x: x['updated_at'], reverse=True)
                        for old in saved[30:]:
                            if old['id'] not in {'market', 'announcements', watch_key, self.selected}:
                                self.store.db.execute("DELETE FROM documents WHERE kind='news_feed' AND id=?", (old['id'],))
                    with self.lock:
                        self.errors.pop(key, None)
                        self.next_poll[key] = time.monotonic() + (60 if key == 'market' else 300)
                except Exception:
                    with self.lock:
                        self.errors[key] = ('市场快讯' if key == 'market' else '公司公告') + '更新失败，稍后重试'
                        self.next_poll[key] = time.monotonic() + 300
                finally:
                    with self.lock:
                        self.running.discard(key)
        finally:
            if provider:
                provider.close()

    def start(self):
        if not self.terminal.network_enabled or self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name='terminal-news-cache', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.is_set():
            self.refresh_once()
            self.wakeup.wait(2)
            self.wakeup.clear()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=2)
