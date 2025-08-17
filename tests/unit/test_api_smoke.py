# tests/unit/test_api_smoke.py
import os
os.environ.setdefault("PYTHONPATH", "src")

from fastapi.testclient import TestClient

from crypto_ai_bot.app.server import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "components" in body


def test_health_details_ok():
    r = client.get("/health/details")
    assert r.status_code == 200
    body = r.json()
    assert "breakers" in body


def test_config_public_ok():
    r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    # Не должно быть секретов
    for k in body.keys():
        assert not any(p in k.upper() for p in ["API_", "SECRET", "TOKEN", "PASSWORD", "WEBHOOK", "TELEGRAM"])


def test_metrics_ok():
    r = client.get("/metrics")
    assert r.status_code == 200
    txt = r.text
    assert "broker_created_total" in txt
    assert "breaker_state" in txt


def test_positions_open_ok():
    r = client.get("/positions/open")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["items"], list)


def test_orders_recent_ok():
    r = client.get("/orders/recent?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["items"], list)


def test_alerts_test_ok():
    r = client.post("/alerts/test", params={"message": "hello"})
    assert r.status_code == 200
    assert r.json().get("echo") == "hello"
