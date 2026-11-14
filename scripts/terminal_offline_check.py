"""在独立数据库副本中重新打开两次，验证证券搜索及行情缓存不依赖上游。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['WORKSTATION_DB'] = ':memory:'
os.environ['WORKSTATION_AUTO_DATA'] = '0'

from fastapi.testclient import TestClient
from backend.app import create_app


def main():
    target = ROOT / '.runtime' / f'terminal-offline-{uuid.uuid4().hex}.db'
    with sqlite3.connect((ROOT / '.local/workstation.db').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
    checks = []
    def forbidden():
        raise AssertionError('缓存读取不应访问外部数据源')
    for attempt in range(2):
        app = create_app(target, network_enabled=False)
        app.state.terminal.provider_factory = forbidden
        app.state.terminal.catalog.provider_factory = forbidden
        app.state.market_data.provider_factory = forbidden
        # 不进入lifespan：本检查只验证数据库重新打开，不启动任何业务任务。
        client = TestClient(app, base_url='http://127.0.0.1:8765')
        try:
            def get(path, **params):
                response = client.get('/api/v1' + path, params=params)
                assert response.status_code == 200, response.text
                return response.json()['data']
            count = get('/data/catalog')['count']
            assert count > 4000
            for query in ('600519', '贵州茅台', 'guizhoumaotai', 'gzmt'):
                assert get('/securities', q=query)[0]['id'] == 'LIVE.SH.600519'
            overview = get('/market/overview')
            assert len(overview['indices']) == 8 and all(i['price'] for i in overview['indices'])
            intraday = get('/market/indices/sh000001/intraday')
            daily = get('/market/indices/sh000001/bars', timeframe='1d')
            assert intraday['points'] and daily['bars']
            checks.append(dict(open_number=attempt + 1, count=count,
                               intraday_points=len(intraday['points']), daily_bars=len(daily['bars']),
                               real_quotes=8, four_search_modes=True, upstream_requests=0))
        finally:
            client.close()
            app.state.store.db.close()
    result = dict(database_copy=str(target), checks=checks, original_database_modified=False)
    out = ROOT / 'docs/evidence/terminal-increment/offline-check.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
