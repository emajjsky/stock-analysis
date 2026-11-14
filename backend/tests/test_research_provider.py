"""研究资料上游解析的固定端点、缺失值和失败边界。"""
import json

import httpx
import pytest

from backend.providers import ProviderError
from backend.research_provider import EastmoneyResearchProvider, ANNOUNCEMENT_URL, COMPANY_URL, FINANCIAL_URL


def client_for(payloads, status=200, headers=None):
    def handler(request):
        for key, payload in payloads.items():
            if request.url.host in key or request.url.path in key:
                return httpx.Response(status, json=payload, headers=headers or {}, request=request)
        return httpx.Response(404, request=request)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fixed_endpoints_parse_company_financial_announcement_and_keep_nulls():
    client = client_for({
        '/PC_HSF10/CompanySurvey/CompanySurveyAjax': {'SecurityCode': '600519', 'Code': 'SH600519', 'jbzl': {'gsmc': '测试股份', 'gsjj': '<p>主营描述</p><script>不可见</script>', 'ssrq': '2020-01-02', 'sshy': '制造'}},
        '/api/data/v1/get': {'result': {'data': [{'SECURITY_CODE': '600519', 'REPORT_DATE': '2026-06-30', 'NOTICE_DATE': '2026-08-15', 'TOTAL_OPERATE_INCOME': 123.45, 'PARENT_NETPROFIT': None}]}},
        '/api/security/ann': {'data': {'list': [{'art_code': 'AN1', 'title': '公告标题', 'notice_date': '2026-08-15', 'codes': [{'stock_code': '600519', 'market_code': '1'}]}]}},
    })
    provider = EastmoneyResearchProvider(client)
    company = provider.company('SH.600519')
    finance = provider.financials('SH.600519')
    announcements = provider.announcements('SH.600519')
    assert company['security_id'] == 'SH.600519' and company['business'] == '主营描述'
    assert finance['records'][0]['total_revenue'] == '123.45' and finance['records'][0]['parent_net_profit'] is None
    assert finance['records'][0]['publication_precision'] == 'DATE'
    assert finance['records'][0]['published_at'] == '2026-08-14T16:00:00Z'
    assert announcements['events'][0]['url'].endswith('/600519/AN1.html')


def test_invalid_identity_and_empty_source_are_rejected():
    provider = EastmoneyResearchProvider(client_for({}))
    with pytest.raises(ProviderError) as invalid:
        provider.company('https://example.com/quote')
    assert invalid.value.code == 'INVALID_SECURITY'
    with pytest.raises(ProviderError) as empty:
        provider.announcements('SH.600519')
    assert empty.value.code == 'UPSTREAM_ERROR'


def test_redirect_and_bad_json_never_become_success():
    def redirect(request):
        return httpx.Response(302, headers={'location': 'https://evil.test'}, request=request)
    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(redirect)))
    with pytest.raises(ProviderError) as exc:
        provider.company('SH.600519')
    assert exc.value.code == 'UPSTREAM_ERROR'

    def bad_json(request):
        return httpx.Response(200, content=b'not-json', request=request)
    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(bad_json)))
    with pytest.raises(ProviderError) as exc:
        provider.company('SH.600519')
    assert exc.value.code == 'INVALID_RESPONSE'


def test_money_uses_original_json_decimal_instead_of_float():
    raw = b'{"result":{"data":[{"SECURITY_CODE":"600519","REPORT_DATE":"2026-06-30","NOTICE_DATE":null,"TOTAL_OPERATE_INCOME":9007199254740991.01,"PARENT_NETPROFIT":-1.20}]}}'
    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))))
    record = provider.financials('SH.600519')['records'][0]
    assert record['total_revenue'] == '9007199254740991.01'
    assert record['parent_net_profit'] == '-1.20'
    assert record['published_at'] is None and record['publication_precision'] == 'UNKNOWN'


