"""固定公开研究端点适配器：公司概况、财务摘要和公告目录。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import json
import re
import time
from typing import Any

import httpx

from backend.providers import ProviderError, normalize_security_id

COMPANY_URL = 'https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax'
FINANCIAL_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
ANNOUNCEMENT_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
SOURCE = '东方财富公开研究接口'
CHINA_TZ = timezone(timedelta(hours=8))
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif tag in {'br', 'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1
        elif tag in {'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _text(value: Any, limit: int = 2000) -> str | None:
    if value is None:
        return None
    parser = _PlainText()
    parser.feed(str(value)[:20000])
    value = re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()
    return value[:limit] if value and value not in {'--', '-', 'null', 'None'} else None


def _date(value: Any) -> str | None:
    if value is None or str(value).strip() in {'', '--', 'None', 'null'}:
        return None
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})(?:[ T]00:00:00)?', str(value).strip())
    if not match:
        raise ProviderError('INVALID_DATE', '研究资料日期格式无效')
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError as exc:
        raise ProviderError('INVALID_DATE', '研究资料日期无效') from exc


def _publication(value: Any) -> tuple[str | None, str]:
    day = _date(value)
    if day is None:
        return None, 'UNKNOWN'
    # 源只有披露日期。UTC午夜换算仅为传输格式，DATE标记必须保留。
    return datetime.fromisoformat(day).replace(tzinfo=CHINA_TZ).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), 'DATE'


def _decimal(value: Any, *, max_scale: int = 8) -> str | None:
    if value is None or str(value).strip() in {'', '--', 'None', 'null'}:
        return None
    try:
        if isinstance(value, bool):
            raise InvalidOperation()
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1e20') or number.as_tuple().exponent < -max_scale:
            raise InvalidOperation()
        return format(number, 'f')
    except (InvalidOperation, ValueError) as exc:
        raise ProviderError('INVALID_NUMBER', '研究财务字段不是有效十进制金额') from exc


class EastmoneyResearchProvider:
    """只允许固定域名；客户端可注入确定性响应进行离线测试。"""

    financial_schema_version = 2

    def __init__(self, client: httpx.Client | None = None, timeout: float = 12.0):
        if not 0 < timeout <= 30:
            raise ProviderError('INVALID_REQUEST', '研究请求超时须在0到30秒之间')
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False,
            headers={'User-Agent': 'AshareResearchWorkstation/0.2', 'Accept': 'application/json',
                     'Referer': 'https://data.eastmoney.com/'})
        self.timeout = timeout

    def close(self):
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _code(security_id: str) -> tuple[str, str]:
        canonical, _ = normalize_security_id(security_id)
        exchange, code = canonical.split('.')
        return canonical, exchange + code

    def _get_json(self, url: str, *, params: dict[str, Any], label: str) -> tuple[dict, str, str]:
        for attempt in range(2):
            try:
                response = self.client.get(url, params=params, timeout=self.timeout, follow_redirects=False)
                break
            except httpx.HTTPError as exc:
                if attempt == 1:
                    raise ProviderError('UPSTREAM_UNAVAILABLE', f'{label}请求失败') from exc
                time.sleep(0.25)
        if response.status_code != 200:
            raise ProviderError('UPSTREAM_ERROR', f'{label}HTTP状态异常：{response.status_code}')
        if response.headers.get('location'):
            raise ProviderError('UNSAFE_REDIRECT', f'{label}出现重定向，未保存')
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ProviderError('RESPONSE_TOO_LARGE', f'{label}响应超过2MB，未保存')
        try:
            # 直接从字节读Decimal，不能先经float再转金额字符串。
            data = json.loads(response.content, parse_float=Decimal, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError) as exc:
            raise ProviderError('INVALID_RESPONSE', f'{label}不是有效JSON') from exc
        if not isinstance(data, dict):
            raise ProviderError('INVALID_RESPONSE', f'{label}返回结构异常')
        if data.get('success') is False or data.get('success') == 0:
            raise ProviderError('UPSTREAM_REJECTED', f'{label}上游明确返回失败')
        raw_hash = hashlib.sha256(response.content).hexdigest()
        return data, raw_hash, _now()

    def company(self, security_id: str) -> dict[str, Any]:
        canonical, code = self._code(security_id)
        data, raw_hash, received = self._get_json(COMPANY_URL, params={'code': code}, label='公司概况')
        jbzl = data.get('jbzl') if isinstance(data.get('jbzl'), dict) else {}
        if not jbzl:
            raise ProviderError('NO_DATA', '公司概况没有返回有效资料')
        if str(data.get('SecurityCode', jbzl.get('agdm', ''))) != code[2:] or (data.get('Code') is not None and data['Code'] != code):
            raise ProviderError('IDENTITY_MISMATCH', '公司概况证券身份不匹配')
        business = _text(jbzl.get('gsjj') or jbzl.get('jyfw'))
        facts = []
        listing = data.get('fxxg') if isinstance(data.get('fxxg'), dict) else {}
        fields = [('公司全称', jbzl.get('gsmc')), ('上市日期', listing.get('ssrq') or jbzl.get('ssrq')), ('所属行业', jbzl.get('sshy')), ('法定代表人', jbzl.get('frdb'))]
        for label, value in fields:
            value = _text(value, 300)
            if value:
                facts.append({'label': label, 'value': value, 'period': '当前资料', 'source': SOURCE})
        if not business and not facts:
            raise ProviderError('NO_DATA', '公司概况字段为空')
        return {'security_id': canonical, 'business': business, 'facts': facts, 'source': SOURCE,
            'source_url': COMPANY_URL, 'received_at': received, 'raw_hash': raw_hash}

    def financials(self, security_id: str) -> dict[str, Any]:
        canonical, code = self._code(security_id)
        data, raw_hash, received = self._get_json(FINANCIAL_URL, params={
            'reportName': 'RPT_DMSK_FN_INCOME',
            'columns': 'SECURITY_CODE,REPORT_DATE,NOTICE_DATE,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,TOI_RATIO,PARENT_NETPROFIT_RATIO',
            'filter': f'(SECURITY_CODE="{code[2:]}")', 'pageSize': 4, 'pageNumber': 1,
            'sortColumns': 'REPORT_DATE', 'sortTypes': '-1'}, label='财务摘要')
        rows = ((data.get('result') or {}).get('data') or []) if isinstance(data.get('result'), dict) else []
        if not isinstance(rows, list):
            raise ProviderError('INVALID_RESPONSE', '财务摘要返回结构异常')
        records = []
        seen_periods = set()
        for row in rows[:4]:
            if not isinstance(row, dict):
                raise ProviderError('INVALID_RESPONSE', '财务摘要记录格式异常')
            if str(row.get('SECURITY_CODE', '')) != code[2:]:
                raise ProviderError('IDENTITY_MISMATCH', '财务摘要证券身份不匹配')
            period = _date(row.get('REPORT_DATE'))
            if not period:
                raise ProviderError('INVALID_DATE', '财务摘要缺少报告期')
            if period in seen_periods:
                raise ProviderError('DATA_CONFLICT', '财务摘要出现重复报告期')
            seen_periods.add(period)
            notice, precision = _publication(row.get('NOTICE_DATE'))
            records.append({'period': period, 'published_at': notice, 'publication_precision': precision,
                'total_revenue': _decimal(row.get('TOTAL_OPERATE_INCOME')), 'parent_net_profit': _decimal(row.get('PARENT_NETPROFIT')),
                'revenue_yoy': _decimal(row.get('TOI_RATIO'), max_scale=16), 'profit_yoy': _decimal(row.get('PARENT_NETPROFIT_RATIO'), max_scale=16),
                'currency': 'CNY', 'unit': '元'})
        if not records:
            raise ProviderError('NO_DATA', '财务摘要没有返回有效报告期')
        return {'security_id': canonical, 'schema_version': self.financial_schema_version, 'records': sorted(records, key=lambda row: row['period'], reverse=True), 'source': SOURCE,
            'source_url': FINANCIAL_URL, 'received_at': received, 'raw_hash': raw_hash}

    def corporate_actions(self, security_id: str) -> dict[str, Any]:
        canonical, code = self._code(security_id)
        secucode = code[2:] + ('.SH' if canonical.startswith('SH.') else '.SZ')
        data, raw_hash, received = self._get_json(FINANCIAL_URL, params={
            'reportName': 'RPT_SHAREBONUS_DET',
            'columns': 'SECUCODE,SECURITY_CODE,REPORT_DATE,NOTICE_DATE,EQUITY_RECORD_DATE,EX_DIVIDEND_DATE,IMPL_PLAN_PROFILE,ASSIGN_PROGRESS',
            'filter': f'(SECUCODE="{secucode}")', 'pageSize': 8, 'pageNumber': 1,
            'sortColumns': 'REPORT_DATE', 'sortTypes': '-1'}, label='分红与除权')
        rows = (data.get('result') or {}).get('data') or []
        if not isinstance(rows, list):
            raise ProviderError('INVALID_RESPONSE', '分红与除权格式异常')
        items=[]
        for row in rows[:8]:
            if str(row.get('SECUCODE')) != secucode or str(row.get('SECURITY_CODE')) != code[2:]:
                raise ProviderError('IDENTITY_MISMATCH', '分红与除权证券身份不匹配')
            items.append(dict(period=_date(row.get('REPORT_DATE')),
                published_at=_date(row.get('NOTICE_DATE')), record_date=_date(row.get('EQUITY_RECORD_DATE')),
                ex_date=_date(row.get('EX_DIVIDEND_DATE')), plan=_text(row.get('IMPL_PLAN_PROFILE'),500) or '',
                status=_text(row.get('ASSIGN_PROGRESS'),100) or ''))
        return dict(security_id=canonical,items=items,source=SOURCE,source_url=FINANCIAL_URL,
                    received_at=received,raw_hash=raw_hash)

    def announcements(self, security_id: str) -> dict[str, Any]:
        canonical, code = self._code(security_id)
        stock_code = code[2:]
        data, raw_hash, received = self._get_json(ANNOUNCEMENT_URL, params={
            'page_size': 10, 'page_index': 1, 'ann_type': 'A', 'stock_list': stock_code}, label='公告目录')
        payload = data.get('data') if isinstance(data.get('data'), dict) else {}
        rows = payload.get('list') if isinstance(payload.get('list'), list) else []
        events = []
        seen_ids = set()
        for row in rows[:10]:
            if not isinstance(row, dict) or not _text(row.get('title') or row.get('title_ch')):
                raise ProviderError('INVALID_RESPONSE', '公告目录缺少有效标题')
            codes = row.get('codes')
            expected_market = '1' if canonical.startswith('SH.') else '0'
            if not isinstance(codes, list) or not any(isinstance(item, dict) and str(item.get('stock_code')) == stock_code and str(item.get('market_code', expected_market)) == expected_market for item in codes):
                raise ProviderError('IDENTITY_MISMATCH', '公告目录证券身份不匹配')
            art_code = _text(row.get('art_code'), 100)
            if not art_code or not re.fullmatch(r'AN\d{1,32}', art_code) or art_code in seen_ids:
                raise ProviderError('INVALID_RESPONSE', '公告编号无效或重复')
            seen_ids.add(art_code)
            notice, precision = _publication(row.get('notice_date'))
            events.append({'id': art_code, 'title': _text(row.get('title_ch') or row.get('title'), 500),
                'published_at': notice, 'publication_precision': precision,
                'url': f'https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html'})
        if not events:
            raise ProviderError('NO_DATA', '公告目录没有返回有效标题')
        return {'security_id': canonical, 'events': events, 'source': SOURCE,
            'source_url': ANNOUNCEMENT_URL, 'received_at': received, 'raw_hash': raw_hash}
