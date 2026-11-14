"""自动监测增量的集成验收。

这些测试刻意使用已保存的固定演示行情；不访问外网，也不启动真实交易接口。
部分测试会暴露当前实现尚未满足的契约行为，失败应作为修复清单处理。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.automation import AutomationBusy, stamp, utcnow


ORIGIN = {"Origin": "http://127.0.0.1:8765"}


@pytest.fixture
def app_client(tmp_path):
    app = create_app(tmp_path / "automation.db")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/session").status_code == 200
        client.headers.update(ORIGIN)
        # 生命周期会自动启动调度线程；接口测试手动运行，避免1秒轮询扰动断言。
        app.state.automation.stop()
        yield app, client
    app.state.automation.stop()
    app.state.store.db.close()


def body(response, status=200):
    assert response.status_code == status, response.text
    payload = response.json()
    if status == 200:
        return payload["data"]
    return payload["error"]


def seed(app, client):
    body(client.post("/api/v1/demo/seed", json={}))
    securities = body(client.get("/api/v1/securities"))
    return securities


def monitor(app, client, security_id, mode="FILTER", enabled=True):
    return body(client.post("/api/v1/monitors", json={
        "security_id": security_id,
        "algorithm_id": "trend-cross-v1",
        "enabled": enabled,
        "parameters": {"fast": 5, "slow": 20},
        "agent_mode": mode,
    }))


def make_current_signal(app, client, security_id, mode="FILTER", kind=None):
    monitor(app, client, security_id, mode=mode)
    generated = body(client.post("/api/v1/signals/run", json={}))
    saved = generated["signals"]
    assert saved, "固定演示行情应产生至少一条监测信号"
    signal = next(item for item in saved if item["security"]["id"] == security_id)
    with app.state.store.lock, app.state.store.db:
        raw = app.state.store.get("signal", signal["id"])
        raw["valid_until"] = stamp(utcnow() + timedelta(minutes=10))
        if kind:
            raw["kind"] = kind
        app.state.store.put("signal", raw)
    return app.state.store.get("signal", signal["id"])


def test_default_automation_is_off_and_manual_empty_run_has_no_output(app_client):
    app, client = app_client
    status = body(client.get("/api/v1/automation"))
    assert status["enabled"] is False
    assert status["interval_seconds"] == 60
    assert status["auto_review"] is False
    assert status["next_run_at"] is None
    assert status["worker_running"] is False

    result = body(client.post("/api/v1/automation/run", json={}))
    assert result["status"] == "SUCCEEDED"
    assert result["generated"] == result["reviewed"] == 0
    assert result["skipped"] == 0
    assert body(client.get("/api/v1/automation/runs"))[0]["trigger"] == "MANUAL"


def test_automation_http_origin_and_interval_validation(app_client):
    app, client = app_client
    client.headers.pop("Origin")
    assert client.patch("/api/v1/automation", json={"enabled": True}).status_code == 403
    client.headers.update(ORIGIN)
    assert body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 29}), 422)["code"] == "VALIDATION_ERROR"
    assert body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 3601}), 422)["code"] == "VALIDATION_ERROR"
    configured = body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 30, "auto_review": False}))
    assert configured["enabled"] is True and configured["interval_seconds"] == 30
    assert configured["next_run_at"] is not None


def test_configuration_survives_restart_without_replaying_downtime(tmp_path):
    path = tmp_path / "persist.db"
    first = create_app(path)
    with TestClient(first, base_url="http://127.0.0.1:8765") as client:
        client.get("/api/v1/session"); client.headers.update(ORIGIN)
        first.state.automation.stop()
        configured = body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 45, "auto_review": True}))
        assert configured["next_run_at"]
    first.state.automation.stop(); first.state.store.db.close()

    second = create_app(path)
    with TestClient(second, base_url="http://127.0.0.1:8765") as client:
        client.get("/api/v1/session"); client.headers.update(ORIGIN)
        second.state.automation.stop()
        status = body(client.get("/api/v1/automation"))
        assert status["enabled"] is True
        assert status["interval_seconds"] == 45
        assert status["auto_review"] is True
        assert body(client.get("/api/v1/automation/runs")) == []
    second.state.automation.stop(); second.state.store.db.close()


def test_scheduled_due_run_is_reserved_once_and_next_run_is_future(app_client):
    app, client = app_client
    body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 30}))
    with app.state.store.lock, app.state.store.db:
        config = app.state.automation.config()
        config["next_run_at"] = stamp(utcnow() - timedelta(seconds=1))
        app.state.store.put("automation", config)
    first = app.state.automation.tick()
    second = app.state.automation.tick()
    assert first and first["trigger"] == "SCHEDULED"
    assert second is None
    status = app.state.automation.status()
    assert status["next_run_at"] and datetime.fromisoformat(status["next_run_at"].replace("Z", "+00:00")) > utcnow()
    assert len(body(client.get("/api/v1/automation/runs"))) == 1


def test_manual_run_mutex_returns_busy_while_work_is_running(app_client):
    app, client = app_client
    started = threading.Event()
    release = threading.Event()

    def blocked_work(config, cancelled):
        started.set()
        assert release.wait(3)
        return dict(status="SUCCEEDED", generated=0, reviewed=0, skipped=0, details=["测试工作"])

    app.state.automation.work = blocked_work
    result = {}

    def invoke():
        result["first"] = app.state.automation.run("MANUAL")

    thread = threading.Thread(target=invoke)
    thread.start(); assert started.wait(2)
    with pytest.raises(AutomationBusy):
        app.state.automation.run("MANUAL")
    release.set(); thread.join(4)
    assert result["first"]["status"] == "SUCCEEDED"
    assert body(client.post("/api/v1/automation/run", json={}), 200)["status"] == "SUCCEEDED"


def test_off_watch_and_expired_signals_never_call_llm(app_client, monkeypatch):
    app, client = app_client
    securities = seed(app, client)
    calls = []
    monkeypatch.setenv("AGENT_API_BASE", "http://agent.invalid/v1")
    monkeypatch.setenv("AGENT_MODEL", "test-model")

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("OFF/WATCH/过期信号不应调用模型")

    monkeypatch.setattr("backend.app.httpx.post", forbidden)
    monitor(app, client, securities[0]["id"], mode="OFF")
    off_signal = make_current_signal(app, client, securities[0]["id"], mode="OFF")
    # 另一个信号显式标为WATCH，即使监测为FILTER也不应进入自动复核候选。
    watch_signal = make_current_signal(app, client, securities[1]["id"], mode="FILTER", kind="WATCH")
    expired_signal = make_current_signal(app, client, securities[2]["id"], mode="FILTER")
    with app.state.store.lock, app.state.store.db:
        expired_signal["valid_until"] = stamp(utcnow() - timedelta(seconds=1))
        app.state.store.put("signal", expired_signal)

    body(client.patch("/api/v1/automation", json={"enabled": True, "auto_review": True}))
    result = app.state.automation.run("MANUAL")
    assert result["reviewed"] == 0
    assert calls == []
    attempts = app.state.store.all("automation_review_attempt")
    assert attempts == []
    assert off_signal["id"] != watch_signal["id"] != expired_signal["id"]


def test_unconfigured_auto_review_does_not_create_attempts_or_model_calls(app_client, monkeypatch):
    app, client = app_client
    security = seed(app, client)[0]
    make_current_signal(app, client, security["id"], mode="FILTER")
    body(client.patch("/api/v1/automation", json={"enabled": True, "auto_review": True}))
    result = app.state.automation.run("MANUAL")
    assert result["reviewed"] == 0
    assert "尚未配置LLM" in " ".join(result["details"])
    assert app.state.store.all("automation_review_attempt") == []


def test_configured_failed_review_is_attempted_once_and_not_retried(app_client, monkeypatch):
    app, client = app_client
    security = seed(app, client)[0]
    signal = make_current_signal(app, client, security["id"], mode="FILTER")
    monkeypatch.setenv("AGENT_API_BASE", "http://agent.invalid/v1")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("模拟模型超时")

    monkeypatch.setattr("backend.app.httpx.post", failing)
    body(client.patch("/api/v1/automation", json={"enabled": True, "auto_review": True}))
    first = app.state.automation.run("MANUAL")
    second = app.state.automation.run("MANUAL")
    assert len(calls) == 1
    assert first["reviewed"] == 0
    assert second["reviewed"] == 0
    attempts = app.state.store.all("automation_review_attempt")
    assert len(attempts) == 1 and attempts[0]["status"] == "FAILED"
    assert signal["id"] == attempts[0]["signal_id"]
    assert first["status"] in {"PARTIAL", "FAILED"}


def test_auto_review_caps_calls_at_five_and_keeps_sixth_pending(app_client, monkeypatch):
    app, client = app_client
    securities = seed(app, client)
    for security in securities:
        # 本用例仅测试调用上限：固定六条可行动信号，避免DEMO本身的WATCH减少候选。
        make_current_signal(app, client, security["id"], mode="FILTER", kind="BUY")
    monkeypatch.setenv("AGENT_API_BASE", "http://agent.invalid/v1")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    calls = []

    class GoodResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "verdict": "WAIT", "summary": "模型等待", "supporting_evidence": [],
                "opposing_evidence": [], "unknowns": [], "conditions": [], "limitations": [],
            }, ensure_ascii=False)}}]}

    def successful(*args, **kwargs):
        calls.append(1)
        return GoodResponse()

    monkeypatch.setattr("backend.app.httpx.post", successful)
    body(client.patch("/api/v1/automation", json={"enabled": True, "auto_review": True}))
    result = app.state.automation.run("MANUAL")
    assert len(calls) <= 5
    assert result["reviewed"] == len(calls) <= 5
    assert result["skipped"] >= 1
    assert any("最多5条" in detail for detail in result["details"])
    assert len(app.state.store.all("automation_review_attempt")) == len(calls)


def test_expired_lease_is_recovered_as_interrupted_before_new_run(app_client):
    app, client = app_client
    body(client.patch("/api/v1/automation", json={"enabled": True, "interval_seconds": 30}))
    old_id = "old-running"
    with app.state.store.lock, app.state.store.db:
        app.state.store.put("automation_run", dict(id=old_id, status="RUNNING", trigger="SCHEDULED", started_at=stamp(utcnow()), finished_at=None, generated=0, reviewed=0, skipped=0, error=None, details=[]))
        config = app.state.automation.config()
        config.update(owner=old_id, lease_until=stamp(utcnow() - timedelta(seconds=1)), next_run_at=stamp(utcnow() - timedelta(seconds=1)))
        app.state.store.put("automation", config)
    result = app.state.automation.tick()
    assert result and result["status"] == "SUCCEEDED"
    runs = {item["id"]: item for item in body(client.get("/api/v1/automation/runs"))}
    assert runs[old_id]["status"] == "INTERRUPTED"
    assert old_id not in {result["id"]}


def test_deleting_last_watch_disables_same_security_monitor(app_client):
    app, client = app_client
    security = seed(app, client)[0]
    watch = body(client.post("/api/v1/watchlists", json={"security_id": security["id"]}))
    monitor(app, client, security["id"], mode="FILTER", enabled=True)
    assert body(client.delete(f"/api/v1/watchlists/{watch['id']}"))["deleted"] is True
    monitors = body(client.get("/api/v1/monitors"))
    same = [item for item in monitors if item["security_id"] == security["id"]]
    assert same and all(item["enabled"] is False for item in same)

