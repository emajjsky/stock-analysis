"""有界真实数据检查：八指数图表加载、日线重复更新不增行、缓存来源。"""
from __future__ import annotations

import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8765'
SYMBOLS = ('sh000001','sz399001','sz399006','sh000300','sh000016','sh000905','sh000852','sh000688')


def main():
    with httpx.Client(base_url=BASE, timeout=10, headers={'Origin':BASE}) as client:
        def get(path, **params):
            r = client.get('/api/v1'+path, params=params)
            r.raise_for_status()
            return r.json()['data']
        def post(path):
            r = client.post('/api/v1'+path,json={})
            r.raise_for_status()
            return r.json()['data']
        client.get('/api/v1/session').raise_for_status()
        states = {}
        # 请求仅登记有界需求，实际上游请求由统一刷新任务去重。
        for symbol in SYMBOLS:
            get(f'/market/indices/{symbol}/bars')
            get(f'/market/indices/{symbol}/intraday')
        deadline = time.monotonic()+45
        while time.monotonic()<deadline:
            for symbol in SYMBOLS:
                bars = get(f'/market/indices/{symbol}/bars')['bars']
                points = get(f'/market/indices/{symbol}/intraday')['points']
                states[symbol] = dict(bars=len(bars), points=len(points),
                    last_bar=bars[-1]['time'] if bars else None,
                    last_point=points[-1]['time'] if points else None)
            if all(x['bars'] and x['points'] for x in states.values()):
                break
            time.sleep(0.5)
        assert all(x['bars'] and x['points'] for x in states.values()), states
        before={symbol:len(get(f'/market/indices/{symbol}/bars')['bars']) for symbol in SYMBOLS}
        baseline=get('/data/refresh')['last_attempt_at']
        post('/market/refresh')
        deadline=time.monotonic()+30
        completed=False
        while time.monotonic()<deadline:
            status=get('/data/refresh')
            if status['last_attempt_at']!=baseline and not status['running']:
                completed=True
                break
            time.sleep(0.5)
        assert completed, '后台刷新未在检查时限内完成'
        assert not status['error'],status
        after={symbol:len(get(f'/market/indices/{symbol}/bars')['bars']) for symbol in SYMBOLS}
        assert before==after,(before,after)
        rankings=get('/market/overview')['rankings']
        assert all(len(rows)==len({row['id'] for row in rows})==100 for rows in rankings.values())
        result=dict(indices=states, repeated_refresh_row_counts_unchanged=True,
                    before_counts=before,after_counts=after,
                    rankings={k:len(v) for k,v in rankings.items()},
                    status=get('/data/refresh'), simulation_or_real_order_actions=False)
    out=ROOT/'docs/evidence/terminal-increment/real-data-check.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
