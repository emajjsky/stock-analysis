from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app, indicators


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_API_BASE", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    app = create_app(tmp_path / "test.db")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/session").status_code == 200
        client.headers["Origin"] = "http://127.0.0.1:8765"
        yield client
    app.state.store.db.close()


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def seeded(client):
    data(client.post("/api/v1/demo/seed", json={}))
    return data(client.get("/api/v1/securities"))[0]["id"]


def account(client, cash="123456.78"):
    return data(client.post("/api/v1/sim/accounts", json={"name": "自定义测试账户", "initial_cash": cash, "mode": "DEMO"}))["id"]


def order(client, aid, sid, side="BUY", qty=100, purpose="BASE", key="test-order"):
    return client.post(f"/api/v1/sim/accounts/{aid}/orders", json={"security_id": sid, "side": side, "quantity": qty, "purpose": purpose, "idempotency_key": key})


def detail(client, aid):
    return data(client.get(f"/api/v1/sim/accounts/{aid}"))


def test_empty_database_has_no_fake_assets_or_recommendations(client):
    assert data(client.get("/api/v1/dashboard"))["security_count"] == 0
    assert data(client.get("/api/v1/sim/accounts")) == []
    assert data(client.get("/api/v1/recommendations")) == []
    assert data(client.post("/api/v1/recommendations/run", json={})) == []
    evaluation = data(client.post("/api/v1/evaluations/run", json={}))
    assert evaluation["sample_size"] == 0
    assert evaluation["metrics"] == []
    assert evaluation["status"] == "PENDING"
    assert not data(client.get("/api/v1/live/status"))["enabled"]


def test_origin_host_session_and_unknown_api(client):
    assert client.post("/api/v1/demo/seed", headers={"Origin": "https://evil.invalid"}, json={}).status_code == 403
    assert client.get("/api/v1/session", headers={"Host": "evil.invalid"}).status_code == 403
    client.headers.pop("Origin")
    assert client.post("/api/v1/demo/seed", json={}).json()["error"]["code"] == "ORIGIN_REQUIRED"
    client.headers["Origin"] = "http://127.0.0.1:8765"
    client.app.state.sessions.clear()
    assert client.post("/api/v1/demo/seed", json={}).status_code == 401
    missing = client.get("/api/v1/unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_test_origin_port_requires_explicit_test_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSTATION_TEST_PORT", raising=False)
    app = create_app(tmp_path / "origin-port.db")
    with TestClient(app, base_url="http://127.0.0.1:5174") as test_client:
        assert test_client.get("/api/v1/session").status_code == 200
        assert test_client.post("/api/v1/demo/seed", headers={"Origin":"http://127.0.0.1:5174"}, json={}).status_code == 403
        monkeypatch.setenv("WORKSTATION_TEST_PORT", "5174")
        assert test_client.post("/api/v1/demo/seed", headers={"Origin":"http://127.0.0.1:5174"}, json={}).status_code == 200
    app.state.store.db.close()


def test_seed_idempotency_and_persistence(client):
    sid = seeded(client)
    first = data(client.post("/api/v1/watchlists", json={"security_id": sid, "tag": "长线"}))
    second = data(client.post("/api/v1/watchlists", json={"security_id": sid}))
    assert first["id"] == second["id"]
    assert data(client.post("/api/v1/demo/seed", json={}))["loaded"] is False
    assert len(data(client.get("/api/v1/watchlists"))) == 1
    data(client.patch("/api/v1/watchlists/"+first["id"], json={"monitor_enabled": True}))
    assert data(client.get("/api/v1/monitors"))[0]["enabled"] is True
    data(client.patch("/api/v1/watchlists/"+first["id"], json={"monitor_enabled": False}))
    assert data(client.get("/api/v1/monitors"))[0]["enabled"] is False


