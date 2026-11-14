"""备份正式库并核对恢复后的服务，只读取HTTP业务端点。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/automation-increment'
BASE = 'http://127.0.0.1:8765'


def snapshot():
    with sqlite3.connect((ROOT / '.local/workstation.db').as_uri() + '?mode=ro', uri=True) as db:
        records = db.execute('SELECT kind,id,payload FROM documents ORDER BY kind,id').fetchall()
        counts = dict(db.execute('SELECT kind,count(*) FROM documents GROUP BY kind').fetchall())
        bars = db.execute('SELECT * FROM bars ORDER BY security_id,time').fetchall()
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    return {'counts': counts, 'bars': len(bars), 'integrity': integrity,
            'documents_sha256': hashlib.sha256(json.dumps(records, ensure_ascii=False).encode()).hexdigest(),
            'bars_sha256': hashlib.sha256(json.dumps(bars, ensure_ascii=False).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['before', 'after'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'restart-check.json'
    if args.phase == 'before':
        state = snapshot()
        assert state['integrity'] == 'ok'
        backup = ROOT / '.runtime/backups/automation-before-restart-20261027.db'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise SystemExit('备份已存在，保留原备份；请先核对记录。')
        with sqlite3.connect((ROOT / '.local/workstation.db').as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(backup) as dest:
                source.backup(dest)
                assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        result = {'before': state, 'backup': str(backup)}
    else:
        result = json.loads(target.read_text(encoding='utf-8'))
        after = snapshot()
        assert after == result['before'], '正式库内容变化，需核对而非覆盖用户数据'
        with urlopen(BASE + '/', timeout=5) as response:
            html = response.read().decode()
            assert response.status == 200
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        assert assets
        for asset in assets:
            with urlopen(BASE + asset, timeout=5) as response:
                assert response.status == 200
                assert response.read() == (ROOT / 'frontend/dist' / asset.lstrip('/')).read_bytes()
        def get(path):
            with urlopen(BASE + '/api/v1' + path, timeout=5) as response:
                return json.load(response)['data']
        config = get('/automation')
        assert config['enabled'] is False and config['auto_review'] is False and config['worker_running'] is True
        result.update(after=after, data_unchanged=True, assets=assets,
            securities=len(get('/securities')), watchlists=len(get('/watchlists')),
            simulation_accounts=len(get('/sim/accounts')), automation=config,
            methods_used=['GET'], html_status=200, assets_match_current_build=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
