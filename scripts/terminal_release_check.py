"""行情升级验收：备份原库、校验业务记录保留、核对运行时真实接口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/terminal-increment'
DB = ROOT / '.local/workstation.db'
BASE = 'http://127.0.0.1:8765'
PROTECTED = ('watch', 'signal', 'latest_review', 'review', 'account', 'order',
             'fill', 'monitor', 'monitor_version', 'profile', 'state')


def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def snapshot():
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as db:
        records = db.execute('SELECT kind,id,payload FROM documents ORDER BY kind,id').fetchall()
        protected = [row for row in records if row[0] in PROTECTED]
        bars = db.execute('SELECT * FROM bars ORDER BY security_id,time').fetchall()
        return dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
                    counts=dict(db.execute('SELECT kind,count(*) FROM documents GROUP BY kind')),
                    protected_sha256=digest(protected), bars_sha256=digest(bars),
                    original_bars=len(bars),
                    provider_bars=db.execute('SELECT count(*) FROM provider_bars').fetchone()[0])


def get(path):
    with urlopen(BASE + path, timeout=15) as response:
        assert response.status == 200
        return json.load(response)


def before():
    OUT.mkdir(parents=True, exist_ok=True)
    state = snapshot()
    assert state['integrity'] == 'ok'
    suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / '.runtime/backups' / f'terminal-before-{suffix}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    assert not backup.exists(), '保留原备份，不覆盖'
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup) as dest:
            source.backup(dest)
            assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), before=state,
                  backup=str(backup))
    (OUT / 'release-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


def after():
    result = json.loads((OUT / 'release-check.json').read_text(encoding='utf-8'))
    state = snapshot()
    assert state['integrity'] == 'ok'
    assert state['protected_sha256'] == result['before']['protected_sha256'], '用户业务记录变化，请检查'
    assert state['bars_sha256'] == result['before']['bars_sha256'], '原有导入/演示行情变化，请检查'
    catalog = get('/api/v1/data/catalog')['data']
    assert catalog['count'] > 4000 and catalog['updated_at'] and catalog['source'], catalog
    queries = {}
    for query in ('600519', '贵州茅台', 'guizhoumaotai', 'gzmt'):
        rows = get('/api/v1/securities?q=' + quote(query))['data']
        assert rows and rows[0]['id'] == 'LIVE.SH.600519', (query, rows[:1])
        queries[query] = dict(id=rows[0]['id'], name=rows[0]['name'])
    overview = get('/api/v1/market/overview')['data']
    assert len(overview['indices']) == 8
    assert all(x['price'] is not None and x['source_time'] for x in overview['indices']), overview
    schema = get('/openapi.json')
    saved = json.loads((ROOT / 'docs/openapi.json').read_text(encoding='utf-8'))
    assert set(schema['paths']) == set(saved['paths']), '运行时接口与导出契约不一致'
    result.update(after=state, business_records_preserved=True, catalog=catalog,
                  search=queries, indices=overview['indices'],
                  refresh=get('/api/v1/data/refresh')['data'],
                  runtime_paths=len(schema['paths']), checked_after_at=datetime.now(timezone.utc).isoformat())
    (OUT / 'release-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['before', 'after'])
    args = parser.parse_args()
    before() if args.phase == 'before' else after()
