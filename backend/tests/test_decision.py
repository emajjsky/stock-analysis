from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.decision import evaluate_gate

AT = datetime(2026, 10, 27, 7, 30, tzinfo=timezone.utc)


def fixtures(mode="FILTER"):
    signal = dict(id="signal-1", kind="BUY", status="CONFIRMED", version="1.0.0", algorithm_version="1.0.0",
                  confirmed_at="2026-10-27T07:00:00Z", valid_until="2026-10-28T07:00:00Z", input_snapshot_hash="current")
    monitor = dict(enabled=True, agent_mode=mode)
    review = dict(signal_id="signal-1", signal_version="1.0.0", input_snapshot_hash="current", mode="LLM",
                  verdict="SUPPORT", conditions=[], created_at="2026-10-27T07:05:00Z", valid_until=signal["valid_until"])
    return signal, monitor, review


def gate(signal, monitor, review, current_hash="current", configured=True):
    return evaluate_gate(signal, monitor, review, current_hash, "1.0.0", configured, AT)


@pytest.mark.parametrize("mode", ["OFF", "EXPLAIN"])
def test_non_filter_mode_never_grants_permission(mode):
    signal, monitor, review = fixtures(mode)
    result = gate(signal, monitor, review)
    assert result["gate_passed"] is None
    assert result["execution_permission"] == "NOT_EVALUATED"


@pytest.mark.parametrize("change", ["missing", "unconfigured", "demo", "expired", "hash", "version", "conditions", "wait", "reject", "conditional"])
def test_filter_requires_valid_bound_unconditional_model_support(change):
    signal, monitor, review = fixtures()
    configured = True
    if change == "missing": review = None
    elif change == "unconfigured": configured = False
    elif change == "demo": review["mode"] = "RULE_DEMO"
    elif change == "expired": review["valid_until"] = "2026-10-27T07:20:00Z"
    elif change == "hash": review["input_snapshot_hash"] = "old"
    elif change == "version": review["signal_version"] = "0.9.0"
    elif change == "conditions": review["conditions"] = ["人工核对财报"]
    else: review["verdict"] = {"wait": "WAIT", "reject": "REJECT", "conditional": "CONDITIONAL"}[change]
    result = gate(signal, monitor, review, configured=configured)
    assert result["gate_passed"] is False
    assert result["execution_permission"] == "NOT_EVALUATED"


def test_support_passes_only_review_filter_and_never_account_execution():
    result = gate(*fixtures())
    assert result["gate_passed"] is True
    assert result["status"] == "PASSED"
    assert "不构成下单许可" in result["execution_label"]


def test_research_revision_change_blocks_old_review():
    signal, monitor, review = fixtures()
    review['research_revision_hash'] = 'old'
    result = evaluate_gate(signal, monitor, review, 'current', '1.0.0', True, AT, current_research_hash='new')
    assert result['gate_passed'] is False
    assert any(check['id'] == 'research_binding' and check['passed'] is False for check in result['checks'])


@pytest.mark.parametrize("change", ["expired", "future", "disabled", "input", "watch", "invalidated"])
def test_base_constraints_block_even_with_model_support(change):
    signal, monitor, review = fixtures()
    current_hash = "current"
    if change == "expired": signal["valid_until"] = "2026-10-27T07:20:00Z"
    elif change == "future": signal["confirmed_at"] = "2026-10-27T08:00:00Z"
    elif change == "disabled": monitor["enabled"] = False
    elif change == "input": current_hash = "changed"
    elif change == "watch": signal["kind"] = "WATCH"
    else: signal["status"] = "INVALIDATED"
    result = gate(signal, monitor, review, current_hash)
    assert result["gate_passed"] is False


def test_parameter_change_invalidates_saved_signal_and_new_signal_preserves_history(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_API_BASE", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    app = create_app(tmp_path / "signals.db")
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Origin": "http://127.0.0.1:8765"}) as client:
        client.get("/api/v1/session")
        client.post("/api/v1/demo/seed", json={})
        monitor = dict(security_id="DEMO.000001", algorithm_id="trend-cross-v1", enabled=True, parameters={"fast": 5, "slow": 20}, agent_mode="FILTER")
        client.post("/api/v1/monitors", json=monitor)
        original = client.post("/api/v1/signals/run", json={}).json()["data"]["signals"][0]
        store = app.state.store
        saved = deepcopy(store.get("signal", original["id"]))
        instant = datetime.now(timezone.utc)
        saved.update(confirmed_at=(instant-timedelta(minutes=1)).isoformat(), valid_until=(instant+timedelta(hours=1)).isoformat())
        with store.lock, store.db: store.put("signal", saved)
        monitor["parameters"] = {"fast": 3, "slow": 10}
        client.post("/api/v1/monitors", json=monitor)
        invalidated = client.get("/api/v1/signals").json()["data"][0]
        assert invalidated["status"] == "INVALIDATED"
        assert invalidated["decision"]["gate_passed"] is False
        assert store.get("signal", saved["id"])["input_snapshot_hash"] == original["input_snapshot_hash"]
        second = client.post("/api/v1/signals/run", json={}).json()["data"]
        assert second["generated"] == 1
        assert second["signals"][0]["id"] != original["id"]
        assert len(client.get("/api/v1/signals").json()["data"]) == 2
    store.db.close()


def test_off_blocks_model_call_and_filter_binds_structured_model_result(tmp_path, monkeypatch):
    import backend.app as app_module

    monkeypatch.setenv("AGENT_API_BASE", "https://model.invalid/v1")
    monkeypatch.setenv("AGENT_MODEL", "fixture-model")
    calls = []

    class ModelResponse:
        def raise_for_status(self): pass
        def json(self):
            import json
            content = dict(verdict="SUPPORT", summary="仅用于接口验证的模型响应", supporting_evidence=["测试趋势条件"], opposing_evidence=[], unknowns=[], conditions=[], limitations=["测试替身，不是有效性证据"])
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

    def model_post(*args, **kwargs):
        calls.append(True)
        return ModelResponse()

    monkeypatch.setattr(app_module.httpx, "post", model_post)
    app = create_app(tmp_path / "model-contract.db")
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Origin": "http://127.0.0.1:8765"}) as client:
        client.get("/api/v1/session")
        client.post("/api/v1/demo/seed", json={})
        monitor = dict(security_id="DEMO.000003", algorithm_id="trend-cross-v1", enabled=True, parameters={"fast": 5, "slow": 20}, agent_mode="OFF")
        client.post("/api/v1/monitors", json=monitor)
        signal = client.post("/api/v1/signals/run", json={}).json()["data"]["signals"][0]
        store = app.state.store
        saved = store.get("signal", signal["id"])
        instant = datetime.now(timezone.utc)
        saved.update(confirmed_at=(instant-timedelta(minutes=1)).isoformat(), valid_until=(instant+timedelta(hours=1)).isoformat())
        with store.lock, store.db: store.put("signal", saved)
        off_review = client.post("/api/v1/reviews", json={"signal_id": saved["id"]}).json()["data"]
        assert off_review["verdict"] == "WAIT" and calls == []
        monitor["agent_mode"] = "FILTER"
        client.post("/api/v1/monitors", json=monitor)
        model_review = client.post("/api/v1/reviews", json={"signal_id": saved["id"]}).json()["data"]
        assert model_review["mode"] == "LLM" and len(calls) == 1
        current = client.get("/api/v1/signals").json()["data"][0]
        assert current["decision"]["gate_passed"] is True
        assert current["decision"]["execution_permission"] == "NOT_EVALUATED"
    app.state.store.db.close()
