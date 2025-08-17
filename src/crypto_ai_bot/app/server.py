from __future__ import annotations

import json
import time
from fastapi import FastAPI, Request
from typing import Any, Dict

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.metrics import export as metrics_export, inc
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.time_sync import measure_time_drift, get_last_drift_ms
from crypto_ai_bot.utils.http_client import get_http_client

from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations import runner

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.events.async_bus import AsyncBus, Event


# ------------------------ App init ------------------------

cfg = Settings.build()
init_logging()
app = FastAPI(title="crypto-ai-bot")

# sqlite
_db_con = connect(getattr(cfg, "DB_PATH", ":memory:"))

# broker через фабрику
_broker = create_broker(cfg)

# event bus
app.state.bus = AsyncBus()


# ------------------------ Helpers ------------------------

def _health_matrix(db_ok: bool, broker_ok: bool, drift_ms: int, limit_ms: int, mig_ok: bool) -> Dict[str, Any]:
    """
    Возвращаем сводный статус по матрице.
    """
    if (not db_ok) or (abs(drift_ms) > limit_ms) or (not mig_ok):
        return {"status": "unhealthy", "degradation_level": "critical"}
    if not broker_ok:
        return {"status": "degraded", "degradation_level": "no_trading"}
    return {"status": "healthy", "degradation_level": "none"}


# ------------------------ Routes ------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    # DB
    t0 = time.perf_counter()
    db_ok = True
    try:
        _db_con.execute("SELECT 1").fetchone()
    except Exception:
        db_ok = False
    db_latency = int((time.perf_counter() - t0) * 1000)

    # Migrations
    cur_v = 0
    latest_v = 0
    mig_ok = False
    try:
        cur_v = runner.get_current_version(_db_con)
        latest_v = runner.latest_version()
        mig_ok = cur_v >= latest_v
    except Exception:
        mig_ok = False

    # Broker
    t1 = time.perf_counter()
    bro_status = "ok"
    try:
        _ = _broker.fetch_ticker(getattr(cfg, "SYMBOL", "BTC/USDT"))
        broker_ok = True
    except Exception as exc:  # noqa: BLE001
        bro_status = f"error:{exc.__class__.__name__}"
        broker_ok = False
    bro_latency = int((time.perf_counter() - t1) * 1000)

    # Time drift — если ещё не мерили, сделаем замер
    try:
        if get_last_drift_ms() == 0:
            measure_time_drift(getattr(cfg, "TIME_DRIFT_URLS", []))
    except Exception:
        pass
    drift_ms = int(get_last_drift_ms() or 0)
    limit_ms = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000))

    matrix = _health_matrix(db_ok, broker_ok, drift_ms, limit_ms, mig_ok)

    # Circuit stats (если брокер поддерживает)
    cb_stats = {}
    try:
        if hasattr(_broker, "get_cb_stats"):
            cb_stats = _broker.get_cb_stats() or {}
    except Exception:
        cb_stats = {}

    return {
        **matrix,
        "components": {
            "mode": "paper" if getattr(cfg, "PAPER_MODE", True) else "live",
            "db": {"status": "ok" if db_ok else "error", "latency_ms": db_latency,
                   "schema_version": cur_v, "latest": latest_v, "migrations_ok": mig_ok},
            "broker": {"status": bro_status, "latency_ms": bro_latency, "circuit": cb_stats},
            "time": {"status": "ok", "drift_ms": drift_ms, "limit_ms": limit_ms},
        },
    }


@app.get("/metrics")
async def metrics() -> str:
    return metrics_export()


@app.get("/bus")
async def bus_stats() -> Dict[str, Any]:
    bus = getattr(app.state, "bus", None)
    if bus and hasattr(bus, "stats"):
        return bus.stats()
    return {"status": "no_bus"}


@app.post("/tick")
async def tick() -> Dict[str, Any]:
    # Для простого прогона evaluate без Telegram
    try:
        # Публикация тестового события в шину (проверка очередей)
        bus: AsyncBus = app.state.bus
        await bus.publish(Event(type="MetricEvent", payload={"kind": "tick"}))
        inc("tick_total")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"tick_failed: {exc}"}
