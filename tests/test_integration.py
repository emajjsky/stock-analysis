"""主任务独立验收：跨模块契约、持久化与资金不变量。"""
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app import create_app

ORIGIN = {"Origin": "http://127.0.0.1:8765"}


def data(response, expected=200):
    assert response.status_code == expected, response.text
    body = response.json()
    assert body["meta"]["request_id"]
    return body["data"] if expected == 200 else body["error"]


def client_for(path):
    client = TestClient(create_app(path), base_url="http://127.0.0.1:8765", headers=ORIGIN)
    data(client.get("/api/v1/session"))
    return client


def test_full_research_and_persistence(tmp_path, monkeypatch):
    for key in ("AGENT_API_BASE", "AGENT_MODEL", "AGENT_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "research.db"
    with client_for(path) as c:
        assert data(c.get("/api/v1/securities")) == []
        assert data(c.get("/api/v1/sim/accounts")) == []
        assert data(c.post("/api/v1/demo/seed", json={}))['loaded']
        assert not data(c.post("/api/v1/demo/seed", json={}))['loaded']
        securities = data(c.get("/api/v1/securities"))
        sid = securities[0]["id"]
        recs = data(c.post("/api/v1/recommendations/run", json={}))
        assert len(recs) == len(securities)
        assert isinstance(recs[0]["score"], str)
        watch = data(c.post("/api/v1/watchlists", json={"security_id": sid}))
        assert data(c.post("/api/v1/watchlists", json={"security_id": sid}))["id"] == watch["id"]
        data(c.post("/api/v1/monitors", json={"security_id": sid, "algorithm_id": "trend-cross-v1", "enabled": True, "parameters": {"fast": 5, "slow": 20}, "agent_mode": "FILTER"}))
        signals = data(c.post("/api/v1/signals/run", json={}))
        assert signals["generated"] == 1
        assert data(c.post("/api/v1/signals/run", json={}))["generated"] == 0
        signal = signals["signals"][0]
        review = data(c.post("/api/v1/reviews", json={"signal_id": signal["id"]}))
        assert review["verdict"] == "WAIT" and review["mode"] == "UNAVAILABLE"
        demo = data(c.post("/api/v1/reviews", json={"signal_id": signal["id"], "demo": True}))
        assert demo["mode"] == "RULE_DEMO" and "非AI" in demo["summary"]
        assert not data(c.get("/api/v1/live/status"))["enabled"]
        assert data(c.post("/api/v1/evaluations/run", json={}))["sample_size"] == 0
        daily = data(c.get("/api/v1/market/bars", params={"security_id": sid}))
        weekly = data(c.get("/api/v1/market/bars", params={"security_id": sid, "timeframe": "1w"}))
        assert len(weekly["bars"]) < len(daily["bars"])
        assert len(daily["indicators"]["ma20"]) == len(daily["bars"])
    with client_for(path) as restored:
        assert len(data(restored.get("/api/v1/watchlists"))) == 1
        assert len(data(restored.get("/api/v1/reviews"))) == 2


def test_csv_atomic_partial_and_source_isolation(tmp_path):
    with client_for(tmp_path / "imports.db") as c:
        data(c.post("/api/v1/demo/seed", json={}))
        demo = data(c.get("/api/v1/securities"))[0]
        csv = f"代码,名称,日期,开盘,最高,最低,收盘,成交量\n{demo['code']},用户导入,2026-10-23,10,12,9,11,1000\n000002,坏行,2026-10-23,10,9,11,10,1000\n"
        preview = data(c.post("/api/v1/data/imports/preview", files={"file": ("导入.csv", csv.encode("gbk"), "text/csv")}))
        assert preview["valid_rows"] == preview["invalid_rows"] == 1
        data(c.post(f"/api/v1/data/imports/{preview['id']}/commit", json={}), 422)
        assert len(data(c.get("/api/v1/securities"))) == 6
        commit = data(c.post(f"/api/v1/data/imports/{preview['id']}/commit", json={"allow_partial": True}))
        assert commit["imported_rows"] == 1
        same_code = [s for s in data(c.get("/api/v1/securities")) if s["code"] == demo["code"]]
        assert len(same_code) == 2 and len({s["id"] for s in same_code}) == 2
        assert data(c.get(f"/api/v1/securities/{demo['id']}"))["quote"] == demo["quote"]


def test_sim_clock_t_plus_one_idempotency_and_comparison(tmp_path):
    with client_for(tmp_path / "sim.db") as c:
        data(c.post("/api/v1/demo/seed", json={}))
        sid = data(c.get("/api/v1/securities"))[0]["id"]
        account = data(c.post("/api/v1/sim/accounts", json={"name": "自定义资金验收", "initial_cash": "76543.21", "mode": "DEMO"}))
        assert account["initial_cash"] == "76543.21"
        aid = account["id"]
        path = f"/api/v1/sim/accounts/{aid}"

        def order(side, key, purpose="BASE", quantity=100, expected=200):
            return data(c.post(path + "/orders", json={"security_id": sid, "side": side, "quantity": quantity, "purpose": purpose, "idempotency_key": key}), expected)

        buy = order("BUY", "buy-base", quantity=200)
        assert buy["market_date"] == account["trade_date"]
        assert buy["quote_as_of"][:10] == account["trade_date"]
        assert order("BUY", "buy-base", quantity=200)["id"] == buy["id"]
        order("BUY", "buy-base", quantity=100, expected=409)
        order("SELL", "t-plus-one", expected=409)
        detail = data(c.get(path))
        assert detail["positions"][0]["sellable"] == 0
        assert detail["comparison"]["t_increment"] == "0.00"
        later = data(c.post(path + "/advance-day", json={}))
        assert later["trade_date"] > account["trade_date"]
        sell = order("SELL", "t-sell", "T")
        back = order("BUY", "t-buy", "T")
        assert sell["price"] == back["price"]
        detail = data(c.get(path))
        comparison = detail["comparison"]
        assert comparison["status"] == "COMPARABLE"
        assert comparison["open_t_quantity"] == 0
        assert Decimal(comparison["t_increment"]) == -(Decimal(sell["fee"]) + Decimal(back["fee"]))
        assert Decimal(comparison["today_actual_pnl"]) - Decimal(comparison["today_baseline_pnl"]) == Decimal(comparison["today_t_increment"])
        assert comparison["today_t_increment"] == comparison["t_increment"]
        assert Decimal(comparison["actual_equity"]) - Decimal(comparison["baseline_equity"]) == Decimal(comparison["t_increment"])
        assert Decimal(detail["account"]["total_pnl"]) == Decimal(detail["account"]["equity"]) - Decimal(account["initial_cash"])
        for _ in range(4):
            data(c.post(path + "/advance-day", json={}))
        data(c.post(path + "/advance-day", json={}), 409)
