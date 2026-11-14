"""只读核对正式库、备份、HTTP接口与静态资源；不启动、停止或修改服务。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8765'


def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def snapshot(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        records = db.execute('SELECT kind,id,payload FROM documents ORDER BY kind,id').fetchall()
        bars = db.execute('SELECT * FROM bars ORDER BY security_id,time').fetchall()
        providers = db.execute('SELECT * FROM provider_bars ORDER BY security_id,time').fetchall()
        return {
            'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
            'counts': dict(db.execute('SELECT kind,count(*) FROM documents GROUP BY kind').fetchall()),
            'bars': len(bars),
            'provider_bars': len(providers),
            'documents_sha256': digest(records),
            'bars_sha256': digest(bars),
            'provider_bars_sha256': digest(providers),
        }


def get(path):
    with urlopen(BASE + path, timeout=5) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True, help='既有只读数据快照JSON')
    parser.add_argument('--backup', type=Path, required=True, help='既有SQLite在线备份')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/real-data-increment/formal-service-check.json')
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding='utf-8'))
    current = snapshot(ROOT / '.local/workstation.db')
    backup = snapshot(args.backup)
    assert current['integrity'] == backup['integrity'] == 'ok', '数据库完整性异常，停止核对'
    assert current == before, '原库有变化，保留现状，不覆盖或恢复用户数据'
    assert backup == before, '备份与原始快照不一致，请检查备份记录'
    html = get('/').decode('utf-8')
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert assets, '正式入口没有前端静态资源'
    matches = {asset: get(asset) == (ROOT / 'frontend/dist' / asset.lstrip('/')).read_bytes() for asset in assets}
    runtime = json.loads(get('/openapi.json'))
    exported = json.loads((ROOT / 'docs/openapi.json').read_text(encoding='utf-8'))
    missing = sorted(set(exported['paths']) - set(runtime['paths']))
    providers = json.loads(get('/api/v1/data/providers'))['data']
    assert snapshot(ROOT / '.local/workstation.db') == before, '只读检查期间原库有变化，请核对用户操作'
    result = {
        'checked_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'service': BASE, 'methods_used': ['GET'],
        'data_unchanged': True, 'before': before, 'after': current,
        'backup': str(args.backup.resolve()), 'backup_matches_snapshot': True,
        'backup_restored': False,
        'runtime_openapi_paths': len(runtime['paths']),
        'exported_openapi_paths': len(exported['paths']),
        'missing_runtime_paths': missing,
        'runtime_provider_ids': [provider['id'] for provider in providers],
        'served_assets_match_build': all(matches.values()), 'assets': matches,
        'backend_update_pending': bool(missing),
        'deployment_note': '最新前端静态资源已可读取；后端仍待重启，旧服务缺少真实行情同步接口。' if missing else '当前接口路径与导出快照一致；不代表全部业务已验收。',
        'restart_performed': False,
        'restart_blocked_reason': '本轮自动审批以blocked by policy拒绝停止/重启8765命令；未绕过该限制。' if missing else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
