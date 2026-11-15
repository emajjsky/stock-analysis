from fastapi.testclient import TestClient
from backend.app import create_app, VERSION


def test_entry_and_api_cannot_reuse_pre_upgrade_html(tmp_path):
    app=create_app(tmp_path/'delivery.db',network_enabled=False)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        for path in ('/','/index.html','/discover','/api/v1/health','/api/v1/lab/jobs'):
            result=client.get(path)
            assert result.status_code==200
            assert result.headers['cache-control']=='no-store'
            assert result.headers['x-wangzha-version']==VERSION
        missing=client.get('/assets/old-upgrade-chunk.js')
        assert missing.status_code==404
        assert 'text/html' not in missing.headers['content-type']
