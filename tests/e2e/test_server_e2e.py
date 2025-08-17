# tests/e2e/test_server_e2e.py
import os
os.environ.setdefault("PYTHONPATH", "src")

from fastapi.testclient import TestClient
from crypto_ai_bot.app.server import app

client = TestClient(app)


def test_health_endpoints():
    r = client.get("/health")
    assert r.status_code == 200
    assert "components" in r.json()

    r = client.get("/health/details")
    assert r.status_code == 200
    assert "breakers" in r.json()


def test_config_public():
    r = client.get("/config")
    assert r.status_code == 200
    # не должно утекать секретов
    for k in r.json().keys():
        assert not any(s in k.upper() for s in ["API_", "SECRET", "TOKEN", "PASSWORD", "WEBHOOK", "TELEGRAM"])


def test_metrics_contains_breaker_lines():
    r = client.get("/metrics")
    assert r.status_code == 200
    txt = r.text
    assert "broker_created_total" in txt
    assert "breaker_state" in txt


def test_tick_and_last_ok():
    r = client.post("/tick", json={"symbol": "BTC/USDT", "timeframe": "1h", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") in ("ok", "error")  # допускаем ok/error, главное — не 5xx

    r2 = client.get("/last?limit=1")
    # decisions repo может быть опционален; в этом случае будет error
    assert r2.status_code == 200
    j2 = r2.json()
    assert "status" in j2


def test_positions_and_orders_ok():
    r = client.get("/positions/open")
    assert r.status_code == 200
    r = client.get("/orders/recent?limit=5")
    assert r.status_code == 200