def test_t_plus_one_and_idempotency_conflict(client):
    sid = seeded(client); aid = account(client)
    buy = data(order(client, aid, sid))
    assert buy["status"] == "FILLED"
    assert data(order(client, aid, sid))["id"] == buy["id"]
    assert order(client, aid, sid, qty=200).status_code == 409
    before = detail(client, aid)
    assert before["positions"][0]["quantity"] == 100
    assert before["positions"][0]["sellable"] == 0
    rejected = order(client, aid, sid, side="SELL", key="same-day-sell")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "T_PLUS_ONE"
    assert detail(client, aid)["account"]["cash"] == before["account"]["cash"]
    data(client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}))
    sell = data(order(client, aid, sid, side="SELL", key="next-day-sell"))
    assert sell["quote_as_of"][:10] == sell["trade_date"]
    assert sell["price"] != buy["price"]
    assert detail(client, aid)["positions"] == []


def test_advance_uses_only_existing_demo_dates(client):
    sid = seeded(client); aid = account(client)
    dates = []
    for _ in range(5):
        dates.append(data(client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}))["trade_date"])
    assert dates == sorted(dates)
    assert client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}).status_code == 409
    data(order(client, aid, sid))
    assert detail(client, aid)["account"]["trade_date"] == dates[-1]


def test_continuous_t_comparison_and_today_accounting(client):
    sid = seeded(client); aid = account(client)
    data(order(client, aid, sid, qty=1000, key="base"))
    assert detail(client, aid)["comparison"]["t_increment"] == "0.00"
    data(client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}))
    sell = data(order(client, aid, sid, side="SELL", qty=200, purpose="T", key="T-sell"))
    open_state = detail(client, aid)
    assert open_state["comparison"]["open_t_quantity"] == 200
    assert Decimal(open_state["comparison"]["t_increment"]) == -Decimal(sell["fee"])
    data(client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}))
    buy = data(order(client, aid, sid, qty=200, purpose="T", key="T-rebuy"))
    final = detail(client, aid)
    expected = (Decimal(sell["price"])-Decimal(buy["price"]))*200-Decimal(sell["fee"])-Decimal(buy["fee"])
    assert Decimal(final["comparison"]["t_increment"]) == expected
    assert final["comparison"]["open_t_quantity"] == 0
    assert final["comparison"]["status"] == "COMPARABLE"
    actual_today = Decimal(final["comparison"]["today_actual_pnl"])
    baseline_today = Decimal(final["comparison"]["today_baseline_pnl"])
    assert Decimal(final["comparison"]["today_t_increment"]) == actual_today-baseline_today
    assert Decimal(final["account"]["equity"])-Decimal(final["comparison"]["baseline_equity"]) == expected


def test_buy_first_t_inventory_capacity(client):
    sid = seeded(client); aid = account(client)
    assert order(client, aid, sid, purpose="T").status_code == 409
    data(order(client, aid, sid, key="base"))
    data(client.post(f"/api/v1/sim/accounts/{aid}/advance-day", json={}))
    data(order(client, aid, sid, purpose="T", key="t-buy"))
    assert order(client, aid, sid, purpose="T", key="t-buy-excess").status_code == 409