@pytest.mark.parametrize('method,payload', [
    ('company', {'SecurityCode': '000001', 'jbzl': {'gsmc': '错误证券'}}),
    ('financials', {'result': {'data': [{'SECURITY_CODE': '000001', 'REPORT_DATE': '2026-06-30'}]}}),
    ('announcements', {'data': {'list': [{'art_code': 'AN1', 'title': '错配', 'codes': [{'stock_code': '000001', 'market_code': '0'}]}]}}),
])
def test_every_section_checks_upstream_security_identity(method, payload):
    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))))
    with pytest.raises(ProviderError) as exc:
        getattr(provider, method)('SH.600519')
    assert exc.value.code == 'IDENTITY_MISMATCH'


@pytest.mark.parametrize('field,value,code', [
    ('REPORT_DATE', '2026-02-30', 'INVALID_DATE'),
    ('NOTICE_DATE', 'bad-date', 'INVALID_DATE'),
    ('TOTAL_OPERATE_INCOME', 'NaN', 'INVALID_NUMBER'),
    ('PARENT_NETPROFIT', 'abc', 'INVALID_NUMBER'),
])
def test_bad_source_numbers_and_dates_are_not_silent_success(field, value, code):
    row = {'SECURITY_CODE': '600519', 'REPORT_DATE': '2026-06-30', 'NOTICE_DATE': '2026-08-15', 'TOTAL_OPERATE_INCOME': 1, 'PARENT_NETPROFIT': None}
    row[field] = value
    provider = EastmoneyResearchProvider(client_for({'/api/data/v1/get': {'result': {'data': [row]}}}))
    with pytest.raises(ProviderError) as exc:
        provider.financials('SH.600519')
    assert exc.value.code == code


def test_upstream_declared_failure_and_timeout_are_explicit():
    provider = EastmoneyResearchProvider(client_for({'/api/data/v1/get': {'success': False, 'result': {'data': []}}}))
    with pytest.raises(ProviderError) as exc:
        provider.financials('SH.600519')
    assert exc.value.code == 'UPSTREAM_REJECTED'
    def timeout(request):
        raise httpx.ReadTimeout('test timeout', request=request)
    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(timeout)))
    with pytest.raises(ProviderError) as exc:
        provider.company('SH.600519')
    assert exc.value.code == 'UPSTREAM_UNAVAILABLE'


def test_fixed_get_retries_one_transient_connection_failure():
    attempts = 0

    def flaky(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError('temporary TLS failure', request=request)
        return httpx.Response(200, json={'result': {'data': [
            {'SECURITY_CODE': '600519', 'REPORT_DATE': '2026-09-30',
             'NOTICE_DATE': '2026-10-30', 'TOTAL_OPERATE_INCOME': '100.25', 'PARENT_NETPROFIT': '20.50'}
        ]}}, request=request)

    provider = EastmoneyResearchProvider(httpx.Client(transport=httpx.MockTransport(flaky)))
    result = provider.financials('SH.600519')
    assert attempts == 2
    assert result['records'][0]['total_revenue'] == '100.25'


def test_financial_yoy_and_corporate_action_dates_preserve_actual_source_fields():
    def source(request):
        if request.url.params.get('reportName') == 'RPT_SHAREBONUS_DET':
            row=dict(SECUCODE='600519.SH',SECURITY_CODE='600519',REPORT_DATE='2025-12-31',
                     NOTICE_DATE='2026-06-04',EQUITY_RECORD_DATE='2026-06-10',EX_DIVIDEND_DATE='2026-06-11',
                     IMPL_PLAN_PROFILE='10派10元',ASSIGN_PROGRESS='实施分配')
        else:
            row=dict(SECURITY_CODE='600519',REPORT_DATE='2026-09-30',NOTICE_DATE='2026-10-30',
                     TOTAL_OPERATE_INCOME='100',PARENT_NETPROFIT='-10',TOI_RATIO='92.9736361603',PARENT_NETPROFIT_RATIO='-12.5')
        return httpx.Response(200,json={'result':{'data':[row]}})
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        provider=EastmoneyResearchProvider(client)
        record=provider.financials('SH.600519')['records'][0]
        assert record['revenue_yoy']=='92.9736361603' and record['profit_yoy']=='-12.5'
        action=provider.corporate_actions('SH.600519')['items'][0]
        assert action['record_date']=='2026-06-10' and action['ex_date']=='2026-06-11'
        assert action['published_at']=='2026-06-04' and action['plan']=='10派10元'
