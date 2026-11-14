"""独立浏览器验收 Agent 研究证据绑定，不操作正式 8765 或用户库。"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('AGENT_EVIDENCE_PORT', '5174'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = ROOT / 'docs/evidence/agent-evidence-increment'


def put_doc(db, kind, key, payload):
    db.execute('INSERT OR REPLACE INTO documents(kind,id,payload) VALUES(?,?,?)',
               (kind, key, json.dumps(payload, ensure_ascii=False)))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    db_path = os.environ.get('WORKSTATION_DB')
    if not db_path:
        raise SystemExit('WORKSTATION_DB未设置，拒绝使用默认数据库')
    target = Path(db_path).resolve()
    if target.parent != (ROOT / '.runtime').resolve() or not target.name.startswith('agent-evidence-acceptance-'):
        raise SystemExit('只接受.runtime内唯一命名的证据验收数据库')
    OUT.mkdir(parents=True, exist_ok=True)
    errors, server_errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='msedge')
        page = browser.new_page(viewport={'width': 1440, 'height': 950}, locale='zh-CN')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: server_errors.append(response.url) if response.status >= 500 else None)
        page.goto(BASE)
        page.wait_for_load_state('networkidle')

        def api(path, method='GET', payload=None):
            return page.evaluate("""async ({path, method, payload}) => {
              const init = {method, credentials: 'same-origin'};
              if (method !== 'GET' && method !== 'HEAD' && payload !== null) {
                init.headers = {'Content-Type': 'application/json'};
                init.body = JSON.stringify(payload);
              }
              const response = await fetch('/api/v1' + path, init);
              return {status: response.status, body: await response.json()};
            }""", {'path': path, 'method': method, 'payload': payload})

        assert api('/securities')['body']['data'] == [], '必须使用全新独立空库'
        seeded = api('/demo/seed', 'POST', {})
        assert seeded['status'] == 200, seeded
        securities = api('/securities')['body']['data']
        sid = securities[0]['id']
        monitor = api('/monitors', 'POST', {'security_id': sid, 'algorithm_id': 'trend-cross-v1',
            'enabled': True, 'parameters': {'fast': 5, 'slow': 20}, 'agent_mode': 'EXPLAIN'})
        assert monitor['status'] == 200, monitor
        generated = api('/signals/run', 'POST', {})['body']['data']['signals']
        assert generated, '合成演示应产生信号'
        signal = generated[0]

        # 研究证据只为本次独立 UI 验收预置，形状与真实同步入库一致。
        raw_hash = hashlib.sha256(b'agent-evidence-browser-v1').hexdigest()
        snapshot_id = 'browser-agent-company-v1'
        cutoff = datetime.fromisoformat(signal['confirmed_at'].replace('Z', '+00:00'))
        snapshot = {
            'id': snapshot_id, 'security_id': sid, 'section': 'company',
            'source': '独立验收研究测试替身', 'source_url': 'https://data.eastmoney.com/',
            'received_at': (cutoff-timedelta(hours=1)).isoformat(),
            'available_at': (cutoff-timedelta(hours=1)).isoformat(),
            'raw_hash': raw_hash,
            'data': {'business': '独立验收研究资料，不构成投资结论', 'facts': []},
        }
        with sqlite3.connect(db_path) as db:
            put_doc(db, 'research_snapshot', snapshot_id, snapshot)
            put_doc(db, 'research_current', sid + ':company', {'id': sid + ':company', 'snapshot_id': snapshot_id})
            db.commit()

        reviewed = api('/reviews', 'POST', {'signal_id': signal['id'], 'demo': True})
        assert reviewed['status'] == 200, reviewed
        review = reviewed['body']['data']
        assert review['mode'] == 'RULE_DEMO'
        assert review['model_request_attempted'] is False
        assert review['research_evidence_snapshot'][0]['included'] is True

        page.reload()
        page.wait_for_load_state('networkidle')
        page.locator('nav button').filter(has_text='提示与复核').click()
        expect(page.locator('.research-binding')).to_be_visible()
        expect(page.locator('.research-evidence-item')).to_have_count(1)
        expect(page.locator('.research-evidence-item')).to_contain_text('已纳入')
        page.locator('.research-evidence-item summary').click()
        expect(page.locator('.research-evidence-detail')).to_contain_text(raw_hash)
        expect(page.locator('.research-evidence-detail a')).to_have_attribute('href', 'https://data.eastmoney.com/')
        expect(page.locator('.research-model-note')).to_contain_text('规则演示，非 AI')
        expect(page.locator('.research-empty')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT / '01-agent-evidence-binding.png'), full_page=True)
        checks = ['空库与独立合成数据', '真实API保存复核快照', '单条纳入证据与展开哈希',
                  'HTTPS来源链接', '规则演示明确非AI', '1440宽度无整页横向溢出']

        revised = {**snapshot, 'id': 'browser-agent-company-v2',
            'raw_hash': hashlib.sha256(b'agent-evidence-browser-v2').hexdigest(),
            'received_at': (cutoff+timedelta(hours=1)).isoformat(),
            'available_at': (cutoff+timedelta(hours=1)).isoformat(),
            'data': {'business': '晚于信号的测试修订，不得纳入历史上下文', 'facts': []}}
        with sqlite3.connect(target) as db:
            put_doc(db, 'research_snapshot', revised['id'], revised)
            put_doc(db, 'research_current', sid+':company', {'id':sid+':company','snapshot_id':revised['id']})
            db.commit()
        page.reload()
        page.wait_for_load_state('networkidle')
        page.locator('nav button').filter(has_text='提示与复核').click()
        expect(page.locator('.binding-warning')).to_contain_text('请重新复核')
        assert api('/signals')['body']['data'][0]['review']['research_binding_status']=='STALE'
        page.screenshot(path=str(OUT/'02-agent-stale-review.png'),full_page=True)
        checks.append('修订后旧复核STALE与醒目提示')

        page.get_by_role('button',name='显式体验规则复核演示（非 AI）',exact=True).click()
        expect(page.locator('.research-evidence-item')).to_have_count(2)
        expect(page.locator('.binding-warning')).to_have_count(0)
        expect(page.locator('.research-evidence-item').nth(1)).to_contain_text('已排除')
        page.locator('.research-evidence-item').nth(1).locator('summary').click()
        expect(page.locator('.research-evidence-item').nth(1)).to_contain_text('避免未来信息')
        new_review=api('/signals')['body']['data'][0]['review']
        assert new_review['research_binding_status']=='CURRENT'
        assert new_review['research_context_snapshot']['company']==snapshot['data']
        assert new_review['model_request_attempted'] is False
        checks.append('显式重审选择旧版本并排除未来修订')
        page.set_viewport_size({'width':1280,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT/'03-agent-evidence-1280.png'),full_page=True)
        checks.append('1280宽度展开证据无整页横向溢出')

        # 关闭监测前不创建模拟账户，证明证据展示与交易域分离。
        assert api('/sim/accounts')['body']['data'] == []
        checks.append('未创建模拟账户或订单')
        assert not errors and not server_errors, (errors,server_errors)
        browser_version=browser.version
        browser.close()

    result = {
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'browser':browser_version, 'checks':checks, 'passed':len(checks), 'page_errors':errors,
        'server_errors': server_errors, 'formal_database_modified': False,
        'research_mode': '独立临时库预置证据', 'review_mode': 'RULE_DEMO',
        'account_count': 0,
        'upstream_is_live':False, 'model_is_real':False, 'database':str(target),
    }
    (OUT / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