def test_import_bad_rows_atomic_partial_and_conflict(client):
    raw = "代码,名称,日期,开盘,最高,最低,收盘,成交量\n000001,测试企业,2026-10-22,10,11,9,10.5,10000\n000001,测试企业,2026-10-23,10,9,11,10,10000\n"
    preview = data(client.post("/api/v1/data/imports/preview", files={"file": ("历史.csv", raw.encode("gb18030"), "text/csv")}))
    assert preview["valid_rows"] == 1 and preview["invalid_rows"] == 1
    assert preview["errors"][0]["row"] == 3
    assert not preview["can_commit"]
    path = f"/api/v1/data/imports/{preview['id']}/commit"
    assert client.post(path, json={}).status_code == 422
    assert data(client.get("/api/v1/securities")) == []
    assert data(client.post(path, json={"allow_partial": True}))["imported_rows"] == 1
    assert client.post(path, json={"allow_partial": True}).status_code == 409
    changed = raw.splitlines()[0]+"\n000001,测试企业,2026-10-22,10,12,9,11,10000\n"
    p2 = data(client.post("/api/v1/data/imports/preview", files={"file": ("修改.csv", changed.encode(), "text/csv")}))
    assert client.post(f"/api/v1/data/imports/{p2['id']}/commit", json={}).status_code == 409
    sec = data(client.get("/api/v1/securities"))[0]
    assert sec["code"] == "000001"
    assert sec["quote"]["price"] == "10.50"
    aid = data(client.post("/api/v1/sim/accounts", json={"name": "导入研究", "initial_cash": "50000", "mode": "IMPORTED"}))["id"]
    assert order(client, aid, sec["id"]).json()["error"]["code"] == "UNKNOWN_ADJUSTMENT"


def test_algorithm_signals_reviews_and_deduplicated_notifications(client):
    sid = seeded(client)
    recs = data(client.post("/api/v1/recommendations/run", json={}))
    assert len(recs) == 6
    assert all(isinstance(r["score"], str) for r in recs)
    data(client.post("/api/v1/monitors", json={"security_id": sid, "algorithm_id": "trend-cross-v1", "enabled": True, "parameters": {}, "agent_mode": "FILTER"}))
    generated = data(client.post("/api/v1/signals/run", json={}))
    assert generated["generated"] == 1
    signal = generated["signals"][0]
    assert signal["input_snapshot_hash"]
    assert data(client.post("/api/v1/signals/run", json={}))["generated"] == 0
    assert len(data(client.get("/api/v1/notifications"))) == 1
    review = data(client.post("/api/v1/reviews", json={"signal_id": signal["id"]}))
    assert review["verdict"] == "WAIT" and review["mode"] == "UNAVAILABLE"
    assert review["input_snapshot_hash"] == signal["input_snapshot_hash"]
    assert review["research_evidence_snapshot"] == []
    assert review["research_binding_status"] == "CURRENT"
    demo_review = data(client.post("/api/v1/reviews", json={"signal_id": signal["id"], "demo": True}))
    assert demo_review["mode"] == "RULE_DEMO"
    assert demo_review["verdict"] == "WAIT"  # 历史演示信号已过期
    assert "非AI" in demo_review["summary"]


