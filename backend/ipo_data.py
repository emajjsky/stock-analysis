"""新股发行/审核资料：固定来源、按页持久缓存，与算法和交易隔离。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import threading
import time

import httpx

from backend.catalog import stamp
from backend.providers import CHINA_TZ, ProviderError

URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
BOARDS = {'all', 'sh', 'sz', 'gem', 'star', 'bj'}
SECTIONS = {'apply', 'listed', 'pending', 'review', 'disclosure', 'bonds', 'news'}


def number(value, scale=1):
    if value is None or isinstance(value, bool) or str(value).strip() in {'', '-', '--', 'NULL', 'null'}:
        return None
    try:
        result = Decimal(str(value)) * Decimal(str(scale))
        return format(result, 'f') if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def day(value):
    text = str(value or '')[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').date().isoformat()
    except ValueError:
        return None


def document_url(code):
    return f'https://pdf.dfcfw.com/pdf/H2_{code}_1.pdf' if re.fullmatch(r'AN\d+', str(code or '')) else None


def security_id(secucode):
    match = re.fullmatch(r'(\d{6})\.(SH|SZ)', str(secucode or ''))
    if not match:
        return None
    code, market = match.groups()
    if not ((market == 'SH' and code.startswith('6')) or (market == 'SZ' and code.startswith(('0', '3')))):
        return None
    return f'LIVE.{market}.{code}'


def quote_time(value):
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat().replace('+00:00', 'Z') if int(value) > 946684800 else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize(row, section, today=None):
    today = today or datetime.now(CHINA_TZ).date().isoformat()
    if section == 'bonds':
        return dict(id=row['SECUCODE'], code=row['SECURITY_CODE'], name=row['SECURITY_NAME_ABBR'],
            apply_code=row.get('CORRECODE'), apply_date=day(row.get('PUBLIC_START_DATE')),
            listing_date=day(row.get('LISTING_DATE')), stock_code=row.get('CONVERT_STOCK_CODE'),
            stock_name=row.get('SECURITY_SHORT_NAME'), rating=row.get('RATING'),
            issue_price=number(row.get('ISSUE_PRICE')), issue_amount=number(row.get('ACTUAL_ISSUE_SCALE'), 100000000),
            win_rate=number(row.get('ONLINE_GENERAL_LWR')), first_profit=number(row.get('FIRST_PROFIT')),
            # 该接口没有可靠的实时行情时间，不取其CURRENT_BOND_*当实时价格。
            security_id=None, currency='CNY', source_date=day(row.get('PUBLIC_START_DATE')))
    if section in {'review', 'disclosure'}:
        return dict(id=str(row.get('ORG_CODE')) + ':' + str(row.get('REVIEW_DATE') or row.get('UPDATE_DATE')),
            code=row.get('SECURITY_CODE'), name=row.get('ORG_NAME') or row.get('DECLARE_ORG'),
            board=row.get('TRADE_MARKET') or row.get('PREDICT_LISTING_MARKET'),
            status=row.get('REVIEW_STATE') or row.get('STATE'),
            review_date=day(row.get('REVIEW_DATE')), update_date=day(row.get('UPDATE_DATE')),
            accept_date=day(row.get('ACCEPT_DATE')), notice_date=day(row.get('NOTICE_DATE')),
            listing_date=day(row.get('LISTING_DATE')), issue_shares=number(row.get('ISSUE_NUM')),
            planned_funds=number(row.get('FINANCE_AMT_UPPER')), industry=row.get('CSRC_INDUSTRY'),
            sponsor=row.get('LEAD_UNDERWRITER') or row.get('RECOMMEND_ORG'),
            region=row.get('REG_ADDRESS'), law_firm=row.get('LAW_FIRM'), accountant=row.get('ACCOUNT_FIRM'),
            document_url=document_url(row.get('INFO_CODE')), security_id=None, currency='CNY',
            source_date=day(row.get('UPDATE_DATE') or row.get('NOTICE_DATE')))
    listing = day(row.get('LISTING_DATE'))
    listed = bool(listing and listing <= today)
    issue, last = number(row.get('ISSUE_PRICE')), number(row.get('f2', row.get('LATELY_PRICE'))) if listed else None
    close, high_change = number(row.get('CLOSE_PRICE')), number(row.get('LD_HIGH_CHANG'))
    ballot_shares = number(row.get('EACHBALLOT_SHARES'))
    return dict(id=row['SECUCODE'], code=row['SECURITY_CODE'], name=row.get('SECURITY_NAME_ABBR') or row.get('SECURITY_NAME'),
        board=row.get('MARKET') or row.get('MARKET_TYPE_NEW') or row.get('TRADE_MARKET'), apply_code=row.get('APPLY_CODE'),
        apply_date=day(row.get('APPLY_DATE')), listing_date=listing,
        pay_date=day(row.get('BALLOT_PAY_DATE') or row.get('ONLINE_PAY_DATE')),
        ballot_date=day(row.get('BALLOT_NUM_DATE') or row.get('RESULT_NOTICE_DATE')),
        # ISSUE_NUM为万股，ONLINE_ISSUE_NUM和ONLINE_APPLY_UPPER为股；不统一误乘10000。
        issue_shares=number(row.get('ISSUE_NUM'), 10000), online_shares=number(row.get('ONLINE_ISSUE_NUM')),
        apply_limit=number(row.get('ONLINE_APPLY_UPPER')), issue_price=issue,
        required_cap=number(row.get('TOP_APPLY_MARKETCAP'), 10000) if not row.get('IS_BEIJING') else None,
        required_cash=number(row.get('APPLY_AMT_UPPER'), 10000) if row.get('IS_BEIJING') else None,
        issue_pe=number(row.get('AFTER_ISSUE_PE')), industry_pe=number(row.get('INDUSTRY_PE_NEW')),
        win_rate=number(row.get('ONLINE_ISSUE_LWR')), price=last,
        change_pct=number(row.get('f3', row.get('CHANGE_RATE'))) if listed else None,
        volume_lots=number(row.get('f5')) if listed else None,
        amount=number(row.get('f6')) if listed else None,
        turnover_rate=number(row.get('f8')) if listed else None,
        pe_dynamic=number(row.get('f9')) if listed else None,
        market_cap=number(row.get('f20')) if listed else None,
        source_time=quote_time(row.get('f124')) if listed else None,
        total_return=format((Decimal(last)/Decimal(issue)-1)*100, '.4f') if last and issue and Decimal(issue)>0 else None,
        first_open=number(row.get('OPEN_PRICE')), first_close=close,
        first_high=format(Decimal(issue)*(1+Decimal(high_change)/100), '.4f') if issue and high_change else None,
        first_change=number(row.get('LD_CLOSE_CHANGE')),
        # PROFIT为来源打新口径，可能按开板价格，不能冒充首日收盘收益。
        first_profit=format((Decimal(close)-Decimal(issue))*Decimal(ballot_shares), '.2f')
            if row.get('IS_BEIJING') != 1 and close and issue and ballot_shares else None,
        profit_per_100=format((Decimal(close)-Decimal(issue))*100, '.2f')
            if row.get('IS_BEIJING') == 1 and close and issue else None,
        source_ipo_profit=number(row.get('PROFIT')),
        ballot_shares=ballot_shares,
        industry=row.get('f100') or row.get('INDUSTRY_NAME'), business=row.get('MAIN_BUSINESS'),
        document_url=document_url(row.get('INFO_CODE')), source_date=day(row.get('UP_DATE')),
        security_id=security_id(row.get('SECUCODE')) if listed else None,
        status='已上市' if listed else '待上市' if row.get('APPLY_DATE') and day(row['APPLY_DATE']) <= today else '待申购', currency='CNY')


class IpoProvider:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=12, trust_env=False,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'})

    def close(self):
        self.client.close()

    def fetch(self, section, board, page):
        if section == 'news':
            from backend.news_data import NewsProvider
            provider = NewsProvider(self.client)
            rows = [r for r in provider.market() if re.search(r'新股|IPO|申购|上市委|招股', r['summary'], re.I)]
            return dict(rows=rows, total=len(rows), pages=1, page=1, page_size=100,
                source='新浪财经最新100条快讯中的新股相关内容', source_url='https://finance.sina.com.cn/',
                is_realtime=False, section=section, board=board)
        today = datetime.now(CHINA_TZ).date()
        params = dict(reportName='RPTA_APP_IPOAPPLY', columns='ALL', pageSize=200,
            pageNumber=page, source='WEB', client='WEB', sortColumns='APPLY_DATE,SECURITY_CODE', sortTypes='-1,-1')
        if section in {'apply', 'listed', 'pending'}:
            params.update(quoteColumns=','.join(f'{field}~01~SECURITY_CODE' for field in ('f2','f3','f5','f6','f8','f9','f20','f100','f124')),quoteType='0')
        filters = ['(SECURITY_TYPE_CODE in ("058001001","058001008"))'] if section in {'apply','listed','pending'} else []
        if section == 'listed':
            params.update(sortColumns='LISTING_DATE,SECURITY_CODE')
            filters.append(f"(LISTING_DATE<='{today.isoformat()}')(LISTING_DATE>'2010-01-01')")
        elif section == 'pending':
            filters.append(f"(APPLY_DATE>='{(today-timedelta(days=90)).isoformat()}')((LISTING_DATE>'{today.isoformat()}')(|@LISTING_DATE=\"NULL\"))")
        elif section == 'review':
            params.update(reportName='RPT_IPO_REVIEW', sortColumns='REVIEW_DATE,ORG_CODE')
        elif section == 'disclosure':
            params.update(reportName='RPT_IPO_INFOALLNEW', sortColumns='UPDATE_DATE,ORG_CODE')
        elif section == 'bonds':
            params.update(reportName='RPT_BOND_CB_LIST', sortColumns='PUBLIC_START_DATE,SECURITY_CODE')
        if board != 'all':
            if section in {'apply', 'listed', 'pending'}:
                codes = dict(sh='069001001001', sz='069001002001', gem='069001002002', star='069001001006', bj='069001017')
                filters.append(f'(TRADE_MARKET_CODE="{codes[board]}")')
            elif section == 'disclosure':
                labels = dict(sh='沪主板', sz='深主板', gem='创业板', star='科创板', bj='北交所')
                filters.append(f'(PREDICT_LISTING_MARKET="{labels[board]}")')
            elif section == 'review':
                codes = dict(sh='069001001001', sz='069001002001', gem='069001002002', star='069001001006', bj='069001017')
                filters.append(f'(TRADE_MARKET_CODE="{codes[board]}")')
        if filters:
            params['filter'] = ''.join(filters)
        response = self.client.get(URL, params=params)
        response.raise_for_status()
        data = response.json()
        result = data.get('result')
        if data.get('success') is not True or not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise ValueError('发行资料来源未返回有效记录')
        if section in {'apply','listed','pending','bonds'}:
            if any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',str(r.get('SECUCODE',''))) or str(r.get('SECUCODE',''))[:6] != r.get('SECURITY_CODE') for r in result['data']):
                raise ValueError('发行资料证券身份不匹配')
        rows = [normalize(r, section) for r in result['data']]
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('来源记录身份重复')
        return dict(rows=rows, total=result['count'], pages=result['pages'], page=page, page_size=200,
            source='东方财富公开发行/审核资料', source_url='https://data.eastmoney.com/xg/',
            report=params['reportName'], schema_version=3, is_realtime=False, section=section, board=board)


class IpoData:
    def __init__(self, store, terminal):
        self.store, self.terminal = store, terminal
        self.factory = IpoProvider
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ipo-cache')
        self.lock = threading.RLock()
        self.pending, self.due, self.errors = set(), {}, {}
        self.closed = False

    def read(self, section, board='all', page=1, force=False):
        if section not in SECTIONS or board not in BOARDS or not 1 <= page <= 100:
            raise ProviderError('INVALID_IPO_QUERY', '请选择有效的新股栏目、市场与页码')
        key = f'{section}:{board}:{page}'
        saved = self.store.get('ipo_cache', key, False)
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(saved['fetched_at'].replace('Z','+00:00'))).total_seconds() if saved else None
        ttl = self.terminal.effective_interval() if section == 'listed' else 300
        enabled = self.terminal.network_enabled and self.terminal.config()['enabled']
        with self.lock:
            if not self.closed and (enabled or force and self.terminal.network_enabled) and len(self.pending) < 8 and key not in self.pending and time.monotonic() >= self.due.get(key, 0) and (force or age is None or age >= ttl or saved.get('schema_version',0)<3 and section!='news'):
                self.pending.add(key)
                self.pool.submit(self.refresh, key, section, board, page)
            refreshing = key in self.pending
            error = self.errors.get(key)
        return {**(saved or dict(rows=[], page=page, page_size=200, total=0, pages=0, section=section, board=board)),
            'fetched_at': saved.get('fetched_at') if saved else None, 'refreshing': refreshing, 'enabled': enabled,
            'status': 'READY' if saved else 'LOADING' if refreshing else 'ERROR' if error else 'EMPTY',
            'error': error, 'stale': age is None or age >= ttl, 'is_realtime': False, 'refresh_interval_seconds': ttl}

    def refresh(self, key, section, board, page):
        provider = None
        try:
            provider = self.factory()
            result = provider.fetch(section, board, page)
            with self.store.lock, self.store.db:
                self.store.put('ipo_cache', dict(id=key, fetched_at=stamp(), **result))
            with self.lock:
                self.errors.pop(key, None)
                self.due[key] = time.monotonic() + 5
        except Exception:
            with self.lock:
                self.errors[key] = '发行资料更新失败，已保留缓存，可稍后重试'
                self.due[key] = time.monotonic() + 60
        finally:
            if provider:
                provider.close()
            with self.lock:
                self.pending.discard(key)

    def stop(self):
        self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
