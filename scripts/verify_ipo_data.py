"""发行资料身份、单位、运行时覆盖和用户业务记录保留核验。"""
import json
from pathlib import Path
import sqlite3
import time
import httpx

out=Path('docs/evidence/ipo-web')
out.mkdir(parents=True,exist_ok=True)
results=[]
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=10) as c:
    c.get('/api/v1/session')
    for section in ['listed','pending','apply','review','disclosure','bonds','news']:
        path=f'/api/v1/market/ipo?section={section}'
        for _ in range(8):
            r=c.get(path);r.raise_for_status();d=r.json()['data']
            if d['status']=='READY' and not d['refreshing']:break
            time.sleep(1)
        assert d['status']=='READY' and not d['error'],(section,d.get('error'))
        results.append(dict(section=section,total=d['total'],loaded=len(d['rows']),source=d['source'],
            fetched_at=d['fetched_at'],schema_version=d.get('schema_version'),sample=d['rows'][:1]))
    d=c.get('/api/v1/market/ipo?section=listed').json()['data']
    assert d['schema_version']==3
    assert any(r['source_time'] and r['volume_lots'] and r['market_cap'] for r in d['rows'])
    d=c.get('/api/v1/market/ipo?section=apply&board=bj').json()['data']
    assert all(r['security_id'] is None and r['required_cap'] is None for r in d['rows'])
    assert all(r['security_id'] is None for r in c.get('/api/v1/market/ipo?section=pending').json()['data']['rows'])
with sqlite3.connect('.local/workstation.db') as db:
    kinds=('watch','account','position','order','trade','rule','signal')
    rows=db.execute('SELECT kind,id,payload FROM documents WHERE kind IN ('+','.join('?' for _ in kinds)+') ORDER BY kind,id',kinds).fetchall()
    before=json.loads(Path('.local/ipo-business-before.json').read_text(encoding='utf-8'))
    preserved=json.loads(json.dumps(rows))==before
    assert preserved,'用户业务数据发生变化，请复核'
    result=dict(coverage=results,business_records_preserved=preserved,business_record_count=len(rows),
        database_integrity=db.execute('PRAGMA integrity_check').fetchone()[0])
    assert result['database_integrity']=='ok'
(out/'data-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(coverage=len(results),business_records_preserved=preserved),ensure_ascii=False))
