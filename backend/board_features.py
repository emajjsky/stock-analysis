"""板块资讯、财报、概念与期股只读扩展；来源与派生口径显式保留。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from html import unescape
import hashlib
import json
import re
import statistics
import time
import httpx

from backend.providers import CHINA_TZ, ProviderError

FUTURE_MARKETS = {113, 114, 115, 8, 142, 225}
# 人工维护的产业关联，不表示价格相关性或买卖信号。
THEMES = {'AP': ('苹果', ['种植业', '农业']), 'CJ': ('红枣', ['种植业', '农业']),
    'LH': ('生猪', ['养殖业', '饲料']), 'JD': ('鸡蛋', ['养殖业']),
    'FG': ('玻璃', ['玻璃']), 'SA': ('纯碱', ['化学原料']),
    'MA': ('甲醇', ['化学原料']), 'TA': ('PTA', ['化学纤维']),
    'PF': ('短纤', ['化学纤维']), 'CF': ('棉花', ['纺织']),
    'CU': ('铜', ['工业金属']), 'AL': ('铝', ['工业金属']),
    'ZN': ('锌', ['工业金属']), 'SN': ('锡', ['小金属', '工业金属']),
    'AU': ('黄金', ['贵金属']), 'AG': ('白银', ['贵金属']),
    'RB': ('螺纹钢', ['钢铁']), 'HC': ('热卷', ['钢铁']), 'I': ('铁矿石', ['钢铁']),
    'JM': ('焦煤', ['煤炭']), 'J': ('焦炭', ['煤炭']), 'SC': ('原油', ['石油']),
    'FU': ('燃油', ['石油']), 'LU': ('低硫燃油', ['石油']),
    'M': ('豆粕', ['饲料']), 'RM': ('菜粕', ['饲料']), 'C': ('玉米', ['种植业']),
    'SI': ('工业硅', ['小金属', '光伏']), 'LC': ('碳酸锂', ['能源金属', '电池'])}


def clean(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', '', str(value or '')))).strip()[:1500]


class ProviderFeatures:
    def feature_json(self, url, params):
        r = self.client.get(url, params=params)
        r.raise_for_status()
        if len(r.content) > 4_000_000:
            raise ValueError('response too large')
        self.hashes.append(hashlib.sha256(r.content).hexdigest())
        return r.json()

    def board_news(self, code, name):
        param = dict(uid='', keyword=name, type=['cmsArticleWebOld'], client='web', clientType='web',
            clientVersion='curr', param={'cmsArticleWebOld': dict(searchScope='default', sort='time', pageIndex=1, pageSize=20)})
        r = self.client.get('https://search-api-web.eastmoney.com/search/jsonp', params={'cb': 'cb', 'param': json.dumps(param, ensure_ascii=False)})
        r.raise_for_status()
        if len(r.content) > 2_000_000 or not r.text.startswith('cb(') or not r.text.rstrip().endswith(')'):
            raise ValueError('invalid news response')
        payload = json.loads(r.text.strip()[3:-1])
        if payload.get('code') != 0:
            raise ValueError('news status')
        rows = []
        for item in payload.get('result', {}).get('cmsArticleWebOld', []):
            published = datetime.strptime(item['date'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CHINA_TZ)
            url = str(item.get('url', '')).replace('http://', 'https://', 1)
            if not re.fullmatch(r'https://[a-z0-9.-]+\.eastmoney\.com/[^\s<>"\']+', url):
                url = None
            rows.append(dict(id=str(item['code']), title=clean(item['title']), summary=clean(item.get('content')),
                published_at=published.astimezone(timezone.utc).isoformat(), url=url, media=clean(item.get('mediaName'))))
        return dict(code=code, keyword=name, items=rows, source='东方财富资讯关键词检索',
            scope_note='按板块名称检索，可能包含同词资讯，不等同于完整行业新闻目录',
            raw_hashes=[hashlib.sha256(r.content).hexdigest()])

    def board_financial(self, code, members):
        from backend.boards import number
        sample = sorted(members, key=lambda r: Decimal((r.get('quote') or {}).get('amount') or 0), reverse=True)[:20]
        codes = {r['code'] for r in sample}
        if not codes:
            raise ValueError('no member sample')
        selector = '(SECURITY_CODE in (' + ','.join('"' + c + '"' for c in sorted(codes)) + '))'
        base = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        payload = self.feature_json(base, dict(reportName='RPT_LICO_FN_CPD', columns='ALL',
            filter=selector + '(ISNEW="1")', pageSize=100, sortColumns='REPORTDATE', sortTypes=-1, source='WEB', client='WEB'))
        if payload.get('success') is not True:
            raise ValueError('financial source status')
        rows, seen = [], set()
        for item in (payload.get('result') or {}).get('data') or []:
            sid = str(item.get('SECURITY_CODE'))
            if sid not in codes or sid in seen:
                raise ValueError('financial identity')
            seen.add(sid)
            period = datetime.strptime(item['REPORTDATE'][:10], '%Y-%m-%d').date().isoformat()
            rows.append(dict(code=sid, name=clean(item['SECURITY_NAME_ABBR']), period=period,
                roe=number(item.get('WEIGHTAVG_ROE'), True), margin=number(item.get('XSMLL'), True),
                revenue_yoy=number(item.get('YSTZ'), True), profit_yoy=number(item.get('SJLTZ'), True),
                revenue=number(item.get('TOTAL_OPERATE_INCOME'), True), profit=number(item.get('PARENT_NETPROFIT'), True)))
        balance_error = None
        try:
            for period in {r['period'] for r in rows}:
                balance = self.feature_json(base, dict(reportName='RPT_DMSK_FN_BALANCE',
                    columns='SECURITY_CODE,REPORT_DATE,TOTAL_ASSETS,TOTAL_LIABILITIES',
                    filter=selector + "(REPORT_DATE='" + period + "')", pageSize=100,
                    source='WEB', client='WEB'))
                if balance.get('success') is not True:
                    raise ValueError('balance status')
                for item in (balance.get('result') or {}).get('data') or []:
                    if item.get('SECURITY_CODE') not in codes or item.get('REPORT_DATE', '')[:10] != period:
                        raise ValueError('balance identity')
                    row = next((r for r in rows if r['code'] == item['SECURITY_CODE'] and r['period'] == period), None)
                    if row is not None:
                        assets = number(item.get('TOTAL_ASSETS'))
                        liabilities = number(item.get('TOTAL_LIABILITIES'))
                        row.update(assets=assets, liabilities=liabilities,
                            debt_ratio=str(Decimal(liabilities) / Decimal(assets) * 100) if assets and Decimal(assets) > 0 and liabilities is not None else None)
        except Exception:
            balance_error = '资产负债数据暂不可用，其余财报保持显示'
        stats = {}
        for field in ['roe', 'margin', 'debt_ratio', 'revenue_yoy', 'profit_yoy']:
            values = [Decimal(r[field]) for r in rows if r.get(field) is not None]
            stats[field] = dict(value=str(statistics.median(values)) if values else None, count=len(values))
        return dict(code=code, rows=rows, metrics=stats, sample_size=len(sample), covered=len(rows),
            source='东方财富业绩报表与资产负债表', raw_hashes=self.hashes, balance_error=balance_error,
            scope_note='成交额前20只已支持成分股、各自最新报告期的中位数；不是全板块评级')

    def concept_new(self):
        r = self.client.get('https://q.10jqka.com.cn/gn/')
        r.raise_for_status()
        if len(r.content) > 2_000_000:
            raise ValueError('concept page too large')
        html = r.content.decode('gbk', errors='replace')
        rows = []
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', html, re.S | re.I):
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', tr, re.S | re.I)
            if len(cells) != 5 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', clean(cells[0])):
                continue
            m = re.search(r'/gn/detail/code/(\d{6})/', cells[1])
            if not m:
                continue
            day = datetime.strptime(clean(cells[0]), '%Y-%m-%d').date()
            if day > datetime.now(CHINA_TZ).date():
                raise ValueError('future concept date')
            rows.append(dict(id='THS.' + m[1], ths_code=m[1], name=clean(cells[1]), date=day.isoformat(),
                event=clean(cells[2]), total=int(clean(cells[4])), url=f'https://q.10jqka.com.cn/gn/detail/code/{m[1]}/'))
        if not rows:
            raise ValueError('no concepts on source page')
        return dict(rows=sorted(rows, key=lambda r: r['date'], reverse=True), source='同花顺公开概念页面',
            date_label='公开页概念日期', raw_hashes=[hashlib.sha256(r.content).hexdigest()])

    def futures(self):
        from backend.boards import LIST_URL, number, source_time
        rows, total = [], None
        for page in range(1, 21):
            data = self.get(LIST_URL, dict(pn=page, pz=100, fs='m:113,m:114,m:115,m:8,m:142,m:225',
                fid='f12', po=0, fltt=2, np=1, fields='f12,f13,f14,f2,f3,f4,f5,f6,f17,f18,f28,f31,f32,f108,f163,f210,f124'))
            if total is not None and total != data.get('total'):
                raise ValueError('unstable futures total')
            total = data.get('total')
            if type(total) is not int or not 0 < total <= 2000:
                raise ValueError('invalid futures total')
            batch = data.get('diff')
            if not isinstance(batch, list) or not batch:
                raise ValueError('missing futures page')
            for item in batch:
                symbol, market = item.get('f12'), item.get('f13')
                if market not in FUTURE_MARKETS or not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z]{1,3}[0-9]{3,4}', symbol):
                    continue  # 连续/指数不冒充实际可交易月份合约。
                prefix = re.match('[A-Za-z]+', symbol)[0].upper()
                theme = THEMES.get(prefix)
                rows.append(dict(id=f'{market}.{symbol}', code=symbol, market=market, name=clean(item['f14']),
                    price=number(item.get('f2'), True), change_pct=number(item.get('f3'), True), change=number(item.get('f4'), True),
                    volume=number(item.get('f5')), amount=number(item.get('f6')), bid=number(item.get('f31'), True),
                    ask=number(item.get('f32'), True), open_interest=number(item.get('f108')),
                    previous_interest=number(item.get('f210')), interest_change=number(item.get('f163'), True),
                    source_time=source_time(item.get('f124')), theme=theme[0] if theme else None,
                    theme_keywords=theme[1] if theme else []))
            if page * 100 >= total:
                if len({r['id'] for r in rows}) != len(rows):
                    raise ValueError('duplicate future')
                return dict(rows=rows, total=total, loaded=len(rows), source='东方财富国内期货行情',
                    volume_unit='CONTRACTS', theme_note='主题为人工产业关联，不代表相关性或交易信号', raw_hashes=self.hashes)
        raise ValueError('futures page limit')

    def convertible_bonds(self):
        """Join delayed convertible-bond quotes with public issue terms and equity quotes."""
        from backend.boards import number, source_time

        quotes, _ = self.pages('b:MK0354')
        bond_quotes = {
            row['f12']: row for row in quotes
            if isinstance(row.get('f12'), str) and re.fullmatch(r'\d{6}', row['f12'])
        }
        if not bond_quotes:
            raise ValueError('empty convertible bond directory')

        terms = {}
        codes = list(bond_quotes)
        for offset in range(0, len(codes), 80):
            batch = codes[offset:offset + 80]
            quoted = ','.join('"' + code + '"' for code in batch)
            response = self.client.get(
                'https://datacenter-web.eastmoney.com/api/data/v1/get',
                params={
                    'reportName': 'RPT_BOND_CB_LIST',
                    'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,CONVERT_STOCK_CODE,SECURITY_SHORT_NAME,LISTING_DATE,DELIST_DATE,INITIAL_TRANSFER_PRICE,TRANSFER_START_DATE,TRANSFER_END_DATE,ACTUAL_ISSUE_SCALE',
                    'filter': f'(SECURITY_CODE in ({quoted}))',
                    'pageNumber': 1,
                    'pageSize': 100,
                    'source': 'WEB',
                    'client': 'WEB',
                },
                headers={'Referer': 'https://data.eastmoney.com/'},
            )
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError('convertible terms response too large')
            self.hashes.append(hashlib.sha256(response.content).hexdigest())
            payload = response.json()
            result = payload.get('result')
            rows = result.get('data') if payload.get('success') is True and isinstance(result, dict) else None
            if not isinstance(rows, list) or len(rows) > len(batch):
                raise ValueError('invalid convertible terms response')
            for row in rows:
                code, stock_code = row.get('SECURITY_CODE'), row.get('CONVERT_STOCK_CODE')
                if code not in batch or code in terms or not re.fullmatch(r'\d{6}', str(stock_code or '')):
                    raise ValueError('invalid convertible issue mapping')
                if row.get('DELIST_DATE'):
                    continue
                terms[code] = row

        stock_markets = {
            row['CONVERT_STOCK_CODE']: (1 if row['CONVERT_STOCK_CODE'].startswith(('5', '6', '9')) else 0)
            for row in terms.values()
        }
        stock_quotes = {}
        stock_codes = list(stock_markets)
        for offset in range(0, len(stock_codes), 80):
            batch = stock_codes[offset:offset + 80]
            secids = ','.join(f'{stock_markets[code]}.{code}' for code in batch)
            data = self.get(
                'https://push2delay.eastmoney.com/api/qt/ulist.np/get',
                {'fltt': 2, 'fields': 'f2,f3,f4,f12,f13,f14,f124', 'secids': secids},
            )
            rows = data.get('diff')
            if not isinstance(rows, list) or len(rows) > len(batch):
                raise ValueError('invalid linked stock quotes')
            for row in rows:
                code, market = row.get('f12'), row.get('f13')
                if code not in batch or market != stock_markets[code] or code in stock_quotes:
                    raise ValueError('linked stock quote identity mismatch')
                stock_quotes[code] = row

        today = datetime.now(CHINA_TZ).date()
        output = []
        for code, term in terms.items():
            quote = bond_quotes.get(code)
            if quote is None:
                continue
            stock_code = term['CONVERT_STOCK_CODE']
            stock_quote = stock_quotes.get(stock_code)

            def term_date(key):
                value = term.get(key)
                if not value:
                    return None
                parsed = datetime.strptime(value[:10], '%Y-%m-%d').date()
                return parsed.isoformat()

            starts, ends = term_date('TRANSFER_START_DATE'), term_date('TRANSFER_END_DATE')
            start_day = datetime.strptime(starts, '%Y-%m-%d').date() if starts else None
            end_day = datetime.strptime(ends, '%Y-%m-%d').date() if ends else None
            state = 'UNKNOWN' if start_day is None or end_day is None else (
                'BEFORE' if today < start_day else 'ENDED' if today > end_day else 'ACTIVE'
            )
            bond_change = number(quote.get('f3'), True)
            stock_change = number(stock_quote.get('f3'), True) if stock_quote else None
            spread = None
            if bond_change is not None and stock_change is not None:
                spread = format(Decimal(bond_change) - Decimal(stock_change), 'f')
            bond_price = number(quote.get('f2'), True)
            stock_price = number(stock_quote.get('f2'), True) if stock_quote else None
            output.append(dict(
                id=code,
                code=code,
                name=clean(quote.get('f14')),
                price=bond_price if bond_price and Decimal(bond_price) > 0 else None,
                change_pct=bond_change,
                amount=number(quote.get('f6')),
                source_time=source_time(quote.get('f124')),
                stock_id=f'LIVE.{"SH" if stock_markets[stock_code] == 1 else "SZ"}.{stock_code}',
                stock_code=stock_code,
                stock_name=clean(term.get('SECURITY_SHORT_NAME')),
                stock_price=stock_price if stock_price and Decimal(stock_price) > 0 else None,
                stock_change_pct=stock_change,
                stock_source_time=source_time(stock_quote.get('f124')) if stock_quote else None,
                change_spread=spread,
                listing_date=term_date('LISTING_DATE'),
                conversion_start=starts,
                conversion_end=ends,
                conversion_state=state,
                initial_conversion_price=number(term.get('INITIAL_TRANSFER_PRICE')),
                issue_scale=number(term.get('ACTUAL_ISSUE_SCALE')),
            ))
        if not output:
            raise ValueError('no convertible bonds matched public issue terms')
        return dict(rows=output, total=len(bond_quotes), loaded=len(output), linked=len(output),
            unmatched=len(bond_quotes) - len(output), source='东方财富公开可转债延时行情与发行条款',
            relation_note='正股关联来自发行条款代码；涨跌差=转债涨跌幅-正股涨跌幅，不代表统计相关性。仅展示发行初始转股价，不推算现行转股价值或溢价率。')

    def etfs(self):
        from backend.boards import number, source_time
        rows = self.pages('b:MK0021,b:MK0022,b:MK0023,b:MK0024')[0]
        return dict(rows=[dict(code=r['f12'], market=r['f13'], name=clean(r['f14']),
            price=number(r.get('f2')), change_pct=number(r.get('f3'), True), amount=number(r.get('f6')),
            source_time=source_time(r.get('f124'))) for r in rows], source='东方财富场内基金行情', raw_hashes=self.hashes)

    def etf_portfolio(self, code):
        """只解析固定基金披露接口，不执行返回的 JavaScript；只取最新一期前十大股票。"""
        from backend.boards import number
        if not re.fullmatch(r'\d{6}', code):
            raise ValueError('invalid ETF code')
        response = self.client.get('https://fundf10.eastmoney.com/FundArchivesDatas.aspx',
            params=dict(type='jjcc', code=code, topline=10, year='', month=''),
            headers={'Referer': 'https://fundf10.eastmoney.com/'})
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError('portfolio too large')
        match = re.search(r'\bcontent\s*:\s*"((?:\\.|[^"\\])*)"', response.text)
        if not match:
            raise ValueError('invalid portfolio wrapper')
        html = json.loads('"' + match[1] + '"')
        title = re.search(r'<h4\b[^>]*>(.*?)</h4>', html, re.S | re.I)
        body = re.search(r'<tbody\b[^>]*>(.*?)</tbody>', html, re.S | re.I)
        if not title or not body:
            raise ValueError('no stock portfolio')
        date = re.search(r'截止至[：:]\s*(\d{4}-\d{2}-\d{2})', clean(title[1]))
        if not date or datetime.strptime(date[1], '%Y-%m-%d').date() > datetime.now(CHINA_TZ).date():
            raise ValueError('invalid portfolio report date')
        holdings, seen = [], set()
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', body[1], re.S | re.I):
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', tr, re.S | re.I)
            if len(cells) != 9:
                raise ValueError('invalid portfolio columns')
            security = clean(cells[1])
            # A股与港股身份分开；不将五位港股代码补成六位。
            if not re.fullmatch(r'\d{6}', security):
                continue
            if security in seen:
                raise ValueError('duplicate portfolio stock')
            seen.add(security)
            weight = number(clean(cells[6]).removesuffix('%'))
            if weight is not None and Decimal(weight) > 100:
                raise ValueError('invalid portfolio weight')
            holdings.append(dict(code=security, name=clean(cells[2]), weight=weight))
        if not holdings or len(holdings) > 10:
            raise ValueError('missing top ten holdings')
        return dict(code=code, report_date=date[1], holdings=holdings,
            raw_hash=hashlib.sha256(response.content).hexdigest())

    def etf_holdings(self, quotes, saved=None):
        """有界取样：每个主要主题中成交额最高的一只ETF，季度披露不冒充实时持仓。"""
        groups = ['沪深300', '中证500', '中证1000', 'A500', '科创50', '创业板', '半导体',
            '芯片', '电子', '通信', '软件', '人工智能', '机器人', '农业', '养殖', '医药',
            '创新药', '证券', '银行', '光伏', '电池', '有色', '化工', '消费']
        choices = {}
        ranked = sorted((r for r in quotes if 'ETF' in r['name'].upper() and r.get('amount') is not None
            and not any(w in r['name'] for w in ['港', '中韩', '日经', '纳指', '标普', '海外', '德国', '法国'])),
            key=lambda r: Decimal(r['amount']), reverse=True)
        for group in groups:
            row = next((r for r in ranked if group in r['name']), None)
            if row:
                choices[row['code']] = row
        if not choices:
            raise ValueError('waiting for ETF directory')
        rows, errors = [], []
        previous = {r['code']: r for r in saved or []}
        capped = False
        for index, code in enumerate(choices):
            if index and not capped:
                time.sleep(0.35)
            try:
                if capped:
                    raise ValueError('source frequency limit')
                rows.append({**self.etf_portfolio(code), 'name': choices[code]['name'], 'stale': False})
            except Exception as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 514):
                    capped = True  # 尊重源频率限制，不重试或继续向该源提交。
                errors.append(code)
                if code in previous:
                    rows.append({**previous[code], 'stale': True})
        if not rows:
            raise ValueError('ETF reports unavailable')
        return dict(rows=rows, total=len(choices), failed=len(errors), failed_codes=errors,
            source='天天基金ETF股票投资明细',
            scope_note='主要主题成交额领先ETF的最新一期披露前十大股票样本；不是全部ETF、完整持仓或实时持仓比例')


class DataFeatures:
    def refresh_features(self, section, code=None, future_id=None, period='daily'):
        if section not in ('hot', 'heat', 'funds', 'rotation', 'new', 'futures', 'bond'):
            raise ProviderError('INVALID_BOARD_VIEW', '请选择有效的板块视图')
        results = []
        if section in ('hot', 'new'):
            if section == 'new':
                results.append(self.read('latest-concepts', lambda p: p.concept_new(), ttl=3600, force=True))
            results.append(self.read('etfs', lambda p: p.etfs(), force=True))
            if section == 'new':
                results.append(self.etf_holdings(force=True))
        if section == 'bond':
            results.append(self.read('convertible-bonds', lambda p: p.convertible_bonds(), force=True))
        if section == 'futures':
            results.append(self.read('futures', lambda p: p.futures(), force=True))
            saved = self.store.get('board_cache', 'futures', False) or {}
            row = next((r for r in saved.get('rows', []) if r['id'] == future_id), None)
            if row and period in ('daily', 'intraday'):
                results.append(self.read(f'future:{period}:{future_id}', lambda p: p.chart(row['code'], period, market=row['market']), force=True))
        if code:
            self.validate(code)
            board = next(r for kind in ('industry', 'concept') for r in (self.store.get('board_cache', 'list:' + kind, False) or {}).get('rows', []) if r['code'] == code)
            if section in ('hot', 'new', 'heat'):
                results.append(self.read('news:' + code, lambda p: p.board_news(code, board['name']), ttl=600, force=True))
            if section == 'heat':
                members = (self.store.get('board_cache', 'members:' + code, False) or {}).get('rows')
                if members:
                    results.append(self.read('financial:' + code, lambda p: p.board_financial(code, members), ttl=86400, force=True))
        return any(r['refreshing'] for r in results)

    def board_news(self, code):
        self.validate(code)
        board = next(r for kind in ('industry', 'concept') for r in (self.store.get('board_cache', 'list:' + kind, False) or {}).get('rows', []) if r['code'] == code)
        return self.read('news:' + code, lambda p: p.board_news(code, board['name']), ttl=600)

    def financial(self, code):
        self.validate(code)
        members = self.members(code)
        if not members.get('rows'):
            return dict(status='LOADING' if members['refreshing'] else 'EMPTY', error=members.get('error'), refreshing=members['refreshing'], enabled=members['enabled'])
        return self.read('financial:' + code, lambda p: p.board_financial(code, members['rows']), ttl=86400)

    def latest_concepts(self):
        result = self.read('latest-concepts', lambda p: p.concept_new(), ttl=3600)
        # 只关联完全同名的东财板块，保留两种来源身份，不按相似名称强行拼接。
        names = {r['name']: r['code'] for r in (self.store.get('board_cache', 'list:concept', False) or {}).get('rows', [])}
        return {**result, 'rows': [{**r, 'board_code': names.get(r['name'])} for r in result.get('rows', [])]}

    def futures(self):
        return self.read('futures', lambda p: p.futures())

    def convertible_bonds(self):
        return self.read('convertible-bonds', lambda p: p.convertible_bonds())

    def etfs(self):
        return self.read('etfs', lambda p: p.etfs())

    def etf_holdings(self, force=False):
        quotes = self.etfs()
        if not quotes.get('rows'):
            return dict(status='LOADING' if quotes['refreshing'] else 'EMPTY', rows=[],
                enabled=quotes['enabled'], error=quotes.get('error'), refreshing=quotes['refreshing'])
        saved = self.store.get('board_cache', 'etf-holdings', False) or {}
        return self.read('etf-holdings', lambda p: p.etf_holdings(quotes['rows'], saved.get('rows')),
            ttl=86400, force=force)

    def future_chart(self, identity, period):
        saved = self.store.get('board_cache', 'futures', False) or {}
        row = next((r for r in saved.get('rows', []) if r['id'] == identity), None)
        if row is None or period not in ('intraday', 'daily'):
            raise ProviderError('INVALID_FUTURE', '请从已加载的国内期货列表选择合约和周期')
        return self.read(f'future:{period}:{identity}', lambda p: p.chart(row['code'], period, market=row['market']), ttl=300 if period == 'daily' else None)

    def benchmark(self):
        return self.read('benchmark', lambda p: p.chart('000001', 'intraday', market=1))

    def historical_rotation(self, kind):
        from backend.boards import stamp
        listing = self.store.get('board_cache', 'list:' + kind, False) or {}
        if not listing.get('rows'):
            return dict(days=[], covered=0, total=0, note='等待当前分类目录')
        rows = listing['rows']
        histories, errors = {}, []
        progress = {'completed': 0, 'total': len(rows), 'failed': 0}
        self.rotation_progress = getattr(self, 'rotation_progress', {})
        self.rotation_progress[kind] = progress
        deadline = time.monotonic() + 600
        def load(row):
            if self.closed or time.monotonic() >= deadline:
                raise ValueError('stopped')
            key = 'rotation-history:' + row['code']
            cached = self.store.get('board_cache', key, False)
            if cached and cached.get('bars') and (datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at'].replace('Z', '+00:00'))).total_seconds() < 3600:
                return row['code'], cached['bars']
            with self.history_slots:
                if self.closed or time.monotonic() >= deadline:
                    raise ValueError('stopped')
                p = self.factory()
                try:
                    result = p.chart(row['code'], 'daily', limit=30)
                    with self.store.lock, self.store.db:
                        self.store.put('board_cache', dict(id=key, fetched_at=stamp(), **result))
                    return row['code'], result['bars']
                finally:
                    p.close()
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='rotation-history') as pool:
            jobs = {pool.submit(load, row): row['code'] for row in rows}
            for future in as_completed(jobs):
                try:
                    code, bars = future.result()
                    histories[code] = bars
                except Exception:
                    errors.append(jobs[future])
                progress['completed'] += 1
                progress['failed'] = len(errors)
        dates = sorted({b['time'] for history in histories.values() for b in history}, reverse=True)[:10]
        days = []
        for day in dates:
            ranked = []
            for row in rows:
                bar = next((b for b in histories.get(row['code'], []) if b['time'] == day), None)
                if bar is not None and bar.get('change_pct') is not None:
                    ranked.append({'id': row['id'], 'code': row['code'], 'name': row['name'], 'kind': kind, 'price': bar['close'], 'change_pct': bar['change_pct'],
                        'amount': bar['amount'], 'source_time': None, 'trade_date': day})
            ranked.sort(key=lambda r: Decimal(r['change_pct']), reverse=True)
            days.append(dict(date=day, rows=ranked, covered=len(ranked), fetched_at=stamp()))
        if not days:
            raise ValueError('no historical ranking')
        if self.closed:
            raise ValueError('stopped')
        return dict(days=days, covered=len(histories), total=len(rows), failed=len(errors), source='东方财富板块日K回填',
            note='按当前板块目录回看历史；新设板块在早期日期可能无数据，不是历史时点分类还原')

    def rotation_full(self, kind):
        if kind not in ('industry', 'concept'):
            raise ProviderError('INVALID_BOARD_KIND', '请选择行业或概念')
        if not (self.store.get('board_cache', 'list:' + kind, False) or {}).get('rows'):
            self.boards(kind)
            return dict(status='LOADING', days=[], refreshing=True, enabled=self.terminal.config()['enabled'])
        result = self.read('rotation-full:' + kind, lambda p: self.historical_rotation(kind), ttl=3600)
        if not result.get('days'):
            result['days'] = self.rotation(kind)['days']
        return {**result, 'progress': getattr(self, 'rotation_progress', {}).get(kind)}