def test_two_selection_algorithms_rank_distinct_risk_profiles(client):
    """更高动量但更宽日内振幅，与平稳上涨对照，验证两种排序确实执行不同公式。"""
    from datetime import date,timedelta
    store=client.app.state.store
    with store.lock,store.db:
        for sid,name,total_rise,range_width in [("SH.600101","高波动趋势",Decimal("3"),Decimal("4")),("SH.600102","平稳趋势",Decimal("2"),Decimal("0.02"))]:
            store.put("security",dict(id=sid,code=sid[3:],name=name,exchange="SSE",sector="测试",status="IMPORTED_UNVERIFIED"))
            for i in range(21):
                close=Decimal("20")+total_rise*Decimal(i)/20
                ds=(date(2026,9,1)+timedelta(days=i)).isoformat()
                store.db.execute("INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,ds,str(close),str(close+range_width),str(close-range_width),str(close),10000,str(close*10000),"测试OHLCV","IMPORTED"))
    algorithms=data(client.get("/api/v1/algorithms"))
    assert {a["id"] for a in algorithms if a["kind"]=="SELECTION"}=={"rank-momentum-v1","trend-stability-v1"}
    momentum=data(client.post("/api/v1/recommendations/run",json={}))
    stability=data(client.post("/api/v1/recommendations/run",json={"algorithm_id":"trend-stability-v1"}))
    assert momentum[0]["security"]["id"]=="SH.600101"
    assert stability[0]["security"]["id"]=="SH.600102"
    assert all(r["algorithm_id"]=="rank-momentum-v1" for r in momentum)
    assert all(r["algorithm_id"]=="trend-stability-v1" for r in stability)
    assert {r["security"]["id"]:r["score"] for r in momentum}!={r["security"]["id"]:r["score"] for r in stability}
    assert any("ATR" in reason for reason in stability[0]["reasons"])
    assert any("最大回撤" in reason for reason in stability[0]["reasons"])
    assert any("低历史波动" in risk for risk in stability[0]["risks"])
    assert stability[0]["algorithm_version"]=="1.0.0"
    assert stability[0]["data_as_of"]=="2026-09-21T07:00:00Z"
    assert len(stability[0]["input_snapshot_hash"])==64
    repeated=data(client.post("/api/v1/recommendations/run",json={"algorithm_id":"trend-stability-v1"}))
    assert [r["input_snapshot_hash"] for r in repeated]==[r["input_snapshot_hash"] for r in stability]
    assert all("胜率" in r["reasons"][-1] for r in repeated)


@pytest.mark.parametrize("algorithm_id",["rank-momentum-v1","trend-stability-v1"])
def test_both_selection_algorithms_keep_empty_database_empty(client,algorithm_id):
    assert data(client.post("/api/v1/recommendations/run",json={"algorithm_id":algorithm_id}))==[]
    assert data(client.get("/api/v1/recommendations"))==[]
    assert data(client.get("/api/v1/securities"))==[]


def test_unknown_selection_algorithm_is_rejected_without_replacing_saved_results(client):
    seeded(client)
    original=data(client.post("/api/v1/recommendations/run",json={"algorithm_id":"trend-stability-v1"}))
    for algorithm_id in ("unknown-model","trend-cross-v1"):
        response=client.post("/api/v1/recommendations/run",json={"algorithm_id":algorithm_id})
        assert response.status_code==422
        assert response.json()["error"]["code"]=="INVALID_ALGORITHM"
    assert data(client.get("/api/v1/recommendations"))==original


def test_indicators_warmup_and_constant_series():
    bars = [dict(open="10",high="11",low="9",close="10",volume=100,amount="1000") for _ in range(40)]
    result = indicators(bars)
    assert result["ma5"][:4] == [None]*4
    assert result["ma5"][4] == "10.00"
    assert result["ma20"][18] is None and result["ma20"][19] == "10.00"
    assert result["rsi14"][13] is None and result["rsi14"][14] == "50.00"
    assert result["atr14"][12] is None and result["atr14"][13] == "2.00"
    assert result["macd"][24] is None and result["macd"][25] == "0.00"


def test_bearish_signal_explains_supporting_sell_conditions(client):
    sid=seeded(client)
    store=client.app.state.store
    dates=[row["time"] for row in store.bars(sid)[-10:]]
    with store.lock,store.db:
        for i,day in enumerate(dates):
            value=str(100-i)
            store.db.execute("UPDATE bars SET open=?,high=?,low=?,close=? WHERE security_id=? AND time=?",(value,value,value,value,sid,day))
    data(client.post("/api/v1/monitors",json={"security_id":sid,"algorithm_id":"trend-cross-v1","enabled":True,"parameters":{"fast":3,"slow":5},"agent_mode":"EXPLAIN"}))
    signal=data(client.post("/api/v1/signals/run",json={}))["signals"][0]
    assert signal["kind"]=="SELL"
    assert all(condition["operator"]=="<" and condition["passed"] is True for condition in signal["conditions"])
    assert all("低于" in condition["label"] for condition in signal["conditions"])
    review=data(client.post("/api/v1/reviews",json={"signal_id":signal["id"],"demo":True}))
    assert len(review["supporting_evidence"])==2
    assert review["opposing_evidence"]==[]


def test_real_persistence_across_app_restart(tmp_path):
    path = tmp_path / "persist.db"
    app = create_app(path)
    with TestClient(app,base_url="http://127.0.0.1:8765") as c:
        c.get("/api/v1/session"); c.headers["Origin"]="http://127.0.0.1:8765"
        sid=seeded(c)
        data(c.post("/api/v1/watchlists",json={"security_id":sid,"group_name":"研究组"}))
    app.state.store.db.close()
    second=create_app(path)
    with TestClient(second,base_url="http://127.0.0.1:8765") as c:
        items=data(c.get("/api/v1/watchlists"))
        assert len(items)==1 and items[0]["group_name"]=="研究组"
        assert len(data(c.get("/api/v1/securities")))==6
    second.state.store.db.close()


@pytest.mark.parametrize("price,volume,amount", [("1e100","100","1000"),("10","1e100","1000"),("10","100","1e100"),("10.1234567","100","1000"),("NaN","100","1000")])
def test_csv_extreme_decimals_are_reported_as_bad_rows(client,price,volume,amount):
    raw=f"code,date,open,high,low,close,volume,amount\n000001,2026-10-23,{price},{price},{price},{price},{volume},{amount}\n"
    preview=data(client.post("/api/v1/data/imports/preview",files={"file":("extreme.csv",raw.encode(),"text/csv")}))
    assert preview["valid_rows"]==0 and preview["invalid_rows"]==1
    assert preview["errors"][0]["row"]==2
    assert not preview["can_commit"]
    assert data(client.get("/api/v1/securities"))==[]


def test_csv_supported_precision_is_not_silently_rounded(client):
    raw="code,date,open,high,low,close,volume,amount\n000001,2026-10-23,10.123456,10.123456,10.123456,10.123456,100,1012.3456\n"
    preview=data(client.post("/api/v1/data/imports/preview",files={"file":("precision.csv",raw.encode(),"text/csv")}))
    assert preview["sample"][0]["close"]=="10.123456"
    assert preview["sample"][0]["amount"]=="1012.3456"
    data(client.post(f"/api/v1/data/imports/{preview['id']}/commit",json={}))
    bars=data(client.get("/api/v1/market/bars",params={"security_id":"SZ.000001"}))["bars"]
    assert bars[0]["close"]=="10.123456"


def test_real_http_parallel_refresh_has_no_cross_query_corruption(tmp_path):
    """重现浏览器选股后并发十路刷新，共享SQLite连接曾交叉返回错误行。"""
    import asyncio
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    app=create_app(tmp_path/"parallel.db")
    listener=socket.socket()
    listener.bind(("127.0.0.1",0))
    listener.listen(128)
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level="error",lifespan="off"))
    worker=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    worker.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:
        time.sleep(0.01)
    assert server.started

    async def exercise():
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",headers={"Origin":"http://127.0.0.1:5173"},timeout=10,trust_env=False) as c:
            assert (await c.get("/api/v1/session")).status_code==200
            assert (await c.post("/api/v1/demo/seed",json={})).status_code==200
            paths=["dashboard","securities","watchlists","algorithms","monitors","recommendations","signals","reviews","notifications","sim/accounts"]
            for _ in range(20):
                assert (await c.post("/api/v1/recommendations/run",json={})).status_code==200
                results=await asyncio.gather(*(c.get("/api/v1/"+path) for path in paths))
                assert all(r.status_code==200 for r in results),[(str(r.url),r.text) for r in results if r.status_code!=200]
                assert results[0].json()["data"]["security_count"]==6
                assert len(results[1].json()["data"])==6
                assert results[4].json()["data"]==[]
                recommendations=results[5].json()["data"]
                assert len(recommendations)==6
                assert len({r["security"]["id"] for r in recommendations})==6
    try:
        asyncio.run(exercise())
    finally:
        server.should_exit=True
        worker.join(timeout=5)
        listener.close()
        app.state.store.db.close()
    assert not worker.is_alive()
