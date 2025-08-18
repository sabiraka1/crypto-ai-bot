# tests/test_api_health_metrics.py
from __future__ import annotations
import sqlite3
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

# Мы подменим build_container на фейковый контейнер, чтобы сервер поднялся быстро и стабильно.


# --- Фейки минимально нужных зависимостей ---

@dataclass
class _Settings:
    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "1h"
    MODE: str = "paper"
    DB_PATH: str = ":memory:"


class _Bus:
    def health(self):
        return {"running": True, "dlq_size": 0, "queue_size": 0, "queue_cap": 1000}


class _Broker:
    def fetch_ticker(self, symbol: str):
        # health будет считать broker-ok, если тут не упадёт
        return {"symbol": symbol, "last": 100.0}


class _TradesRepo:
    def __init__(self, con): self.con = con
    def count_pending(self): return 0


class _PositionsRepo:
    def __init__(self, con): self.con = con
    def get_open(self): return []


class _IdempotencyRepo:
    def __init__(self, con): self.con = con
    def cleanup_expired(self, ttl_seconds: int = 300): return 0


class _AuditRepo:
    def __init__(self, con): self.con = con


@dataclass
class _Container:
    settings: _Settings
    con: sqlite3.Connection
    broker: _Broker
    bus: _Bus
    trades_repo: _TradesRepo
    positions_repo: _PositionsRepo
    idempotency_repo: _IdempotencyRepo
    audit_repo: _AuditRepo


def _make_sqlite():
    con = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    # минимальные таблицы, чтобы /health не спотыкался на PRAGMA user_version
    con.execute("PRAGMA user_version = 1")
    # метрики/telegram ничего не требуют, но оставим базовые схемы на будущее
    con.execute("""
    CREATE TABLE IF NOT EXISTS trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT, side TEXT, price REAL, qty REAL, fee_amt REAL,
      ts INTEGER, state TEXT
    )""")
    con.execute("""
    CREATE TABLE IF NOT EXISTS positions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT UNIQUE, qty REAL, avg_price REAL
    )""")
    return con


@pytest.fixture
def client(monkeypatch):
    # Подменяем compose.build_container, чтобы server.lifespan использовал наш контейнер
    from crypto_ai_bot.app import compose as _compose

    def _fake_build():
        con = _make_sqlite()
        return _Container(
            settings=_Settings(),
            con=con,
            broker=_Broker(),
            bus=_Bus(),
            trades_repo=_TradesRepo(con),
            positions_repo=_PositionsRepo(con),
            idempotency_repo=_IdempotencyRepo(con),
            audit_repo=_AuditRepo(con),
        )

    monkeypatch.setattr(_compose, "build_container", _fake_build, raising=True)

    # Теперь импортируем сервер и создаём TestClient — lifespan вызовет наш _fake_build()
    from crypto_ai_bot.app.server import app
    with TestClient(app) as c:
        yield c


def test_metrics_returns_text(client: TestClient):
    r = client.get("/metrics", timeout=10)
    assert r.status_code == 200
    # Prometheus-текст
    assert "version=0.0.4" in r.headers.get("content-type", "")
    assert isinstance(r.text, str)
    assert len(r.text) > 0


def test_health_ok(client: TestClient):
    r = client.get("/health", timeout=10)
    assert r.status_code in (200, 503)  # ok или degraded
    data = r.json()
    assert "status" in data
    assert "broker" in data
    assert "db" in data
    assert "bus" in data
    assert "time_sync" in data
