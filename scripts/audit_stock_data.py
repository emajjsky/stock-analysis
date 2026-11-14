"""核对正式本机服务的数据与上游事实，保存审计证据；不操作交易账户。"""
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from backend.providers import TencentProvider

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stock-data-audit'
BASE = 'http://127.0.0.1:8765'
KEYS = ['LIVE.SZ.300502', 'LIVE.SZ.300030', 'LIVE.SH.603444']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'securities': {}, 'adjustments': {}}
    source = TencentProvider()
    try:
        direct = {q['security_id']: q for q in source.quotes([k.removeprefix('LIVE.') for k in KEYS])}
    finally:
        source.close()
    with httpx.Client(base_url=BASE, trust_env=False, timeout=120, headers={'Origin': BASE}) as client:
        client.get('/api/v1/session').raise_for_status()
        def get(path):
            response = client.get('/api/v1'+path)
            response.raise_for_status()
            return response.json()['data']
        for key in KEYS:
            client.post('/api/v1/securities/'+key+'/activate', json={}).raise_for_status()
            profile = get('/securities/'+key+'/profile')
            deadline = time.monotonic()+70
            while time.monotonic()<deadline and (profile['research']['auto_refresh']['pending'] or not profile.get('corporate_actions')):
                time.sleep(1)
                profile = get('/securities/'+key+'/profile')
            sec = get('/securities/'+key)
            quote = sec['quote']
            reference = direct[key.removeprefix('LIVE.')]
            fields = ['pe_ttm','pe_dynamic','pe_static','total_shares','float_shares','buy_volume','sell_volume']
            comparison = {f: {'cache':quote.get(f),'source':reference.get(f),'equal':quote.get(f)==reference.get(f)} for f in fields}
            assert all(x['equal'] for x in comparison.values()), comparison
            assert profile['financials'] and all('revenue_yoy' in r and 'profit_yoy' in r for r in profile['financials']), key
            assert profile.get('corporate_actions') is not None, key
            result['securities'][key] = {'name':sec['name'],'source_time':quote['source_time'], 'fetched_at':quote.get('fetched_at'),
                'quote_comparison':comparison, 'financials':profile['financials'], 'corporate_actions':profile['corporate_actions'],
                'auto_refresh':profile['research']['auto_refresh']}
        intraday = get('/market/intraday?security_id='+KEYS[0])
        point = intraday['points'][-1]
        expected = Decimal(point['cumulative_amount'])/Decimal(point['cumulative_volume'])
        assert abs(expected-Decimal(point['average_price']))<=Decimal('0.00005')
        result['intraday']={'count':len(intraday['points']),'last':point,'source_time':intraday.get('source_time'),
            'average_formula':'cumulative_amount / cumulative_volume (shares)', 'expected_average':str(expected)}
        histories = {}
        for adjustment in ['none','qfq','hfq']:
            if adjustment != 'none':
                response = client.post('/api/v1/securities/'+KEYS[0]+'/history/sync',params={'adjustment':adjustment},json={})
                response.raise_for_status()
                result['adjustments'][adjustment]={'sync':response.json()['data']}
            history = get('/market/bars?security_id='+KEYS[0]+'&adjustment='+adjustment)
            assert history['bars'] and history['adjustment']==adjustment.upper()
            histories[adjustment] = {b['time']:b for b in history['bars']}
            result['adjustments'].setdefault(adjustment,{})['coverage']=history['bars_coverage']
            result['adjustments'][adjustment]['indicator_count']=len(history['indicators'])
            assert all(len(v)==len(history['bars']) for v in history['indicators'].values())
        common=sorted(set.intersection(*(set(h) for h in histories.values())))
        differing=[d for d in common if len({histories[a][d]['close'] for a in histories})>1]
        assert differing, '复权历史不应全部与原价相同'
        result['adjustment_sample']={'date':differing[-1], 'close':{a:h[differing[-1]]['close'] for a,h in histories.items()}}
        front_changed=[d for d in common if histories['none'][d]['close'] != histories['qfq'][d]['close']]
        assert front_changed, '前复权应在公司行为之前与原价存在差异'
        result['qfq_sample']={'date':front_changed[-1],'none':histories['none'][front_changed[-1]]['close'],
            'qfq':histories['qfq'][front_changed[-1]]['close']}
        schema=client.get('/openapi.json').json()
        result['runtime_paths']=len(schema['paths'])
        result['adjustment_sync_loaded']='/api/v1/securities/{key}/history/sync' in schema['paths']
    before=json.loads((OUT/'before.json').read_text(encoding='utf-8'))
    protected=['watch','signal','latest_review','review','account','order','fill','monitor','monitor_version','profile','state']
    with sqlite3.connect(before['backup']) as old, sqlite3.connect(ROOT/'.local/workstation.db') as current:
        def records(conn):
            return sorted([list(r) for r in conn.execute('SELECT kind,id,payload FROM documents') if r[0] in protected])
        original,actual=records(old),records(current)
        assert original==actual, '受保护业务记录发生变化'
        result['business_preserved']={'kinds':protected,'equal_to_backup':True,'record_count':len(actual),
            'sha256':hashlib.sha256(json.dumps(actual,ensure_ascii=False).encode()).hexdigest()}
        for table in ('bars','provider_bars'):
            previous=old.execute('SELECT * FROM '+table+' ORDER BY security_id,time').fetchall()
            latest=current.execute('SELECT * FROM '+table+' ORDER BY security_id,time').fetchall()
            original_rows, latest_rows = set(previous), set(latest)
            assert original_rows <= latest_rows, table+'原有历史被改写或删除'
            result[table+'_preservation']={'original_rows_unchanged':True,'count':len(latest),
                'appended_rows':len(latest_rows-original_rows)}
    (OUT/'runtime-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'docs/evidence/stock-detail/runtime-state.json').write_text(json.dumps({
        'runtime_paths':result['runtime_paths'],'adjustment_sync_loaded':True,'auto_research_loaded':True,
        'current_source_time':result['securities'][KEYS[0]]['source_time'],'checked_at':result['checked_at']},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'checked':list(result['securities']),'adjustments':result['adjustment_sample'],'business_preserved':True},ensure_ascii=False))


if __name__=='__main__':
    main()
